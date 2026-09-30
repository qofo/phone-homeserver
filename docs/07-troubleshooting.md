# 7. Troubleshooting — every failure this phone actually produced

<b>English</b> · [한국어](07-troubleshooting.ko.md)

[← 6. Operations](06-operations.md) · [README](../README.md)

---

Indexed by the symptom you will see, not by the subsystem at fault. Every entry here
happened on this device; none are hypothetical.

| Area | Jump to |
|:---|:---|
| installing things | [7.1](#71-installing-things) |
| processes that will not stay up | [7.2](#72-processes-that-will-not-stay-up) |
| the public address | [7.3](#73-the-public-address) |
| the private services | [7.4](#74-the-private-services) |
| the site and publishing | [7.5](#75-the-site-and-publishing) |
| the phone itself | [7.6](#76-the-phone-itself) |

## 7.1 Installing things

**`CANNOT LINK EXECUTABLE "node": cannot locate symbol ...`**
A version mismatch between the installed package and the libraries currently on the
device, not a broken package. Termux builds against Android's bionic libc, and its
repository assumes everything is current. Run `pkg update && pkg upgrade -y`, then try
again. Do this before installing anything large, not after.

**A binary you downloaded from a vendor hangs, or dies at the linker**
Android's linker has requirements a generic Linux `x86_64`-or-`aarch64` build does not
meet. `termux-elf-cleaner <file>` is worth exactly one attempt; if that does not fix
it, stop patching and run the binary inside `proot-distro` instead, where there is a
real glibc. See [`01-install.md`](01-install.md) §1.4.

**Every HTTPS call inside Ubuntu fails certificate verification**
The `proot-distro` rootfs is minimal and its CA bundle is missing or stale. The error
will blame the remote server; it is your trust store.

```bash
apt-get update && apt-get install --reinstall ca-certificates
```

**`termux-battery-status` (or any `termux-*` command) hangs forever and returns nothing**
Either Termux:API is not installed, or it came from a different store than Termux
itself. Android will not let apps with different signing keys communicate, and the
failure is silent. Install Termux, Termux:Boot and Termux:API all from F-Droid. Also
open each add-on once — an add-on that has never been launched is never granted its
permissions.

**`sysctl -w fs.inotify.max_user_watches=8192` succeeds, and changes nothing**
It should not have succeeded, and that is the clue. `proot-distro` bind-mounts an
ordinary file over that path:

```
$ grep inotify /proc/self/mountinfo
... /proc/sys/fs/inotify/max_user_watches rw,relatime - bind
    .../containers/ubuntu/sysdata/sysctl_inotify_max_user_watches rw,relatime
```

Reads return 4096, writes change that file, and the kernel never learns about either.
The same trick is used for `/proc/stat` and `/proc/uptime`. To find a real limit, add
watches until one fails rather than reading a number.

## 7.2 Processes that will not stay up

**Everything was running last night; this morning all services are `STOPPED`**
They were started inside a `proot` login session. `proot-distro` runs with
`--kill-on-exit` and takes the whole tracee tree down when that session ends. Start
supervisors only through the launchers in `termux/`, which use `setsid` from the Termux
side. [`04-always-on.md`](04-always-on.md) §4.3.

**The log is full of `[CRASH DETECTED]` and the service keeps bouncing**
The supervisor is sharing a terminal's process group, so a `Ctrl+C` or a closing SSH
session reaches its children. It restarts them, they die again. The fix is `setsid`;
the lesson is that a restart loop in the log is a symptom, not evidence of recovery.

**`status` says `RUNNING` but visitors get an error page**
The process exists and has stopped working. `pgrep` cannot see the difference. Add a
probe of the endpoint a visitor actually uses, require three consecutive failures
before acting, and allow a grace period after a start. §4.4.

**A service stopped with `SIGSTOP` is never restarted**
A stopped process cannot handle `SIGTERM`, so a supervisor that sends `SIGTERM` and
waits will wait forever. Escalate to `SIGKILL` after a timeout.

**The service I just stopped came back on its own**
That is the fifteen-minute `termux-job-scheduler` job doing its job. Create the
disable flag first: `touch /root/.services_disabled` (or `.private_docs_disabled`,
`.code_server_disabled`).

**`termux-job-scheduler --period-ms 60000` still runs every fifteen minutes**
Fifteen minutes is the platform floor for a periodic job. Asking for less is accepted
and then ignored.

**`tmux` dies when the SSH connection drops**
The `tmux` server was started inside `proot`, which makes it a tracee like everything
else. Start `tmux` from the Termux shell and log into Ubuntu from inside the session.

## 7.3 The public address

**`ERR_NGROK_334`: the endpoint is already online**
A new agent claimed the domain before the edge retired the previous session. Add
`--pooling-enabled`. With a supervisor that restarts on failure you will hit this
within a day.

**`ERR_NGROK_3200`: endpoint offline, while the agent is running**
This is the hung-tunnel case from §4.4. Restart the agent and add an active health
check so that the next occurrence is measured in seconds rather than the 23 minutes it
cost here.

**Visitors see "You are about to visit ..." before the site**
`ERR_NGROK_6024`, the free plan's browser interstitial. `curl` and API clients are not
affected. Sending `ngrok-skip-browser-warning` skips it; removing it entirely needs a
paid plan or your own domain.

**An external request returns a web server that is not yours**
Your DNS name points at the house; the router decides which machine inside answers. An
old port-forward for port 80 will happily serve a desktop PC instead. Check the
forwarding table before blaming the phone.

**No port can be forwarded at all**
Compare `curl -s https://api.ipify.org` with `ip route get 1.1.1.1`. A WAN address
inside `100.64.0.0/10` means carrier-grade NAT, and only a tunnel gets in.

**Cloudflare will not let me add a Public Hostname**
A Named Tunnel needs a domain you own and have delegated to Cloudflare's nameservers.
Free subdomains cannot be delegated. [`03-public-address.md`](03-public-address.md).

## 7.4 The private services

**`refusing to bind to 0.0.0.0` and exit code 2**
Working as intended. The bind address is the only firewall available, so an address
outside the tailnet and loopback ranges is a startup failure rather than a warning.

**The docs viewer stays in `waiting` and never opens a port**
No Tailscale address was found: the app is off, or the phone has just booted. The
server retries every five seconds and deliberately opens no socket until it has the
right address.

**The docs viewer exits with code 3**
The tailnet address changed. A bound socket cannot be moved, so it exits and the
supervisor starts it again on the new address.

**Everything is running but the browser cannot connect**
In order: is Tailscale on, on *both* devices? Does `./private_docs.sh status` print
`listening`? Are you using the tailnet address rather than the LAN address? A refused
connection from the Wi-Fi address is the design working.

**A document returns 404 even though the file exists**
It is not in `private_docs.list`. The request's filename is a key into that list, never
a path. Add a line; no restart needed.

**VS Code Remote-SSH: "This machine does not meet ... prerequisites"**
SSH lands in Termux, which is bionic — not glibc, not musl. Nothing will make the VS
Code server install there. Run code-server inside the container and use a browser.
[`05-private-access.md`](05-private-access.md) §5.7.

**code-server restarts in a loop right after starting**
Two causes, often together: the health check is probing before the editor is ready
(give it 90 seconds), and the process pattern matches only the wrapper, not the Node
process that actually listens — so the supervisor restarts a healthy service.

**The browser says the certificate is not trusted**
Install the CA on that device, and compare the SHA-256 fingerprint that
`./code_server.sh status` prints first.

**A certificate from my own CA fails verification**
If it was issued for a LAN IP or a public domain, that is the name constraint working
correctly. The CA is permitted to vouch for tailnet addresses and `*.ts.net` only.

## 7.5 The site and publishing

**The dashboard shows no data, but `curl` on the same URL returns 200**
A CORS preflight. The browser sends `OPTIONS` first because of a non-standard request
header; Python's `BaseHTTPRequestHandler` answers an unimplemented method with **501**
and the real request never happens. Handle `OPTIONS` explicitly.
[`02-web-server.md`](02-web-server.md) §2.3.

**Assets 404 for a few seconds after publishing**
The build directory was written over while it was being served. Build into a new
directory and swap a symlink with `mv -T`, which is a single `rename(2)`.

**`hugo` fails on the phone but builds fine on a laptop**
Two usual causes. `timeZone = "Asia/Seoul"` in the configuration fails because this
minimal Ubuntu has no `tzdata` — leave it out. Or the theme declares a `min_version`
above the `apt` Hugo (0.154.5 here) and refuses to build.

**`git push` is rejected for a path under `.github/workflows/`**
A classic token with only the `repo` scope cannot push workflow files. Either grant the
`workflow` scope, or do what this repository does and build on the phone instead of in
Actions.

**GitHub Pages does not update after a push to `gh-pages`**
A push does not reliably trigger a Pages build — observed once here, then not at all
for eight minutes. Request one over the API:

```bash
curl -X POST -H "Authorization: token <token>" \
     https://api.github.com/repos/<owner>/<repo>/pages/builds
```

**The site on github.com differs from the site on the phone**
Pages serves the branch, so an edit made in the GitHub web editor is not on the phone.
`./publish_blog.sh status` shows which commit each copy is serving; `publish` brings
them back together.

## 7.6 The phone itself

**A battery notification arrives every fifteen minutes**
A battery resting exactly on the threshold. Add hysteresis: return to the normal state
only once the reading has moved a few points past the threshold.

**The Tapo plug times out, or answers a handshake with 400 or 403**
Timeouts: the plug loses packets (15 % here, against 1 % to the router). Send as few
requests as possible, retry the whole exchange instead of raising the timeout, and
judge the result by the phone's charging status. A 400 on handshake 2 means the
session cookie did not go back: if you hand python-kasa your own aiohttp session, its
cookie jar must be created with `unsafe=True`, or it ignores cookies from an IP address. A 403 on handshake 1 means the plug refuses local control altogether; turning
Third-Party Compatibility off and on again in the Tapo app ended it here, with the
firmware unchanged, twice in two days. The plug can also come back refusing after it has
been unplugged and plugged in again. Otherwise, if `tapo_plug.py status` never succeeds,
check the account in `/root/.config/tapo/credentials`.

**The Tapo app switches the plug, but the phone cannot reach it**
`Cannot connect to host` from `tapo_plug.py`, `No route to host` on a plain TCP connect,
and broadcast discovery finds nothing. The app works through TP-Link's cloud, so the plug
can be online there while it has stopped answering on the LAN. Compare the IP in the
app's device info with `/root/.config/tapo/host`; if it moved, write the new one there
(and reserve it in the router). If it is the same, unplug the plug and plug it in again,
then expect a 403 and toggle Third-Party Compatibility as above.

**`nproc` says 5 on an eight-core phone; load average never changes**
Android hot-unplugs idle cores, so the visible count moves. The static load average is
`proot` faking `/proc/loadavg` — read `sysinfo(2)` instead, or take the number from the
Termux side.

**The phone gets hot and everything slows down**
Thermal throttling. Take the case off, keep the screen off and dim, and do not run
heavy builds while fast-charging. Watch `temp` in `battery_watch.log` and set a ceiling
before you start a load test. [`06-operations.md`](06-operations.md).

**The tunnel drops a few minutes after the screen turns off**
Doze. Run `termux-wake-lock`, and turn off battery optimisation for Termux in Android's
settings. Both are needed; neither alone is enough.

---

If something here is wrong, or you hit a failure that is not listed, open an issue with
your phone model, Android version and the output of the relevant `status` command.
