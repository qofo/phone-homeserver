#!/data/data/com.termux/files/usr/bin/sh
# Starts the Ubuntu blog/ngrok supervisor unless it is already running or disabled.
#
# Runs on the Termux side, outside proot. Callers: ~/.termux/boot/start-server.sh,
# Termux ~/.bashrc, the termux-job-scheduler watchdog (job 4241), and
# `start_services.sh start`, which schedules this script from inside proot (job 4242).
PREFIX=/data/data/com.termux/files/usr
ROOTFS=$PREFIX/var/lib/proot-distro/containers/ubuntu/rootfs
PID_FILE=$ROOTFS/root/.start_services.pid
LOG=/data/data/com.termux/files/home/boot_services.log

[ -e "$ROOTFS/root/.services_disabled" ] && exit 0

if [ -r "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$pid" ]; then
        case "$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)" in
            *"start_services.sh start-daemon"*) exit 0 ;;
        esac
    fi
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] launching supervisor" >> "$LOG"

# setsid gives the supervisor its own session with no controlling terminal, so
# Ctrl+C or logout in whichever shell ran this cannot reach it or its children.
setsid nohup "$PREFIX/bin/proot-distro" login ubuntu -- /root/start_services.sh start-daemon \
    </dev/null >>"$LOG" 2>&1 &
