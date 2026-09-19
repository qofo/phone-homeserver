#!/data/data/com.termux/files/usr/bin/sh
# Starts the tailnet-only code-server supervisor unless it is already running or disabled.
#
# Runs on the Termux side, outside proot, and is independent of the blog's and the docs
# viewer's launchers. Callers: ~/.termux/boot/start-server.sh, the termux-job-scheduler
# watchdog (job 4245), and `code_server.sh start`, which schedules this script from
# inside proot (job 4246).
PREFIX=/data/data/com.termux/files/usr
ROOTFS=$PREFIX/var/lib/proot-distro/containers/ubuntu/rootfs
PID_FILE=$ROOTFS/root/.code_server.pid
LOG=/data/data/com.termux/files/home/boot_services.log

[ -e "$ROOTFS/root/.code_server_disabled" ] && exit 0

if [ -r "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$pid" ]; then
        case "$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)" in
            *"code_server.sh start-daemon"*) exit 0 ;;
        esac
    fi
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] launching code-server supervisor" >> "$LOG"

# setsid: own session, no controlling terminal (see ensure-daemon.sh)
setsid nohup "$PREFIX/bin/proot-distro" login ubuntu -- /root/code_server.sh start-daemon \
    </dev/null >>"$LOG" 2>&1 &
