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
# Runs on the Termux side because notifications go through the Termux:API app. Readings
# come from sysfs; the directory cannot be listed under SELinux but the individual files
# are readable.
#
#   battery-watch.sh         what job 4247 (every 15 minutes) and the boot script run:
#                            start the loop if it is not running, then take a reading
#   battery-watch.sh loop    take a reading every 5 minutes, forever (one instance)
#   battery-watch.sh check   take one reading and act on it
#   battery-watch.sh stop    stop the loop (job 4247 starts it again)
#
# Why a loop: on battery at night Android's Doze held job 4247 back for up to 5 h 28 min
# (06:35 to 12:03 on 2026-09-28), and the 40% switch-on never ran; the battery was at 25%
# by then. The supervisors in the proot, long-running loops like this one, never paused
# for even 20 seconds on the same nights (their heartbeat check writes a downtime entry
# when it does, and there is none), so the reading moved into a loop and the job only
# restarts the loop if it has died.
PREFIX=/data/data/com.termux/files/usr
ROOTFS=$PREFIX/var/lib/proot-distro/containers/ubuntu/rootfs
SYS=/sys/class/power_supply/battery
LOG=$ROOTFS/root/logs/battery_watch.log
STATE=$ROOTFS/root/.battery_watch.state
LOG_MAX=524288
INTERVAL=300 # seconds between readings in the loop
HIGH=80      # switch the charger off (or ask to unplug) at or above this while charging
PLUG_ON=40   # switch the charger on at or below this while on battery
LOW=30       # ask to plug in at or below this while on battery: the plug has not helped
NOTIFY_ID=battery
# The plug: set up only once the Tapo account is on the phone (see /root/tapo_plug.py)
PLUG_TOOL=/root/tapo_plug.py
PLUG_CREDENTIALS=$ROOTFS/root/.config/tapo/credentials
PLUG_STATE=$ROOTFS/root/.battery_watch.plug   # failed switches in a row; absent when fine
PLUG_NOTIFY_ID=battery-plug
PLUG_HOST=$ROOTFS/root/.config/tapo/host      # the plug's saved LAN address
LOCK=$ROOTFS/root/.battery_watch.lock
LOOP_PID=$ROOTFS/root/.battery_watch.pid

read_node() { cat "$SYS/$1" 2>/dev/null; }

# How long the battery lasts at the fuel gauge's averaged current, as a sentence, or
# nothing when charging or when the gauge gives no usable numbers. Only an estimate:
# the drain on this phone ranges from 4%/h idle to 25%/h during a build (2026-09-29 log).
eta_text() {
    cc=$(read_node charge_counter)
    ca=$(read_node current_avg)
    case "$cc" in ''|*[!0-9]*) return 0 ;; esac
    case "$ca" in -[0-9]*) ;; *) return 0 ;; esac
    awk "BEGIN { h = ($cc / 1000) / (0 - $ca)
        if (h <= 0 || h > 200) exit
        if (h < 3) printf \"지금 쓰는 속도라면 약 %.1f시간 뒤 방전됩니다.\", h
        else printf \"지금 쓰는 속도라면 약 %.0f시간 뒤 방전됩니다.\", h }"
}
stamp() { TZ=KST-9 date '+%Y-%m-%d %H:%M:%S %Z'; }

loop_running() {
    pid=$(cat "$LOOP_PID" 2>/dev/null)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && grep -q 'battery-watch' "/proc/$pid/cmdline" 2>/dev/null
}

case "${1:-}" in
    loop)
        loop_running && exit 0
        # Two starters at once both get here; the last one to write the PID file stays
        echo $$ > "$LOOP_PID"
        sleep 1
        [ "$(cat "$LOOP_PID" 2>/dev/null)" = "$$" ] || exit 0
        while :; do
            # A reading that hangs (proot, the plug) must not stop every later one
            timeout 600 "$0" check
            sleep "$INTERVAL"
        done
        ;;
    stop)
        pid=$(cat "$LOOP_PID" 2>/dev/null)
        [ -n "$pid" ] && kill "$pid" 2>/dev/null
        rm -f "$LOOP_PID"
        exit 0
        ;;
    check) ;;
    *)
        loop_running || setsid nohup "$0" loop </dev/null >/dev/null 2>&1 &
        ;;
esac

# One run at a time: the job has been seen to start twice in the same second, the loop
# and the job can meet, and two runs switching the plug at once would each log a result
# for the other. A lock older than ten minutes belongs to a run that died.
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

# Tell the owner when the plug cannot be switched: which of the three failures it is,
# what to do first, and what happens meanwhile. The three seen so far:
#   refused (403)  the plug answers but has lost its third-party authorisation; the app's
#                  Third-Party Compatibility toggle restores it (2026-09-28, 09-29 twice)
#   unreachable    nothing answers at the saved address and discovery finds nothing, while
#                  the app still works through the cloud (2026-09-29 21:10); unplugging
#                  and replugging the plug brought it back, refusing (403) at first
#   no reply       a timeout: often one of the plug's lost packets
# A refusal is certain at once; the other two count from the third miss in a row.
# --alert-once: later updates of the same notification stay quiet.
plug_alert() {
    fails=$(cat "$PLUG_STATE" 2>/dev/null)
    case "$fails" in ''|*[!0-9]*) fails=0 ;; esac
    fails=$((fails + 1))
    echo "$fails" > "$PLUG_STATE"
    case "$want" in
        off) effect="충전기가 켜진 채 100%까지 찹니다."; by_hand="끄세요"
             plug_why="플러그를 끄지 못했습니다" ;;
        *) effect="충전기가 꺼져 있습니다. $(eta_text)"; by_hand="켜세요"
           plug_why="플러그를 켜지 못했습니다" ;;
    esac
    host=$(cat "$PLUG_HOST" 2>/dev/null)
    case "$1" in
        *"refused local control"*)
            plug_why="$plug_why(플러그가 거부)"
            title="🔌 플러그가 폰의 제어를 거부합니다 ($pct%)"
            text="타사 호환성 허가가 풀렸습니다. ① 급하면 Tapo 앱에서 플러그를 직접 $by_hand. ② Tapo 앱 → 나 → 타사 서비스 → 타사 호환성을 끄고 10초 뒤 다시 켜세요. 지금은 $effect"
            ;;
        *"Cannot connect"*|*"No route"*|*_ConnectionError*)
            plug_why="$plug_why(플러그가 네트워크에서 안 보임)"
            [ "$fails" -ge 3 ] || return 0
            title="🔌 폰에서 플러그가 보이지 않습니다 ($pct%, ${fails}번 연속)"
            text="앱은 인터넷을 거치므로 동작할 수 있습니다. ① 급하면 Tapo 앱에서 플러그를 직접 $by_hand. ② 앱의 기기 정보에서 IP가 ${host:-?}인지 확인하세요. 다르면 알려 주세요. ③ 같으면 플러그를 뽑았다가 다시 꽂으세요. 그 뒤 '거부' 알림이 오면 타사 호환성을 껐다 켜세요. 지금은 $effect"
            ;;
        *)
            plug_why="$plug_why(플러그 응답 없음)"
            [ "$fails" -ge 3 ] || return 0
            title="🔌 플러그가 응답하지 않습니다 ($pct%, ${fails}번 연속)"
            text="대답이 중간에 끊기고 있습니다. ① 급하면 Tapo 앱에서 플러그를 직접 $by_hand. ② 계속되면 플러그를 뽑았다가 다시 꽂으세요. 지금은 $effect"
            ;;
    esac
    termux-notification --id "$PLUG_NOTIFY_ID" --priority high --alert-once \
        --title "$title" --content "$text" >/dev/null 2>&1
}

plug_recovered() {
    [ -e "$PLUG_STATE" ] || return 0
    rm -f "$PLUG_STATE"
    termux-notification-remove "$PLUG_NOTIFY_ID" >/dev/null 2>&1
    echo "$(stamp) plug answers again" >> "$LOG"
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
plug_why=
case "$status" in
    Charging|Full) [ "$pct" -ge "$HIGH" ] && want=off ;;
    *) [ "$pct" -le "$PLUG_ON" ] && want=on ;;
esac
if [ -r "$PLUG_CREDENTIALS" ] && [ -x "$ROOTFS$PLUG_TOOL" ]; then
    if [ -n "$want" ]; then
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
            plug_recovered
        else
            echo "$(stamp) plug $want FAILED: $reply, phone still $now after ${waited}s" >> "$LOG"
            plug_alert "$reply"
        fi
    elif [ -e "$PLUG_STATE" ]; then
        # Nothing to switch, but the last switch failed: ask the plug whether it answers
        # now, so a fixed setting clears the alert without waiting for the next switch
        reply=$("$PREFIX/bin/proot-distro" login ubuntu -- "$PLUG_TOOL" status 2>&1 | tail -n 1)
        case "$reply" in on|off) plug_recovered ;; esac
    fi
fi

# Hysteresis: come back to "normal" only after moving 5 points away from the threshold,
# so a battery sitting at exactly 80% does not send an alert at every reading.
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
[ -r "$PLUG_CREDENTIALS" ] && plug_note="${plug_why:-스마트 플러그로 바꾸지 못했습니다}. "

[ "$state" = "$prev" ] && exit 0
echo "$state" > "$STATE"

case "$state" in
    high)
        termux-notification --id "$NOTIFY_ID" --priority high \
            --title "🔌 충전기를 빼세요 ($pct%)" \
            --content "${plug_note}만충 상태로 오래 두면 배터리가 부풀고 수명이 줄어듭니다. Tapo 앱에서 플러그를 끄거나 충전기를 빼세요." >/dev/null 2>&1
        ;;
    low)
        termux-notification --id "$NOTIFY_ID" --priority high \
            --title "🔋 충전기를 꽂으세요 ($pct%)" \
            --content "$LOW% 아래입니다. ${plug_note}$(eta_text) 방전되면 서버가 멈춥니다. 급하면 Tapo 앱에서 플러그를 켜거나 충전기를 직접 꽂으세요." >/dev/null 2>&1
        vibrate 3
        ;;
    normal)
        termux-notification-remove "$NOTIFY_ID" >/dev/null 2>&1
        ;;
esac
