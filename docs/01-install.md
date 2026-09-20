# 1. Installation — from a bare phone to an Ubuntu shell

<b>English</b> · [한국어](01-install.ko.md)

[← README](../README.md) · Next: [2. Web server](02-web-server.md)

---

At the end of this page the phone runs Ubuntu 26.04 with Python, Git and Hugo, and
you can reach it from a laptop over SSH. Nothing here needs root.

![Termux — from a bare app to an Ubuntu shell](images/term-install.svg)

## 1.1 Prepare the phone itself

Do this before installing anything, in Android's own settings. Each item is a way
Android will otherwise kill your server.

| Setting | Where | Why |
|:---|:---|:---|
| Battery optimisation → **off** for Termux | Settings → Apps → Termux → Battery | Android suspends optimised apps, which stops the supervisor loop |
| **Keep Wi-Fi on during sleep** | Settings → Wi-Fi → Advanced | otherwise the tunnel drops minutes after the screen turns off |
| Screen timeout → short, brightness → low | Settings → Display | the screen is the biggest power draw and the biggest heat source |
| Automatic updates → **off** | Play Store → Settings | an unattended reboot in the middle of the night is not what you want |

Keep the phone plugged in. Charging it from 30 % to 80 % and holding it there is
much kinder to the battery than sitting at 100 %; [`06-operations.md`](06-operations.md)
covers the script that alerts you either way.

## 1.2 Install the apps from F-Droid

Install **Termux**, **Termux:Boot** and **Termux:API** from
[F-Droid](https://f-droid.org/en/packages/com.termux/), in one sitting.

> **Do not mix stores.** The Play Store build of Termux is abandoned, and Android
> refuses to let apps signed with different keys talk to each other. An F-Droid
> Termux with a Play Store Termux:API gives you a `termux-battery-status` that
> silently never answers.

Open Termux:Boot once after installing it. It does nothing visible, but an add-on
that has never been launched is never granted its boot permission.

## 1.3 Update Termux before anything else

```bash
pkg update && pkg upgrade -y
```

Run this first, not later. Termux builds against Android's **bionic** libc rather
than glibc, and its packages assume the library versions currently in the
repository. Install something big on a stale base and the dynamic linker refuses:

```
CANNOT LINK EXECUTABLE "node": cannot locate symbol "..." referenced by
"/data/data/com.termux/files/usr/bin/node"...
```

That error is a version mismatch, not a broken package. `pkg upgrade` fixes it.

Then add what the rest of this guide needs, and take a wake lock:

```bash
pkg install proot-distro termux-api openssh tmux
termux-wake-lock
```

`termux-wake-lock` keeps the CPU from sleeping when the screen turns off. Without it
the phone enters Doze a few minutes after you put it down and the network stalls.

## 1.4 Why a Linux container, and not Termux alone

Termux can install Python, Node and clang directly, so the extra layer looks
unnecessary. It is necessary for anything you did not get from `pkg`.

A self-contained binary downloaded from a vendor — a 197 MB CLI tool, in the case
that forced this decision — expects glibc and an ELF layout that Android's linker
accepts. It hangs or dies at the linker. `termux-elf-cleaner` rewrites the headers
and is worth one attempt, but four rounds of patch-and-retry on that binary changed
nothing.

The cheaper move is to stop bending binaries and give them the environment they
expect. `proot-distro` runs a real distribution's root filesystem inside Termux
using `ptrace`, with no root and no kernel support:

```bash
proot-distro install ubuntu
proot-distro login ubuntu
```

The prompt becomes `root@localhost:~#`, and `/etc/os-release` says Ubuntu 26.04 LTS.
That `root` is not real root — see [`04-always-on.md`](04-always-on.md) for what the
emulation does and does not give you.

## 1.5 Fix the certificate bundle first

```bash
apt-get update
apt-get install --reinstall ca-certificates
```

A `proot-distro` rootfs is minimal — around 90 packages — and its CA bundle is
missing or stale. Until you reinstall it, every HTTPS client fails certificate
verification, and the error messages blame the remote server rather than your
trust store. This is the single most common first-hour failure in a phone Linux.

## 1.6 Install what you actually need

```bash
apt-get install -y python3 git curl hugo
python3 -V          # 3.14.6 here
hugo version        # 0.154.5+extended, from apt
```

The servers in this repository use **only the Python standard library**, so there is
no `pip install` step and nothing to keep up to date. Hugo comes from `apt` on
purpose: the phone must be able to build the site offline, and a version pinned by
the distribution is one less moving part. If you plan to use a Hugo theme, check its
`min_version` against what `apt` gives you before committing to it.

## 1.7 Reach the phone from a laptop

Typing shell commands on a phone screen gets old within an hour. Run `sshd` on the
**Termux** side — port 8022, because binding 22 needs root:

```bash
# in Termux, not inside Ubuntu
passwd              # set a password for SSH
sshd
whoami              # your username, e.g. u0_a283
ip addr show wlan0 | grep 'inet '
```

From the laptop:

```bash
ssh u0_a283@192.168.0.42 -p 8022
```

Then `proot-distro login ubuntu` to get into Ubuntu. An SSH session lands in Termux,
never in the container — worth remembering, because VS Code's Remote-SSH fails for
exactly this reason ([`05-private-access.md`](05-private-access.md)).

## 1.8 Make long jobs survive a dropped connection

Mobile SSH connections die. Start anything slow inside `tmux`, and start `tmux` from
**Termux**, not from inside the container:

```bash
tmux new -s work
# ctrl-b d to detach, tmux attach -t work to come back
```

A `tmux` server started inside `proot` is itself a `proot` tracee and dies with the
login session. `termux/claude-session.sh` in this repository is that pattern written
down: it refuses to run if it detects it is being traced, then opens the session on
the Termux side and logs into Ubuntu from there.

## 1.9 Verify before moving on

| Check | Expected |
|:---|:---|
| `uname -m` inside Ubuntu | `aarch64` |
| `cat /etc/os-release \| head -1` | `PRETTY_NAME="Ubuntu 26.04.1 LTS"` |
| `curl -sI https://github.com \| head -1` | `HTTP/2 200` — if this fails, redo 1.5 |
| `ssh u0_a283@<phone-ip> -p 8022` from the laptop | a Termux prompt |
| `free -h` | around 3.7 GiB total, some swap in use |

Next: serve something over HTTP → [2. Web server](02-web-server.md)
