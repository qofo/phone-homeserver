#!/data/data/com.termux/files/usr/bin/sh
# Keeps the battery away from both extremes and records a log for power measurements.
#
# This phone is from 2017 and the battery is the expensive part of running it: left at
# 100% around the clock it swells and dies within a year or two. Android 9 has no charge
# limit, so the charger hangs off a Tapo P100 smart plug that this script switches: off at
# 80% while charging, on at 40% on battery (/root/tapo_plug.py, run inside the proot).
# Without the plug set up, or when switching it fails, it falls back to what it did
# before: a notification asking the owner to unplug at 80% or plug in at 30%.
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
HIGH=80      # switch the charger off (or ask to unplug) at or above this while charging
PLUG_ON=40   # switch the charger on at or below this while on battery
LOW=30       # ask to plug in at or below this while on battery: the plug has not helped
NOTIFY_ID=battery
# The plug: set up only once the Tapo account is on the phone (see /root/tapo_plug.py)
PLUG_TOOL=/root/tapo_plug.py
PLUG_CREDENTIALS=$ROOTFS/root/.config/tapo/credentials
LOCK=$ROOTFS/root/.battery_watch.lock

read_node() { cat "$SYS/$1" 2>/dev/null; }
stamp() { TZ=KST-9 date '+%Y-%m-%d %H:%M:%S %Z'; }

# One run at a time: the job has been seen to start twice in the same second, and two
# runs switching the plug at once would each log a result for the other. A lock older
# than ten minutes belongs to a run that died.
if ! mkdir "$LOCK" 2>/dev/null; then
    [ -n "$(find "$LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ] || exit 0
    rm -rf "$LOCK" && mkdir "$LOCK" 2>/dev/null || exit 0
fi
trap 'rm -rf "$LOCK"' EXIT

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
echo "$(stamp) pct=$pct status=$status temp=${temp:-?} mA=${mA:-?} mV=${mV:-?}" >> "$LOG"

# Rotate the log by hand; it is the only thing here that grows
size=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
[ "$size" -gt "$LOG_MAX" ] && mv -f "$LOG" "$LOG.1"

# Switch the charger with the plug when the battery reaches either end. The plug answers
# slowly and drops packets, so tapo_plug.py retries for up to a minute or two; then check
# that the phone really stopped or started charging, since that is what matters.
plug_ok=0
want=
case "$status" in
    Charging|Full) [ "$pct" -ge "$HIGH" ] && want=off ;;
    *) [ "$pct" -le "$PLUG_ON" ] && want=on ;;
esac
if [ -n "$want" ] && [ -r "$PLUG_CREDENTIALS" ] && [ -x "$ROOTFS$PLUG_TOOL" ]; then
    reply=$("$PREFIX/bin/proot-distro" login ubuntu -- "$PLUG_TOOL" "$want" 2>&1 | tail -n 1)
    waited=0
    now=$(read_node status)
    while [ "$waited" -lt 30 ]; do
        now=$(read_node status)
        case "$want:$now" in
            off:Discharging|"off:Not charging"|on:Charging|on:Full) plug_ok=1; break ;;
        esac
        sleep 3
        waited=$((waited + 3))
    done
    if [ "$plug_ok" = 1 ]; then
        # The phone's own status is the proof; the plug's reply is only a note
        echo "$(stamp) plug $want: phone now $now (plug said: $reply)" >> "$LOG"
    else
        echo "$(stamp) plug $want FAILED: $reply, phone still $now after ${waited}s" >> "$LOG"
    fi
fi

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

# The plug did its job, so there is nothing to ask the owner to do
[ "$plug_ok" = 1 ] && state=normal
# Say why the owner is being asked, when a plug is set up and did not manage it
plug_note=
[ -r "$PLUG_CREDENTIALS" ] && plug_note="스마트 플러그로 바꾸지 못했습니다. "

[ "$state" = "$prev" ] && exit 0
echo "$state" > "$STATE"

case "$state" in
    high)
        termux-notification --id "$NOTIFY_ID" --priority high \
            --title "🔌 충전기를 빼세요 ($pct%)" \
            --content "${plug_note}만충 상태로 오래 두면 배터리가 부풀고 수명이 줄어듭니다." >/dev/null 2>&1
        ;;
    low)
        termux-notification --id "$NOTIFY_ID" --priority high \
            --title "🔋 충전기를 꽂으세요 ($pct%)" \
            --content "$LOW% 아래입니다. ${plug_note}방전되면 서버가 멈춥니다." >/dev/null 2>&1
        vibrate 3
        ;;
    normal)
        termux-notification-remove "$NOTIFY_ID" >/dev/null 2>&1
        ;;
esac
