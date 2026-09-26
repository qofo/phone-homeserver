#!/data/data/com.termux/files/usr/bin/sh
# Keeps the battery away from both extremes and records a log for power measurements.
#
# This phone is from 2017 and the battery is the expensive part of running it: left at
# 100% around the clock it swells and dies within a year or two. Android 9 has no charge
# limit, so the only lever is a notification asking the owner to unplug or plug in.
#
# Runs on the Termux side (job 4247, every 15 minutes) because notifications go through
# the Termux:API app. Readings come from sysfs; the directory cannot be listed under
# SELinux but the individual files are readable.
PREFIX=/data/data/com.termux/files/usr
ROOTFS=$PREFIX/var/lib/proot-distro/containers/ubuntu/rootfs
SYS=/sys/class/power_supply/battery
LOG=$ROOTFS/root/logs/battery_watch.log
STATE=$ROOTFS/root/.battery_watch.state
LOG_MAX=524288
HIGH=80      # ask to unplug at or above this while charging
LOW=30       # ask to plug in at or below this while on battery
NOTIFY_ID=battery

read_node() { cat "$SYS/$1" 2>/dev/null; }

# The low alert is the one that matters: a flat battery takes the server down with it.
# Android's own notification buzz is easy to sleep through and Do Not Disturb silences
# it, so buzz explicitly as well. -f vibrates even in silent mode; three pulses tell
# the two alerts apart without looking at the screen.
vibrate() {
    left=$1
    while [ "$left" -gt 0 ]; do
        termux-vibrate -d 600 -f >/dev/null 2>&1
        left=$((left - 1))
        if [ "$left" -gt 0 ]; then sleep 1; fi
    done
}

pct=$(read_node capacity)
status=$(read_node status)
case "$pct" in ''|*[!0-9]*) exit 0 ;; esac   # no reading, nothing to do

temp=$(read_node temp)
mA=$(read_node current_now)
mV=$(read_node voltage_now)
[ -n "$temp" ] && temp=$(awk "BEGIN {printf \"%.1f\", $temp/10}")
[ -n "$mV" ] && mV=$((mV / 1000))
mkdir -p "${LOG%/*}"
echo "$(TZ=KST-9 date '+%Y-%m-%d %H:%M:%S %Z') pct=$pct status=$status temp=${temp:-?} mA=${mA:-?} mV=${mV:-?}" >> "$LOG"

# Rotate the log by hand; it is the only thing here that grows
size=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
[ "$size" -gt "$LOG_MAX" ] && mv -f "$LOG" "$LOG.1"

# Hysteresis: come back to "normal" only after moving 5 points away from the threshold,
# so a battery sitting at exactly 80% does not send an alert every 15 minutes.
prev=$(cat "$STATE" 2>/dev/null)
state=normal
case "$status" in
    Charging|Full)
        if [ "$pct" -ge "$HIGH" ]; then state=high
        elif [ "$prev" = high ] && [ "$pct" -gt $((HIGH - 5)) ]; then state=high
        fi
        ;;
    *)
        if [ "$pct" -le "$LOW" ]; then state=low
        elif [ "$prev" = low ] && [ "$pct" -lt $((LOW + 5)) ]; then state=low
        fi
        ;;
esac

[ "$state" = "$prev" ] && exit 0
echo "$state" > "$STATE"

case "$state" in
    high)
        termux-notification --id "$NOTIFY_ID" --priority high \
            --title "🔌 충전기를 빼세요 ($pct%)" \
            --content "만충 상태로 오래 두면 배터리가 부풀고 수명이 줄어듭니다." >/dev/null 2>&1
        ;;
    low)
        termux-notification --id "$NOTIFY_ID" --priority high \
            --title "🔋 충전기를 꽂으세요 ($pct%)" \
            --content "$LOW% 아래입니다. 방전되면 서버가 멈춥니다." >/dev/null 2>&1
        vibrate 3
        ;;
    normal)
        termux-notification-remove "$NOTIFY_ID" >/dev/null 2>&1
        ;;
esac
