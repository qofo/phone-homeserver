# 6. Operations — battery, heat, metrics and proof

<b>English</b> · [한국어](06-operations.ko.md)

[← 5. Private access](05-private-access.md) · Next: [7. Troubleshooting](07-troubleshooting.md)

---

A phone server has two consumables a rack server does not: a battery that degrades and
a case with no fan. Everything on this page exists to keep those two from ending the
experiment, and to produce numbers instead of impressions.

![proving it works, from outside the phone](images/term-verify.svg)

## 6.1 The battery is the part that wears out

Android 9 has no charge limit, so a phone left plugged in sits at 100 % around the
clock. On a 2017 battery that means swelling within a year or two — and a swollen
battery in a device you leave unattended is a real hazard, not a performance note.

The only lever available without root is a notification. `termux/battery-watch.sh`
runs every fifteen minutes on the Termux side (job 4247, because notifications go
through Termux:API) and reads sysfs directly:

```sh
SYS=/sys/class/power_supply/battery
HIGH=80      # ask to unplug at or above this, while charging
LOW=30       # ask to plug in at or below this, while on battery
```

Two implementation details that cost time to find:

- **The sysfs directory cannot be listed** under SELinux, but the individual files
  inside it are readable. Do not try to enumerate; read `capacity`, `status`, `temp`,
  `current_now`, `voltage_now` by name.
- **Add hysteresis.** A battery resting at exactly 80 % otherwise notifies every
  fifteen minutes forever. The state only returns to normal five points away from the
  threshold.
- **The low alert vibrates as well.** Android's own notification buzz is easy to
  sleep through and Do Not Disturb silences it, so the low branch also calls
  `termux-vibrate -d 600 -f` three times; `-f` vibrates even in silent mode. A flat
  battery takes the server down with it, while a full one only shortens its life, so
  only the low end is worth waking up for.

Each run appends a line, and the log is rotated by hand at 512 KB:

```
2026-09-20 21:15:02 KST pct=80 status=Charging temp=31.5 mA=-412 mV=4301
```

The alert as it arrives, next to Termux's wake lock and Tailscale's connection — the
three notifications that together mean the server is healthy:

![The Termux:API notification asking for the charger to be unplugged at 80%](images/shot-battery-alert.png)

That log is what makes power questions answerable: charge and discharge rate under
real load, and how warm the phone runs at each.

## 6.2 Heat

Fanless, in a case, on a charger, under load — the phone throttles. Three things help
more than anything clever:

- **Take the case off.** The back cover is the heatsink.
- **Keep the screen off and dim.** The display is the largest single power draw and a
  significant heat source.
- **Do not schedule heavy work at 100 % charge.** Charging is itself exothermic;
  building a site while fast-charging is the worst combination.

Watch `temp` in the battery log rather than a CPU sensor. Inside `proot` the thermal
zones are not reliably readable, and the battery's own thermistor is close enough for
the decision you are making, which is "is this too hot to keep doing".

## 6.3 The metrics endpoint

`serve_blog.py` exposes `/api/metrics` — the only data source for the dashboard:

```bash
curl -s http://127.0.0.1:8080/api/metrics | python3 -m json.tool | head -30
```

It returns CPU percentage, memory and swap, battery percentage and status,
temperature, uptime and load average. Two constraints shape how it is gathered:

- **`/proc` lies inside `proot`.** `/proc/stat`, `/proc/uptime` and `/proc/loadavg`
  return static or fabricated values. Uptime and load come from the `sysinfo(2)`
  syscall through `ctypes` instead, and CPU percentage is derived on the Termux side.
- **Battery data comes from Termux:API**, which means the metrics call depends on an
  Android app being alive. Treat a missing battery field as "unknown", never as zero.

![The live dashboard: per-core usage, memory, swap, battery and temperature](images/shot-dashboard.png)

The dashboard that consumes this is built only into the phone's copy of the site. A
public visitor's browser should not be calling into your phone
([`02-web-server.md`](02-web-server.md)).

## 6.4 Measuring downtime instead of guessing

Two different numbers, measured two different ways.

**Planned restarts** — run the prober, then restart, and read the gap:

```bash
./measure_downtime.py --once &        # polls every 0.5 s by default
./start_services.sh restart
# downtime: 11.6 s   → appended to downtime.log
```

Useful flags: `--local` to probe `127.0.0.1:8080` instead of the public address,
`--interval` to trade resolution for request count (the ngrok free plan counts
requests), `--once` to exit after one outage-and-recovery cycle.

**Unplanned outages** — each supervisor keeps a heartbeat file and compares it on
startup, so a gap is recorded with a cause even though nothing was watching:

```
Last Downtime: 168s (unexpected_shutdown_or_reboot, 2026-09-19 17:27:59 ~ 17:30:47 UTC)
```

Measure the public address, not the local port, when the question is "was the site
up". A restart that swaps the build in 0.3 s can still cost twelve seconds at the
tunnel, and only the outside measurement sees that.

## 6.5 Load testing without cooking the phone

A full specification with staged load, cooldowns and the client scripts is in
[`reference/STRESS_TEST_SPEC.md`](reference/STRESS_TEST_SPEC.md) (Korean). The shape
matters more than the numbers:

- **Generate load from a PC, not the phone.** A load generator on the device under
  test measures the load generator.
- **Drive it over Tailscale**, straight at `100.x.y.z:8080`, so you are measuring the
  phone rather than the ngrok edge and your uplink.
- **Ramp in stages with a cooldown between each**, and read `/api/metrics` at every
  stage. On a fanless device the interesting failure is thermal, and it only appears
  after several minutes at load.
- **Stop on temperature, not on errors.** Decide the ceiling before you start.

## 6.6 Running the test suites

```bash
python3 tests/test_serve_blog.py      # 35 tests
python3 tests/test_private_docs.py    # 47 tests
```

Both are black-box: they start their own server instance on their own port in a
temporary directory, so they are safe to run on the live phone at any time. Run them
after touching a server file, and before any `publish`.

To check the suites are testing anything, break a copy on purpose:

```bash
cp serve_blog.py /tmp/x.py     # delete the path check in the copy
# six tests must fail. If they all still pass, the tests are decorative.
```

## 6.7 Routine maintenance

**Stop a service properly.** Create the disable flag, or the launcher and the
fifteen-minute job will restart what you just stopped:

```bash
touch /root/.services_disabled        # blog + ngrok
touch /root/.private_docs_disabled    # docs viewer
touch /root/.code_server_disabled     # code-server
./start_services.sh stop
# ... maintenance ...
rm /root/.services_disabled && ./start_services.sh start
```

**Logs.** Everything logs to `/root/logs/`, which the supervisors create if it is
missing, and each supervisor rotates its own log (10 MB for the blog, 2 MB for the
private services, 512 KB for the battery watch). Nothing else grows unattended, but
`/root/blog_builds/` accumulates one directory per publish — prune it occasionally:

```bash
ls -1dt /root/blog_builds/* | tail -n +6 | xargs rm -rf
```

**Back up these four things.** Everything else is reproducible from this repository:

| What | Why |
|:---|:---|
| the blog source repository | your writing; it is in git, so push it |
| `~/.config/ngrok/ngrok.yml` | the token, and therefore your fixed address |
| `/root/.config/code-server/tls/ca.key` and `ca.crt` | losing the CA means re-trusting it on every device |
| `/root/private_docs.list` | your allow-list, which is not in the repository |

**A weekly minute.** Three status commands, one glance at the battery log, and the
publish state:

```bash
./start_services.sh status && ./private_docs.sh status && ./code_server.sh status
tail -3 /root/logs/battery_watch.log
./publish_blog.sh status
```

Next: when something is broken → [7. Troubleshooting](07-troubleshooting.md)
