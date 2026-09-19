#!/usr/bin/env bash
# ==============================================================================
# Service Manager & Daemon Supervisor for Galaxy Note FE (Ubuntu PRoot)
# Manages Python Blog/Dashboard & ngrok Tunnel with auto-restart capability
#
# The supervisor (start-daemon) is launched from the Termux side by
# /root/termux/ensure-daemon.sh. proot-distro runs proot with --kill-on-exit,
# so anything started from an interactive proot login dies when that login
# ends; `start` therefore asks Termux to run the launcher instead.
# ==============================================================================

NGROK_DOMAIN="https://daringly-marrow-penny.ngrok-free.dev"
LOG_DIR="/root"
PID_FILE="/root/.start_services.pid"
LOCK_FILE="/root/.start_services.lock"
DISABLED_FLAG="/root/.services_disabled"
RESTART_FLAG="/root/.restart_requested"
DOWNTIME_LOG="/root/downtime.log"
DOWNTIME_START_FILE="/root/.downtime_start"
HEARTBEAT_FILE="/root/.service_heartbeat"
LAST_DOWNTIME_FILE="/root/.last_downtime"
LOG_MAX_BYTES=$((10 * 1024 * 1024))
CHECK_INTERVAL=10

TERMUX_BIN="/data/data/com.termux/files/usr/bin"
# /root/termux/ensure-daemon.sh as seen from the Termux side
LAUNCHER="/data/data/com.termux/files/usr/var/lib/proot-distro/containers/ubuntu/rootfs/root/termux/ensure-daemon.sh"
LAUNCH_JOB_ID=4242

BLOG_PATTERN='^python3 (-u )?/root/serve_blog\.py'
NGROK_PATTERN='^/usr/local/bin/ngrok http '

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_DIR/daemon.log"
}

record_downtime_start() {
    local reason="${1:-unknown}"
    local now=${2:-$(date +%s)}
    local datestr=$(date -d "@$now" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S %Z')
    # Record only if not already active to preserve original outage timestamp
    if [ ! -f "$DOWNTIME_START_FILE" ]; then
        echo "${now}|${reason}|${datestr}" > "$DOWNTIME_START_FILE"
        log "[DOWNTIME_START] Service outage started (reason: ${reason}, at ${datestr})"
    fi
}

check_and_record_recovery() {
    local now=$(date +%s)
    local end_date=$(date '+%Y-%m-%d %H:%M:%S %Z')
    local start_ts reason start_date duration msg

    if [ -f "$DOWNTIME_START_FILE" ]; then
        IFS='|' read -r start_ts reason start_date < "$DOWNTIME_START_FILE"
        rm -f "$DOWNTIME_START_FILE"
        if [ -n "$start_ts" ] && [ "$now" -ge "$start_ts" ]; then
            duration=$((now - start_ts))
            msg="[DOWNTIME] Service was unavailable for ${duration}s (${reason}, from ${start_date} to ${end_date})"
            echo "[$end_date] $msg" >> "$DOWNTIME_LOG"
            log "$msg"
            echo "${duration}|${reason}|${start_date}|${end_date}" > "$LAST_DOWNTIME_FILE"
        fi
    elif [ -f "$HEARTBEAT_FILE" ]; then
        start_ts=$(cat "$HEARTBEAT_FILE" 2>/dev/null)
        if [ -n "$start_ts" ] && [ "$((now - start_ts))" -ge 20 ]; then
            duration=$((now - start_ts))
            start_date=$(date -d "@$start_ts" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || echo "timestamp $start_ts")
            msg="[DOWNTIME] Service was unavailable for ${duration}s (unexpected_shutdown_or_reboot, from ${start_date} to ${end_date})"
            echo "[$end_date] $msg" >> "$DOWNTIME_LOG"
            log "$msg"
            echo "${duration}|unexpected_shutdown_or_reboot|${start_date}|${end_date}" > "$LAST_DOWNTIME_FILE"
        fi
    fi

    echo "$now" > "$HEARTBEAT_FILE"
}

daemon_pid() {
    # Prints the supervisor PID if one is alive
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null) && [ -n "$pid" ] || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "start_services.sh start-daemon" || return 1
    echo "$pid"
}

no_daemon() {
    ! daemon_pid >/dev/null
}

blog_up() {
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://localhost:8080/)" = "200" ]
}

ngrok_up() {
    curl -s --max-time 2 http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -q "$NGROK_DOMAIN"
}

network_ready() {
    timeout 3 getent hosts connect.ngrok-agent.com >/dev/null 2>&1
}

services_up() {
    daemon_pid >/dev/null && blog_up && ngrok_up
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

# ---------------------------------------------------------
# Supervisor (start-daemon)
# ---------------------------------------------------------
declare -A CHILD STARTED DELAY NEXT FAILED_HEALTH

child_alive() {
    # True while PID is a live (non-zombie) child of this supervisor
    local stat
    stat=$(cat "/proc/$1/stat" 2>/dev/null) || return 1
    set -- ${stat##*) }
    [ "$1" != "Z" ] && [ "$2" = "$$" ]
}

spawn() {
    # 9>&- keeps the supervisor lock out of the children
    case "$1" in
        blog)
            python3 -u /root/serve_blog.py </dev/null >> "$LOG_DIR/blog_server.log" 2>&1 9>&- &
            ;;
        ngrok)
            if ! network_ready; then
                log "[WAIT] Network not ready for ngrok; delaying spawn by ${CHECK_INTERVAL}s"
                NEXT[ngrok]=$((SECONDS + CHECK_INTERVAL))
                return
            fi
            /usr/local/bin/ngrok http 8080 --url "$NGROK_DOMAIN" --pooling-enabled --log stdout \
                </dev/null >> "$LOG_DIR/ngrok.log" 2>&1 9>&- &
            ;;
    esac
    CHILD[$1]=$!
    STARTED[$1]=$SECONDS
    FAILED_HEALTH[$1]=0
    log "[START] $1 (pid $!)"
}

supervise() {
    local name="$1" pid="${CHILD[$1]}" rc up delay
    if [ -n "$pid" ]; then
        up=$((SECONDS - ${STARTED[$name]:-0}))
        if child_alive "$pid"; then
            # Active health check after grace period (30s)
            if [ "$up" -ge 30 ]; then
                local healthy=0
                case "$name" in
                    blog) blog_up && healthy=1 ;;
                    ngrok) ngrok_up && healthy=1 ;;
                    *) healthy=1 ;;
                esac

                if [ "$healthy" -eq 1 ]; then
                    FAILED_HEALTH[$name]=0
                    # A service that stayed up and healthy for 5 minutes gets its backoff reset
                    [ "$up" -ge 300 ] && DELAY[$name]=0
                else
                    FAILED_HEALTH[$name]=$(( ${FAILED_HEALTH[$name]:-0} + 1 ))
                    log "[WARN] $name failed health check ($up seconds up, failure ${FAILED_HEALTH[$name]}/3)"
                    if [ "${FAILED_HEALTH[$name]}" -ge 3 ]; then
                        record_downtime_start "hung_${name}"
                        log "[HUNG DETECTED] $name is unresponsive (pid $pid, up ${up}s); terminating..."
                        kill "$pid" 2>/dev/null
                        sleep 2
                        child_alive "$pid" && kill -9 "$pid" 2>/dev/null
                        wait "$pid" 2>/dev/null
                        CHILD[$name]=""
                        FAILED_HEALTH[$name]=0
                        delay=${DELAY[$name]:-0}
                        delay=$((delay ? delay * 2 : CHECK_INTERVAL))
                        [ "$delay" -gt 300 ] && delay=300
                        DELAY[$name]=$delay
                        NEXT[$name]=$((SECONDS + delay))
                        return
                    fi
                fi
            fi
            return
        fi
        record_downtime_start "crash_${name}"
        wait "$pid" 2>/dev/null
        rc=$?
        CHILD[$name]=""
        FAILED_HEALTH[$name]=0
        delay=${DELAY[$name]:-0}
        if [ "$up" -lt 300 ]; then
            # Crashing within 5 minutes of starting: back off 10s, 20s, 40s ... up to 5 minutes
            delay=$((delay ? delay * 2 : CHECK_INTERVAL))
            [ "$delay" -gt 300 ] && delay=300
        else
            delay=0
        fi
        DELAY[$name]=$delay
        NEXT[$name]=$((SECONDS + delay))
        log "[CRASH DETECTED] $name exited (code $rc, up ${up}s); restarting in ${delay}s"
    fi
    [ "$SECONDS" -ge "${NEXT[$name]:-0}" ] && spawn "$name"
}

stop_children() {
    local name pid alive i pids=()
    for name in "${!CHILD[@]}"; do
        pid="${CHILD[$name]}"
        CHILD[$name]=""
        # Signal only live children: a reaped PID may already belong to another process
        [ -n "$pid" ] && child_alive "$pid" && pids+=("$pid")
    done
    [ ${#pids[@]} -gt 0 ] || return 0
    kill "${pids[@]}" 2>/dev/null
    for i in 1 2 3 4 5; do
        alive=""
        for pid in "${pids[@]}"; do
            child_alive "$pid" && alive=1
        done
        [ -z "$alive" ] && break
        sleep 1
    done
    for pid in "${pids[@]}"; do
        child_alive "$pid" && kill -9 "$pid" 2>/dev/null
    done
    wait "${pids[@]}" 2>/dev/null
}

rotate_log() {
    # copytruncate, so writers holding O_APPEND descriptors keep working
    local size
    size=$(stat -c %s "$1" 2>/dev/null) || return 0
    [ "$size" -gt "$LOG_MAX_BYTES" ] || return 0
    cp "$1" "$1.1" && : > "$1"
    log "[LOG] Rotated $1 ($size bytes)"
}

kill_strays() {
    # TERM every process matching $1, escalating to KILL after 5 seconds; fails if none matched
    local i
    pkill -f "$1" || return 1
    for i in 1 2 3 4 5; do
        pgrep -f "$1" >/dev/null || return 0
        sleep 1
    done
    pkill -9 -f "$1"
    sleep 1
}

start_daemon() {
    local name
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        echo "[INFO] Supervisor already running (PID $(daemon_pid))."
        exit 0
    fi
    # Write-then-rename so the launcher never reads a half-written PID file
    echo "$$" > "$PID_FILE.tmp" && mv -f "$PID_FILE.tmp" "$PID_FILE"
    rm -f "$RESTART_FLAG"
    log "[DAEMON] Supervisor started (pid $$)"

    trap 'RESTART_REQUESTED=1' USR1
    trap 'record_downtime_start "shutdown/reboot"; log "[DAEMON] Supervisor stopping"; stop_children; exit 0' TERM INT HUP
    trap 'rm -f "$PID_FILE"' EXIT

    # This supervisor owns the services: clear out copies started any other way
    kill_strays "$BLOG_PATTERN" && log "Stopped an unsupervised blog server"
    kill_strays "$NGROK_PATTERN" && log "Stopped an unsupervised ngrok"

    # If the system was rebooted abruptly (without graceful trap), use the last heartbeat as outage start
    if [ ! -f "$DOWNTIME_START_FILE" ] && [ -f "$HEARTBEAT_FILE" ]; then
        last_hb=$(cat "$HEARTBEAT_FILE" 2>/dev/null)
        now_ts=$(date +%s)
        if [ -n "$last_hb" ] && [ "$((now_ts - last_hb))" -ge 20 ]; then
            record_downtime_start "unexpected_shutdown_or_reboot" "$last_hb"
        fi
    fi

    while true; do
        if [ -n "$RESTART_REQUESTED" ] || [ -e "$RESTART_FLAG" ]; then
            RESTART_REQUESTED=""
            rm -f "$RESTART_FLAG"
            record_downtime_start "restart"
            log "[RESTART] Restart requested"
            stop_children
            for name in blog ngrok; do
                DELAY[$name]=0
                NEXT[$name]=0
                FAILED_HEALTH[$name]=0
            done
        fi

        for name in blog ngrok; do
            supervise "$name"
        done

        # If both services are up, record recovery and maintain heartbeat; otherwise track downtime
        if blog_up && ngrok_up; then
            check_and_record_recovery
        else
            record_downtime_start "services_offline"
        fi

        for name in daemon.log blog_server.log ngrok.log; do
            rotate_log "$LOG_DIR/$name"
        done

        # Sleeping in the background lets the USR1/TERM traps run immediately
        sleep "$CHECK_INTERVAL" 9>&- &
        wait $!
    done
}

# ---------------------------------------------------------
# Commands
# ---------------------------------------------------------
status() {
    local pid tty code
    echo "=== Galaxy Note FE Service Status ==="
    if pid=$(daemon_pid); then
        tty=$(ps -o tty= -p "$pid" | tr -d ' ')
        if [ "$tty" = "?" ]; then
            echo "Supervisor:   [RUNNING] (PID $pid) - detached"
        else
            echo "Supervisor:   [RUNNING] (PID $pid) - WARNING: attached to $tty"
        fi
    else
        echo "Supervisor:   [STOPPED]"
    fi

    pid=$(pgrep -f "$BLOG_PATTERN" | head -n 1)
    if [ -n "$pid" ]; then
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://localhost:8080/)
        echo "Blog Server:  [RUNNING] (PID $pid) - port 8080, HTTP $code"
    else
        echo "Blog Server:  [STOPPED]"
    fi

    pid=$(pgrep -f "$NGROK_PATTERN" | head -n 1)
    if [ -n "$pid" ]; then
        if ngrok_up; then
            echo "ngrok Tunnel: [RUNNING] (PID $pid) - $NGROK_DOMAIN (online)"
        else
            echo "ngrok Tunnel: [RUNNING] (PID $pid) - WARNING: tunnel offline/unresponsive"
        fi
    else
        echo "ngrok Tunnel: [STOPPED]"
    fi

    if [ -e "$DISABLED_FLAG" ]; then
        echo "Auto-start:   [DISABLED] - resume with: $0 start"
    else
        echo "Auto-start:   [ENABLED]"
    fi

    if [ -f "$LAST_DOWNTIME_FILE" ]; then
        IFS='|' read -r dt_sec dt_reason dt_start dt_end < "$LAST_DOWNTIME_FILE"
        echo "Last Downtime: ${dt_sec}s (${dt_reason}, ${dt_start} ~ ${dt_end})"
    fi
    if [ -f "$DOWNTIME_START_FILE" ]; then
        IFS='|' read -r dt_ts dt_reason dt_start < "$DOWNTIME_START_FILE"
        local cur=$(date +%s)
        echo "Downtime:      [IN PROGRESS] (${dt_reason}, ongoing for $((cur - dt_ts))s since ${dt_start})"
    fi
}

start() {
    local pid
    rm -f "$DISABLED_FLAG"
    if pid=$(daemon_pid); then
        echo "[INFO] Supervisor already running (PID $pid)."
    else
        echo "[START] Asking Termux to launch the supervisor outside this proot session..."
        request_daemon
        if wait_until 60 services_up; then
            echo "[OK] Supervisor and blog server are up."
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
    record_downtime_start "manual_stop"
    if pid=$(daemon_pid); then
        echo "[STOP] Stopping supervisor (PID $pid)..."
        kill "$pid"
        wait_until 15 no_daemon || echo "[WARN] Supervisor still running after 15s."
    fi
    rm -f "$RESTART_FLAG"
    pkill -f "$BLOG_PATTERN" && echo "Blog server stopped."
    pkill -f "$NGROK_PATTERN" && echo "ngrok stopped."
    echo "[INFO] Auto-start disabled until '$0 start'."
}

blog_restarted() {
    local pid
    pid=$(pgrep -f "$BLOG_PATTERN" | head -n 1)
    [ -n "$pid" ] && [ "$pid" != "$1" ] && blog_up
}

restart() {
    local pid old_blog
    if ! pid=$(daemon_pid); then
        start
        return
    fi
    old_blog=$(pgrep -f "$BLOG_PATTERN" | head -n 1)
    record_downtime_start "manual_restart"
    echo "[RESTART] Asking supervisor (PID $pid) to restart the blog server and ngrok..."
    # A flag file rather than a signal: processes started from the Termux app inherit a
    # mask with SIGUSR1 blocked, so the signal can sit undelivered forever. The supervisor
    # picks the flag up on its next pass, within CHECK_INTERVAL seconds.
    : > "$RESTART_FLAG"
    kill -USR1 "$pid" 2>/dev/null
    if wait_until 40 blog_restarted "$old_blog"; then
        echo "[OK] Services restarted."
    else
        rm -f "$RESTART_FLAG"
        echo "[WARN] Blog server not back after 40s; see $LOG_DIR/daemon.log and $LOG_DIR/blog_server.log"
    fi
    status
}

login_check() {
    # Called from /root/.bashrc on interactive proot logins
    if [ -e "$DISABLED_FLAG" ]; then
        echo "[blog] Services were stopped manually. Resume with: $0 start"
    elif no_daemon; then
        # Synchronous: a background request would die with this session if the user logs out at once
        echo "[blog] Supervisor is not running; asking Termux to launch it (check: $0 status)"
        request_daemon
    fi
}

downtime_history() {
    echo "=== Service Downtime History ($DOWNTIME_LOG) ==="
    if [ -f "$DOWNTIME_LOG" ]; then
        cat "$DOWNTIME_LOG"
    else
        echo "(No recorded downtime yet)"
    fi
    if [ -f "$DOWNTIME_START_FILE" ]; then
        IFS='|' read -r dt_ts dt_reason dt_start < "$DOWNTIME_START_FILE"
        local cur=$(date +%s)
        echo ""
        echo "[CURRENT] Service is currently down: $((cur - dt_ts))s (${dt_reason}, started ${dt_start})"
    fi
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
    downtime)
        downtime_history
        ;;
    login-check)
        login_check
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|downtime|start-daemon|login-check}"
        status
        ;;
esac
