#!/data/data/com.termux/files/usr/bin/sh
# Starts the tailnet-only private docs supervisor unless it is already running or disabled.
#
# Runs on the Termux side, outside proot, and is independent of ensure-daemon.sh (the
# public blog's launcher). Callers: ~/.termux/boot/start-server.sh, the
# termux-job-scheduler watchdog (job 4243), and `private_docs.sh start`, which schedules
# this script from inside proot (job 4244).
PREFIX=/data/data/com.termux/files/usr
ROOTFS=$PREFIX/var/lib/proot-distro/containers/ubuntu/rootfs
PID_FILE=$ROOTFS/root/.private_docs.pid
LOG=/data/data/com.termux/files/home/boot_services.log

[ -e "$ROOTFS/root/.private_docs_disabled" ] && exit 0

if [ -r "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$pid" ]; then
        case "$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)" in
            *"private_docs.sh start-daemon"*) exit 0 ;;
        esac
    fi
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] launching private docs supervisor" >> "$LOG"

# setsid: own session, no controlling terminal (see ensure-daemon.sh)
setsid nohup "$PREFIX/bin/proot-distro" login ubuntu -- /root/private_docs.sh start-daemon \
    </dev/null >>"$LOG" 2>&1 &
