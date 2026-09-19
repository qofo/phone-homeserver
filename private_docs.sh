#!/usr/bin/env bash
# ==============================================================================
# Supervisor & commands for the tailnet-only document viewer (private_docs_server.py)
#
# Kept apart from start_services.sh on purpose: the public blog and ngrok have their
# own supervisor, and nothing here can stop, restart or delay them. Like that one,
# start-daemon is launched from the Termux side (/root/termux/ensure-private-docs.sh),
# because proot-distro's --kill-on-exit ends whatever a proot login started.
# ==============================================================================

SERVER="/root/private_docs_server.py"
PATTERN='^python3 (-u )?/root/private_docs_server\.py'
LIST_FILE="/root/private_docs.list"
# Written by the server: "listening IP:PORT", "waiting" (no Tailscale address yet)
# or "offline IP:PORT" (Tailscale went away after binding)
STATE_FILE="/root/.private_docs.state"
PID_FILE="/root/.private_docs.pid"
LOCK_FILE="/root/.private_docs.lock"
DISABLED_FLAG="/root/.private_docs_disabled"
RESTART_FLAG="/root/.private_docs_restart"
LOG="/root/private_docs.log"
LOG_MAX_BYTES=$((2 * 1024 * 1024))
CHECK_INTERVAL=10

TERMUX_BIN="/data/data/com.termux/files/usr/bin"
# /root/termux/ensure-private-docs.sh as seen from the Termux side
LAUNCHER="/data/data/com.termux/files/usr/var/lib/proot-distro/containers/ubuntu/rootfs/root/termux/ensure-private-docs.sh"
LAUNCH_JOB_ID=4244

log() {
    # Same clock as the server's own lines (KST); the proot has no zoneinfo, hence the POSIX TZ
    echo "[$(TZ=KST-9 date '+%Y-%m-%d %H:%M:%S KST')] [supervisor] $*" >> "$LOG"
}

daemon_pid() {
    # Prints the supervisor PID if one is alive
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null) && [ -n "$pid" ] || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "private_docs.sh start-daemon" || return 1
    echo "$pid"
}

no_daemon() {
    ! daemon_pid >/dev/null
}

server_pid() {
    pgrep -f "$PATTERN" | head -n 1
}

docs_up() {
    # The server listens on the Tailscale address only, so it is probed there. While the
    # VPN is down it idles on purpose ("waiting"/"offline"); that counts as healthy as long
    # as the state file keeps being rewritten (every 5-30 seconds).
    local state addr age
    state=$(cat "$STATE_FILE" 2>/dev/null) || return 1
    case "$state" in
        waiting|offline\ *)
            age=$(( $(date +%s) - $(stat -c %Y "$STATE_FILE" 2>/dev/null || echo 0) ))
            [ "$age" -lt 90 ]
            return
            ;;
        listening\ *) addr=${state#listening } ;;
        *) return 1 ;;
    esac
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://$addr/healthz")" = "200" ]
}

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

kill_strays() {
    # TERM every server process, escalating to KILL after 5 seconds; fails if none matched
    local i
    pkill -f "$PATTERN" || return 1
    for i in 1 2 3 4 5; do
        pgrep -f "$PATTERN" >/dev/null || return 0
        sleep 1
    done
    pkill -9 -f "$PATTERN"
    sleep 1
}

# ---------------------------------------------------------
# Supervisor (start-daemon)
# ---------------------------------------------------------
CHILD="" STARTED=0 DELAY=0 NEXT=0 FAILED=0

child_alive() {
    # True while PID is a live (non-zombie) child of this supervisor
    local stat
    stat=$(cat "/proc/$1/stat" 2>/dev/null) || return 1
    set -- ${stat##*) }
    [ "$1" != "Z" ] && [ "$2" = "$$" ]
}

spawn() {
    rm -f "$STATE_FILE"
    # 9>&- keeps the supervisor lock out of the child
    python3 -u "$SERVER" </dev/null >> "$LOG" 2>&1 9>&- &
    CHILD=$!
    STARTED=$SECONDS
    FAILED=0
    log "[START] private docs server (pid $CHILD)"
}

stop_child() {
    local pid=$CHILD i
    CHILD=""
    [ -n "$pid" ] || return 0
    if child_alive "$pid"; then
        kill "$pid" 2>/dev/null
        for i in 1 2 3 4 5; do
            child_alive "$pid" || break
            sleep 1
        done
        child_alive "$pid" && kill -9 "$pid" 2>/dev/null
    fi
    wait "$pid" 2>/dev/null
    rm -f "$STATE_FILE"
}

back_off() {
    # back_off SECONDS_UP: dying within 5 minutes of starting waits 10s, 20s, 40s ... up to 5 minutes
    if [ "$1" -lt 300 ]; then
        DELAY=$((DELAY ? DELAY * 2 : CHECK_INTERVAL))
        [ "$DELAY" -gt 300 ] && DELAY=300
    else
        DELAY=0
    fi
    NEXT=$((SECONDS + DELAY))
}

supervise() {
    local up rc
    if [ -n "$CHILD" ]; then
        up=$((SECONDS - STARTED))
        if child_alive "$CHILD"; then
            # Active health check after a 30-second grace period
            [ "$up" -ge 30 ] || return
            if docs_up; then
                FAILED=0
                [ "$up" -ge 300 ] && DELAY=0
                return
            fi
            FAILED=$((FAILED + 1))
            log "[WARN] health check failed (up ${up}s, failure $FAILED/3)"
            [ "$FAILED" -ge 3 ] || return
            log "[HUNG DETECTED] server is unresponsive (pid $CHILD); terminating"
            stop_child
            back_off 0
            return
        fi
        wait "$CHILD" 2>/dev/null
        rc=$?
        CHILD=""
        rm -f "$STATE_FILE"
        case "$rc" in
            3)
                # The server exits with 3 when the Tailscale address changed, to be rebound at once
                DELAY=0
                NEXT=$SECONDS
                log "[REBIND] Tailscale address changed; restarting now"
                ;;
            2)
                DELAY=300
                NEXT=$((SECONDS + DELAY))
                log "[REFUSED] server refused its bind address (code 2); retrying in ${DELAY}s"
                ;;
            *)
                back_off "$up"
                log "[CRASH DETECTED] server exited (code $rc, up ${up}s); restarting in ${DELAY}s"
                ;;
        esac
    fi
    [ "$SECONDS" -ge "$NEXT" ] && spawn
}

rotate_log() {
    # copytruncate, so the server's O_APPEND descriptor keeps working
    local size
    size=$(stat -c %s "$LOG" 2>/dev/null) || return 0
    [ "$size" -gt "$LOG_MAX_BYTES" ] || return 0
    cp "$LOG" "$LOG.1" && : > "$LOG"
    log "[LOG] Rotated $LOG ($size bytes)"
}

start_daemon() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        echo "[INFO] Private docs supervisor already running (PID $(daemon_pid))."
        exit 0
    fi
    # Write-then-rename so the launcher never reads a half-written PID file
    echo "$$" > "$PID_FILE.tmp" && mv -f "$PID_FILE.tmp" "$PID_FILE"
    rm -f "$RESTART_FLAG"
    log "[DAEMON] Supervisor started (pid $$)"

    trap 'log "[DAEMON] Supervisor stopping"; stop_child; exit 0' TERM INT HUP
    trap 'rm -f "$PID_FILE"' EXIT

    # This supervisor owns the server: clear out copies started any other way
    kill_strays && log "Stopped an unsupervised private docs server"

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
running() {
    daemon_pid >/dev/null && [ -n "$(server_pid)" ] && [ -e "$STATE_FILE" ]
}

status() {
    local pid state addr code count
    echo "=== Private Docs (Tailscale only) ==="
    if pid=$(daemon_pid); then
        echo "Supervisor: [RUNNING] (PID $pid)"
    else
        echo "Supervisor: [STOPPED]"
    fi

    pid=$(server_pid)
    state=$(cat "$STATE_FILE" 2>/dev/null)
    if [ -z "$pid" ]; then
        echo "Server:     [STOPPED]"
    else
        case "$state" in
            listening\ *)
                addr=${state#listening }
                code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://$addr/healthz")
                echo "Server:     [RUNNING] (PID $pid) - http://$addr/ (HTTP $code)"
                ;;
            waiting)
                echo "Server:     [WAITING] (PID $pid) - no Tailscale address yet; is the VPN on?"
                ;;
            offline\ *)
                echo "Server:     [OFFLINE] (PID $pid) - bound to ${state#offline }, but Tailscale is down"
                ;;
            *)
                echo "Server:     [STARTING] (PID $pid)"
                ;;
        esac
    fi

    count=$(grep -cvE '^[[:space:]]*(#|$)' "$LIST_FILE" 2>/dev/null)
    echo "Documents:  ${count:-0} listed in $LIST_FILE"
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
        echo "[START] Asking Termux to launch the private docs supervisor outside this proot session..."
        request_daemon
        if wait_until 60 running; then
            echo "[OK] Private docs supervisor is up."
        else
            echo "[WARN] Not up after 60s. The launch job waits for a network connection;"
            echo "       you can also run it from a Termux (non-proot) shell: $LAUNCHER"
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
        wait_until 15 no_daemon || echo "[WARN] Supervisor still running after 15s."
    fi
    rm -f "$RESTART_FLAG"
    kill_strays && echo "Private docs server stopped."
    rm -f "$STATE_FILE"
    echo "[INFO] Auto-start disabled until '$0 start'."
}

server_restarted() {
    local pid
    pid=$(server_pid)
    [ -n "$pid" ] && [ "$pid" != "$1" ] && [ -e "$STATE_FILE" ]
}

restart() {
    local pid old
    if ! pid=$(daemon_pid); then
        start
        return
    fi
    old=$(server_pid)
    echo "[RESTART] Asking supervisor (PID $pid) to restart the private docs server..."
    : > "$RESTART_FLAG"
    if wait_until 40 server_restarted "$old"; then
        echo "[OK] Server restarted."
    else
        rm -f "$RESTART_FLAG"
        echo "[WARN] Server not back after 40s; see $LOG"
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
