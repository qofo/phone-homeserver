#!/usr/bin/env bash
# ==============================================================================
# Supervisor & commands for code-server (VS Code in the browser), tailnet only
#
# code-server gives a full editor and terminal on this phone, so it listens on the
# Tailscale address only, over HTTPS with a password. The certificate comes from a
# local CA whose name constraints allow only Tailscale addresses (100.64.0.0/10,
# fd7a:115c:a1e0::/48) and *.ts.net names, so trusting it on a client cannot be used
# to impersonate any other site.
#
# Kept apart from start_services.sh (public blog) and private_docs.sh (docs viewer).
# start-daemon is launched from the Termux side (/root/termux/ensure-code-server.sh),
# because proot-distro's --kill-on-exit ends whatever a proot login started.
# ==============================================================================

CS_BIN="/root/.local/lib/code-server/bin/code-server"
# Main process and its helpers (extension host, pty host, file watcher) all run this node
PATTERN='^/root/\.local/lib/code-server[^/ ]*/lib/node '
PORT=8443
# MagicDNS name of this device (Tailscale admin console). The certificate carries it
# beside the Tailscale IP, so the editor can be opened by name even if the IP changes.
# Leave empty to use the IP only; the CA's name constraints allow any *.ts.net name.
MAGIC_DNS=""   # e.g. "phone.tailnet-name.ts.net"
WORKSPACE="/root"
CONF_DIR="/root/.config/code-server"
TLS_DIR="$CONF_DIR/tls"
CA_KEY="$TLS_DIR/ca.key"
CA_CRT="$TLS_DIR/ca.crt"
SRV_KEY="$TLS_DIR/server.key"
SRV_CRT="$TLS_DIR/server.crt"
# Written by the supervisor: "listening IP:PORT", "waiting" (no Tailscale address yet)
# or "offline IP:PORT" (Tailscale went away after binding)
STATE_FILE="/root/.code_server.state"
PID_FILE="/root/.code_server.pid"
LOCK_FILE="/root/.code_server.lock"
DISABLED_FLAG="/root/.code_server_disabled"
RESTART_FLAG="/root/.code_server_restart"
LOG="/root/code_server.log"
LOG_MAX_BYTES=$((2 * 1024 * 1024))
CHECK_INTERVAL=15
# code-server needs well over 30 seconds to come up on this phone
GRACE=90
# Renew the server certificate when it has less than 30 days left
RENEW_BEFORE=$((30 * 86400))

TERMUX_BIN="/data/data/com.termux/files/usr/bin"
# /root/termux/ensure-code-server.sh as seen from the Termux side
LAUNCHER="/data/data/com.termux/files/usr/var/lib/proot-distro/containers/ubuntu/rootfs/root/termux/ensure-code-server.sh"
LAUNCH_JOB_ID=4246

log() {
    # KST like private_docs.log; the proot has no zoneinfo, hence the POSIX TZ
    echo "[$(TZ=KST-9 date '+%Y-%m-%d %H:%M:%S KST')] [supervisor] $*" >> "$LOG"
}

daemon_pid() {
    # Prints the supervisor PID if one is alive
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null) && [ -n "$pid" ] || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "code_server.sh start-daemon" || return 1
    echo "$pid"
}

no_daemon() {
    ! daemon_pid >/dev/null
}

server_pid() {
    # Oldest matching process = the main server
    pgrep -o -f "$PATTERN"
}

tailnet_ip() {
    # This device's Tailscale IPv4 address, whatever the VPN interface is called (tun0, tun1...).
    # There is no `ip` command and /proc/net/fib_trie is unreadable, so ask the kernel per
    # interface (SIOCGIFADDR), as private_docs_server.py does.
    python3 - <<'EOF'
import fcntl, ipaddress, socket, struct
net = ipaddress.ip_network("100.64.0.0/10")
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for _, name in socket.if_nameindex():
    try:
        packed = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
    except OSError:
        continue
    ip = socket.inet_ntoa(packed[20:24])
    if ipaddress.ip_address(ip) in net:
        print(ip)
        break
EOF
}

healthy() {
    # healthy ADDR: /healthz answers without a login; --cacert also proves the certificate is ours
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 --cacert "$CA_CRT" "https://$1/healthz")" = "200" ]
}

# ---------------------------------------------------------
# Certificates
# ---------------------------------------------------------
make_ca() {
    log "[TLS] Creating the local CA (name-constrained to Tailscale addresses and *.ts.net)"
    ( umask 077 && mkdir -p "$TLS_DIR" ) || return 1
    ( umask 077 && openssl req -x509 -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
        -keyout "$CA_KEY" -out "$CA_CRT" -days 3650 -sha256 \
        -subj "/O=phone-homeserver/CN=code-server local CA ($(date -u +%Y-%m-%d))" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -addext "subjectKeyIdentifier=hash" \
        -addext "nameConstraints=critical,permitted;IP:100.64.0.0/255.192.0.0,permitted;IP:fd7a:115c:a1e0:0:0:0:0:0/ffff:ffff:ffff:0:0:0:0:0,permitted;DNS:ts.net" \
        ) >/dev/null 2>&1 || return 1
    chmod 644 "$CA_CRT"
}

cert_ok() {
    # cert_ok IP: server certificate exists, chains to our CA, names IP and is not about to expire
    [ -s "$SRV_CRT" ] && [ -s "$SRV_KEY" ] || return 1
    openssl verify -CAfile "$CA_CRT" "$SRV_CRT" >/dev/null 2>&1 || return 1
    openssl x509 -in "$SRV_CRT" -noout -checkend "$RENEW_BEFORE" >/dev/null 2>&1 || return 1
    local names
    names=$(openssl x509 -in "$SRV_CRT" -noout -ext subjectAltName 2>/dev/null)
    grep -qw "IP Address:$1" <<<"$names" || return 1
    [ -z "$MAGIC_DNS" ] || grep -qw "DNS:$MAGIC_DNS" <<<"$names"
}

issue_cert() {
    # issue_cert IP: 397 days (browsers reject longer server certificates), P-256
    local tmp
    tmp=$(mktemp -d) || return 1
    printf '%s\n' "basicConstraints=critical,CA:FALSE" "keyUsage=critical,digitalSignature" \
        "extendedKeyUsage=serverAuth" "subjectAltName=IP:$1${MAGIC_DNS:+,DNS:$MAGIC_DNS}" \
        "subjectKeyIdentifier=hash" "authorityKeyIdentifier=keyid" > "$tmp/ext"
    if ( umask 077 && openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
            -keyout "$tmp/key" -out "$tmp/csr" -subj "/CN=code-server $1" ) >/dev/null 2>&1 \
        && openssl x509 -req -in "$tmp/csr" -CA "$CA_CRT" -CAkey "$CA_KEY" \
            -set_serial "0x$(openssl rand -hex 16)" -days 397 -sha256 -extfile "$tmp/ext" \
            -out "$tmp/crt" >/dev/null 2>&1 \
        && openssl verify -CAfile "$CA_CRT" "$tmp/crt" >/dev/null 2>&1; then
        mv -f "$tmp/key" "$SRV_KEY" && mv -f "$tmp/crt" "$SRV_CRT"
        rm -rf "$tmp"
        log "[TLS] Issued server certificate for $1${MAGIC_DNS:+ and $MAGIC_DNS} (valid 397 days)"
        return 0
    fi
    rm -rf "$tmp"
    log "[TLS] Failed to issue a server certificate for $1"
    return 1
}

ensure_cert() {
    # ensure_cert IP
    { [ -s "$CA_KEY" ] && [ -s "$CA_CRT" ]; } || make_ca || { log "[TLS] Failed to create the CA"; return 1; }
    cert_ok "$1" || issue_cert "$1"
}

# ---------------------------------------------------------
# Supervisor (start-daemon)
# ---------------------------------------------------------
CHILD="" BOUND="" STARTED=0 DELAY=0 NEXT=0 FAILED=0 CERT_CHECKED=0

child_alive() {
    # True while PID is a live (non-zombie) child of this supervisor
    local stat
    stat=$(cat "/proc/$1/stat" 2>/dev/null) || return 1
    set -- ${stat##*) }
    [ "$1" != "Z" ] && [ "$2" = "$$" ]
}

set_state() {
    echo "$1" > "$STATE_FILE.tmp" && mv -f "$STATE_FILE.tmp" "$STATE_FILE"
}

spawn() {
    # spawn IP
    # 9>&- keeps the supervisor lock out of the child. The password lives in config.yaml.
    "$CS_BIN" --bind-addr "$1:$PORT" --auth password --cert "$SRV_CRT" --cert-key "$SRV_KEY" \
        --disable-telemetry --disable-update-check "$WORKSPACE" \
        </dev/null >> "$LOG" 2>&1 9>&- &
    CHILD=$!
    BOUND=$1
    STARTED=$SECONDS
    CERT_CHECKED=$SECONDS
    FAILED=0
    set_state "listening $1:$PORT"
    log "[START] code-server on https://$1:$PORT/ (pid $CHILD)"
}

stop_child() {
    local pid=$CHILD i
    CHILD=""
    [ -n "$pid" ] || return 0
    if child_alive "$pid"; then
        kill "$pid" 2>/dev/null
        for i in 1 2 3 4 5 6 7 8 9 10; do
            child_alive "$pid" || break
            sleep 1
        done
        child_alive "$pid" && kill -9 "$pid" 2>/dev/null
    fi
    wait "$pid" 2>/dev/null
    # Helpers (extension host, pty host) must not outlive the main process
    pkill -f "$PATTERN" 2>/dev/null
    rm -f "$STATE_FILE"
}

back_off() {
    # back_off SECONDS_UP: dying within 5 minutes of starting waits 15s, 30s, 60s ... up to 5 minutes
    if [ "$1" -lt 300 ]; then
        DELAY=$((DELAY ? DELAY * 2 : CHECK_INTERVAL))
        [ "$DELAY" -gt 300 ] && DELAY=300
    else
        DELAY=0
    fi
    NEXT=$((SECONDS + DELAY))
}

supervise() {
    local ip up rc
    ip=$(tailnet_ip)

    if [ -n "$CHILD" ]; then
        up=$((SECONDS - STARTED))
        if child_alive "$CHILD"; then
            if [ -z "$ip" ]; then
                # The VPN went away; the socket stays bound and works again when it returns
                set_state "offline $BOUND:$PORT"
                return
            fi
            if [ "$ip" != "$BOUND" ]; then
                log "[REBIND] Tailscale address changed ($BOUND -> $ip); restarting"
                stop_child
                DELAY=0
                NEXT=$SECONDS
            else
                set_state "listening $BOUND:$PORT"
                # Twice a day, renew a certificate that is about to expire
                if [ $((SECONDS - CERT_CHECKED)) -ge 43200 ]; then
                    CERT_CHECKED=$SECONDS
                    if ! cert_ok "$ip"; then
                        log "[TLS] Server certificate needs renewal; restarting"
                        stop_child
                        DELAY=0
                        NEXT=$SECONDS
                    fi
                fi
            fi
            if [ -n "$CHILD" ]; then
                [ "$up" -ge "$GRACE" ] || return
                if healthy "$BOUND:$PORT"; then
                    FAILED=0
                    [ "$up" -ge 300 ] && DELAY=0
                    return
                fi
                FAILED=$((FAILED + 1))
                log "[WARN] health check failed (up ${up}s, failure $FAILED/3)"
                [ "$FAILED" -ge 3 ] || return
                log "[HUNG DETECTED] code-server is unresponsive (pid $CHILD); terminating"
                stop_child
                back_off 0
                return
            fi
        else
            wait "$CHILD" 2>/dev/null
            rc=$?
            CHILD=""
            pkill -f "$PATTERN" 2>/dev/null
            back_off "$up"
            log "[CRASH DETECTED] code-server exited (code $rc, up ${up}s); restarting in ${DELAY}s"
        fi
    fi

    [ "$SECONDS" -ge "$NEXT" ] || return
    if [ -z "$ip" ]; then
        set_state "waiting"
        return
    fi
    if ! ensure_cert "$ip"; then
        DELAY=300
        NEXT=$((SECONDS + DELAY))
        return
    fi
    spawn "$ip"
}

rotate_log() {
    # copytruncate, so code-server's O_APPEND descriptor keeps working
    local size
    size=$(stat -c %s "$LOG" 2>/dev/null) || return 0
    [ "$size" -gt "$LOG_MAX_BYTES" ] || return 0
    cp "$LOG" "$LOG.1" && : > "$LOG"
    log "[LOG] Rotated $LOG ($size bytes)"
}

start_daemon() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        echo "[INFO] code-server supervisor already running (PID $(daemon_pid))."
        exit 0
    fi
    # Write-then-rename so the launcher never reads a half-written PID file
    echo "$$" > "$PID_FILE.tmp" && mv -f "$PID_FILE.tmp" "$PID_FILE"
    rm -f "$RESTART_FLAG"
    log "[DAEMON] Supervisor started (pid $$)"

    trap 'log "[DAEMON] Supervisor stopping"; stop_child; exit 0' TERM INT HUP
    trap 'rm -f "$PID_FILE"' EXIT

    # This supervisor owns code-server: clear out copies started any other way
    pkill -f "$PATTERN" && log "Stopped an unsupervised code-server"

    while true; do
        # A flag file rather than a signal: processes started from the Termux app inherit
        # a mask with SIGUSR1 blocked (see start_services.sh restart)
        if [ -e "$RESTART_FLAG" ]; then
            rm -f "$RESTART_FLAG"
            log "[RESTART] Restart requested"
            stop_child
            DELAY=0
            NEXT=0
        fi
        supervise
        rotate_log

        # Sleeping in the background lets the TERM trap run immediately
        sleep "$CHECK_INTERVAL" 9>&- &
        wait $!
    done
}

# ---------------------------------------------------------
# Commands
# ---------------------------------------------------------
wait_until() {
    # wait_until SECONDS COMMAND...: polls COMMAND once per second
    local deadline=$((SECONDS + $1))
    shift
    until "$@"; do
        [ "$SECONDS" -ge "$deadline" ] && return 1
        sleep 1
    done
}

request_daemon() {
    # Termux:API runs the launcher outside proot; the job fires within seconds once a network is up
    timeout 30 "$TERMUX_BIN/termux-job-scheduler" --job-id "$LAUNCH_JOB_ID" --battery-not-low false \
        --script "$LAUNCHER" >/dev/null 2>&1
}

serving() {
    local state
    state=$(cat "$STATE_FILE" 2>/dev/null)
    case "$state" in
        listening\ *) healthy "${state#listening }" ;;
        waiting) return 0 ;;
        *) return 1 ;;
    esac
}

running() {
    daemon_pid >/dev/null && serving
}

status() {
    local pid state addr code rss
    echo "=== code-server (Tailscale only) ==="
    if pid=$(daemon_pid); then
        echo "Supervisor: [RUNNING] (PID $pid)"
    else
        echo "Supervisor: [STOPPED]"
    fi

    pid=$(server_pid)
    state=$(cat "$STATE_FILE" 2>/dev/null)
    if [ -z "$pid" ]; then
        case "$state" in
            waiting) echo "Server:     [WAITING] - no Tailscale address yet; is the VPN on?" ;;
            *) echo "Server:     [STOPPED]" ;;
        esac
    else
        # Resident memory of every code-server process (main, extension host, pty host...)
        rss=$(ps -o rss= -p "$(pgrep -d, -f "$PATTERN")" 2>/dev/null | awk '{s+=$1} END {printf "%d", s/1024}')
        case "$state" in
            listening\ *)
                addr=${state#listening }
                code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 --cacert "$CA_CRT" "https://$addr/healthz")
                echo "Server:     [RUNNING] (PID $pid, ${rss:-?} MB) - https://$addr/ (healthz HTTP $code)"
                [ -z "$MAGIC_DNS" ] || echo "            also https://$MAGIC_DNS:$PORT/ (same certificate)"
                ;;
            offline\ *)
                echo "Server:     [OFFLINE] (PID $pid) - bound to ${state#offline }, but Tailscale is down"
                ;;
            *)
                echo "Server:     [STARTING] (PID $pid)"
                ;;
        esac
    fi

    if [ -s "$SRV_CRT" ]; then
        echo "TLS:        server certificate valid until $(openssl x509 -in "$SRV_CRT" -noout -enddate | cut -d= -f2)"
        echo "            CA to trust on your devices: $CA_CRT"
        echo "            CA SHA-256 $(openssl x509 -in "$CA_CRT" -noout -fingerprint -sha256 | cut -d= -f2)"
    else
        echo "TLS:        no certificate yet (created on first start)"
    fi
    echo "Password:   in $CONF_DIR/config.yaml (not shown here)"
    if [ -e "$DISABLED_FLAG" ]; then
        echo "Auto-start: [DISABLED] - resume with: $0 start"
    else
        echo "Auto-start: [ENABLED]"
    fi
}

start() {
    local pid
    rm -f "$DISABLED_FLAG"
    if pid=$(daemon_pid); then
        echo "[INFO] Supervisor already running (PID $pid)."
    else
        echo "[START] Asking Termux to launch the code-server supervisor outside this proot session..."
        request_daemon
        if wait_until 150 running; then
            echo "[OK] code-server supervisor is up."
        else
            echo "[WARN] Not serving after 150s. The launch job waits for a network connection;"
            echo "       you can also run it from a Termux (non-proot) shell: $LAUNCHER"
            echo "       Log: $LOG"
        fi
    fi
    status
}

stop() {
    local pid
    touch "$DISABLED_FLAG"
    if pid=$(daemon_pid); then
        echo "[STOP] Stopping supervisor (PID $pid)..."
        kill "$pid"
        wait_until 20 no_daemon || echo "[WARN] Supervisor still running after 20s."
    fi
    rm -f "$RESTART_FLAG"
    pkill -f "$PATTERN" && echo "code-server stopped."
    rm -f "$STATE_FILE"
    echo "[INFO] Auto-start disabled until '$0 start'."
}

server_restarted() {
    local pid
    pid=$(server_pid)
    [ -n "$pid" ] && [ "$pid" != "$1" ] && serving
}

restart() {
    local pid old
    if ! pid=$(daemon_pid); then
        start
        return
    fi
    old=$(server_pid)
    echo "[RESTART] Asking supervisor (PID $pid) to restart code-server..."
    : > "$RESTART_FLAG"
    if wait_until 150 server_restarted "$old"; then
        echo "[OK] code-server restarted."
    else
        rm -f "$RESTART_FLAG"
        echo "[WARN] code-server not back after 150s; see $LOG"
    fi
    status
}

case "$1" in
    start)
        start
        ;;
    start-daemon)
        start_daemon
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|start-daemon}"
        status
        ;;
esac
