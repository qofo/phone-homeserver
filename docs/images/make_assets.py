#!/usr/bin/env python3
"""Generates the SVG diagrams and terminal transcripts used by the docs.

Run from anywhere:  python3 docs/images/make_assets.py
Every file it writes lands next to this script. The SVGs carry their own
background so they stay readable in GitHub's light and dark themes.
"""
import os

OUT = os.path.dirname(os.path.abspath(__file__))

# GitHub-ish palette. Diagrams sit on a light card, terminals on a dark one.
BG      = "#ffffff"
CARD    = "#f6f8fa"
BORDER  = "#d0d7de"
INK     = "#1f2328"
MUTED   = "#656d76"
GREEN   = "#1a7f37"   # Android
DARK    = "#24292f"   # Termux
ORANGE  = "#bc4c00"   # Ubuntu / proot
BLUE    = "#0969da"   # public internet
PURPLE  = "#8250df"   # tailnet only
RED     = "#cf222e"

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Svg:
    def __init__(self, w, h, title, desc=""):
        self.w, self.h = w, h
        self.parts = []
        self.title = title
        self.desc = desc

    def rect(self, x, y, w, h, fill=BG, stroke=BORDER, rx=8, sw=1.5, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, size=12, fill=INK, font=SANS, weight="normal",
             anchor="start"):
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{esc(s)}</text>')

    def line(self, x1, y1, x2, y2, stroke=MUTED, sw=1.5, dash=None, arrow=True):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        a = ' marker-end="url(#a)"' if arrow else ""
        self.parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
            f'stroke-width="{sw}"{d}{a}/>')

    def path(self, d, stroke=MUTED, sw=1.5, dash=None, arrow=True, fill="none"):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        a = ' marker-end="url(#a)"' if arrow else ""
        self.parts.append(
            f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{da}{a}/>')

    def card(self, x, y, w, h, label, stroke, fill=BG, label_fill=None, dash=None):
        self.rect(x, y, w, h, fill=fill, stroke=stroke, dash=dash)
        self.text(x + 14, y + 22, label, size=12.5, weight="bold",
                  fill=label_fill or stroke)

    def node(self, x, y, w, h, lines, stroke=BORDER, fill=CARD, mono_first=True):
        self.rect(x, y, w, h, fill=fill, stroke=stroke, rx=6, sw=1.3)
        ty = y + 21
        for i, ln in enumerate(lines):
            if i == 0:
                self.text(x + 12, ty, ln, size=11.5, weight="bold", fill=INK,
                          font=MONO if mono_first else SANS)
            else:
                self.text(x + 12, ty, ln, size=10.5, fill=MUTED, font=SANS)
            ty += 16

    def save(self, name):
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
            f'height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" '
            f'aria-label="{esc(self.title)}">'
            f'<title>{esc(self.title)}</title>'
            + (f'<desc>{esc(self.desc)}</desc>' if self.desc else '')
            + '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" '
              'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
              f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{MUTED}"/></marker></defs>'
            f'<rect width="{self.w}" height="{self.h}" fill="{BG}"/>')
        body = "".join(self.parts)
        with open(os.path.join(OUT, name), "w") as f:
            f.write(head + body + "</svg>\n")
        print("wrote", name)


# --------------------------------------------------------------------------
# 1. The layer stack
# --------------------------------------------------------------------------
def architecture():
    s = Svg(900, 580, "Layer stack of the phone server",
            "Android hosts Termux, Termux hosts a proot Ubuntu, and Ubuntu runs "
            "three independent supervisors.")
    s.text(24, 30, "One phone, four layers, three independent supervisors",
           size=16, weight="bold")
    s.text(24, 50, "Nothing here needs root, a router setting, or a cloud VM.",
           size=11.5, fill=MUTED)

    s.card(20, 64, 860, 446, "Android 9  ·  Galaxy Note FE (SM-N935L, aarch64)  ·  not rooted", GREEN)
    s.card(38, 96, 824, 398, "Termux  ·  the only app involved", DARK, fill=CARD)

    s.node(56, 128, 336, 54,
           ["Termux:Boot", "runs ~/.termux/boot/*.sh once, after every reboot"],
           stroke=DARK, fill=BG)
    s.node(406, 128, 438, 54,
           ["termux-job-scheduler  (every 15 min)",
            "re-launches any supervisor that is missing — outside proot"],
           stroke=DARK, fill=BG)

    s.card(56, 202, 788, 274, "proot-distro: Ubuntu 26.04 LTS  ·  glibc, no systemd, fake root", ORANGE)

    cols = [
        (72, "start_services.sh", "public", BLUE, [
            ("serve_blog.py  :8080", "Hugo build + /api/metrics"),
            ("ngrok  tunnel", "fixed free domain, HTTPS"),
        ]),
        (330, "private_docs.sh", "tailnet only", PURPLE, [
            ("private_docs_server.py  :8081", "markdown viewer, no directory listing"),
            ("private_docs.list", "an explicit allow-list of files"),
        ]),
        (588, "code_server.sh", "tailnet only", PURPLE, [
            ("code-server  :8443", "VS Code in the browser, over HTTPS"),
            ("local CA", "name-constrained, issued on the phone"),
        ]),
    ]
    for x, sup, zone, zc, children in cols:
        s.node(x, 236, 240, 52, [sup, "supervisor \u00b7 10 s loop \u00b7 own session"],
               stroke=ORANGE, fill=CARD)
        y = 310
        prev_bottom = 288
        for name, note in children:
            s.line(x + 120, prev_bottom, x + 120, y - 6, stroke=MUTED)
            s.node(x, y, 240, 52, [name, note], stroke=BORDER, fill=BG)
            prev_bottom = y + 52
            y += 64
        s.rect(x, 440, 240, 24, fill=BG, stroke=zc, rx=12, sw=1.3)
        s.text(x + 120, 456, zone, size=10.5, weight="bold", fill=zc, anchor="middle")

    s.text(24, 532, "The public internet reaches only the blue port. The purple "
                    "ports are bound to the Tailscale address,", size=11, fill=MUTED)
    s.text(24, 548, "so they do not exist for anyone else. Every supervisor is "
                    "launched from Termux with setsid, because proot", size=11, fill=MUTED)
    s.text(24, 564, "runs with --kill-on-exit and would otherwise take its children "
                    "down with the login session.", size=11, fill=MUTED)
    s.save("architecture.svg")


# --------------------------------------------------------------------------
# 2. Boot and survival chain
# --------------------------------------------------------------------------
def boot_chain():
    s = Svg(900, 470, "How a service survives a reboot, a crash and a logout")
    s.text(24, 30, "Why the launcher lives outside proot", size=16, weight="bold")
    s.text(24, 50, "Three triggers, one launcher, one session that no terminal owns.",
           size=11.5, fill=MUTED)

    trig = [("reboot", "Termux:Boot", 70), ("every 15 min", "termux-job-scheduler", 190),
            ("manual", "start_services.sh start", 310)]
    for label, name, y in trig:
        s.node(24, y, 250, 52, [name, f"trigger: {label}"], stroke=DARK, fill=CARD)
        s.line(274, y + 26, 316, 216 + 26 if y != 216 else y + 26, stroke=MUTED)

    s.node(316, 190, 250, 104,
           ["termux/ensure-daemon.sh", "already running? exit 0",
            "disabled flag set? exit 0", "otherwise: setsid nohup proot-distro …"],
           stroke=GREEN, fill=BG)

    s.line(566, 242, 610, 242, stroke=MUTED)
    s.node(610, 216, 266, 52,
           ["supervisor (start-daemon)", "own session, no controlling terminal"],
           stroke=ORANGE, fill=CARD)

    s.path("M 743 268 L 743 300 L 743 316", stroke=MUTED)
    s.node(610, 316, 266, 78,
           ["serve_blog.py  +  ngrok", "restarted within 10 s if the process is gone",
            "killed and restarted if it answers wrong"],
           stroke=BORDER, fill=BG)

    s.text(24, 392, "What each layer defends against", size=12.5, weight="bold")
    rows = [
        ("reboot", "Termux:Boot re-runs the launcher"),
        ("Android's low-memory killer", "the 15-minute job re-runs it too"),
        ("Ctrl+C or a closed SSH session", "setsid put the supervisor in its own session"),
        ("a process that lives but stopped working", "the supervisor probes it, not just pgrep"),
    ]
    y = 414
    for a, b in rows:
        s.text(30, y, "•", size=11, fill=MUTED)
        s.text(44, y, a, size=11, weight="bold", fill=INK)
        s.text(300, y, b, size=11, fill=MUTED)
        y += 17
    s.save("boot-chain.svg")


# --------------------------------------------------------------------------
# 3. Who can reach what
# --------------------------------------------------------------------------
def network_paths():
    s = Svg(900, 440, "Public path versus tailnet-only path")
    s.text(24, 30, "Two doors, and the one that does not exist", size=16, weight="bold")
    s.text(24, 50, "With no firewall inside proot, the bind address is the firewall.",
           size=11.5, fill=MUTED)

    s.node(24, 92, 190, 62, ["anyone on the internet", "a link in a blog post"],
           stroke=BLUE, fill=CARD)
    s.node(24, 214, 190, 62, ["your laptop / other phone", "signed in to your tailnet"],
           stroke=PURPLE, fill=CARD)
    s.node(24, 320, 190, 62, ["anyone on the same Wi-Fi", "a stranger on café Wi-Fi"],
           stroke=RED, fill=CARD)

    s.line(214, 123, 270, 123, stroke=BLUE)
    s.node(270, 96, 200, 54, ["ngrok edge", "fixed free HTTPS domain"],
           stroke=BLUE, fill=BG)
    s.line(470, 123, 526, 123, stroke=BLUE)

    s.line(214, 245, 526, 245, stroke=PURPLE)
    s.text(300, 238, "WireGuard tunnel · 100.x.y.z", size=10.5, fill=PURPLE)

    s.path("M 214 351 L 430 351", stroke=RED, dash="5 4")
    s.text(232, 342, "port never bound on the LAN address", size=10.5, fill=RED)
    s.text(440, 356, "✕", size=20, fill=RED)

    s.card(526, 76, 350, 290, "the phone", ORANGE)
    s.node(546, 108, 310, 52, ["0.0.0.0:8080   serve_blog.py", "public on purpose"],
           stroke=BLUE, fill=CARD)
    s.node(546, 176, 310, 52, ["100.x.y.z:8081   private_docs_server.py",
                               "bound to the Tailscale address only"],
           stroke=PURPLE, fill=CARD)
    s.node(546, 244, 310, 52, ["100.x.y.z:8443   code-server",
                               "bound to the Tailscale address only"],
           stroke=PURPLE, fill=CARD)
    s.text(546, 330, "A service bound to 100.x.y.z has no socket on wlan0.",
           size=10.5, fill=MUTED)
    s.text(546, 346, "Scanning the Wi-Fi subnet finds nothing to connect to.",
           size=10.5, fill=MUTED)

    s.text(24, 398, "The private services add four more checks on top of the bind "
                    "address: the peer address, the Host header,", size=11, fill=MUTED)
    s.text(24, 414, "an explicit file allow-list, and a strict content security "
                    "policy in the browser.", size=11, fill=MUTED)
    s.save("network-paths.svg")


# --------------------------------------------------------------------------
# 4. One source, two servers
# --------------------------------------------------------------------------
def publish_pipeline():
    s = Svg(900, 340, "Publishing the same commit to the phone and to GitHub Pages")
    s.text(24, 30, "One source, two servers, same commit", size=16, weight="bold")
    s.text(24, 50, "publish_blog.sh builds both copies with the same Hugo binary.",
           size=11.5, fill=MUTED)

    s.node(24, 128, 220, 70, ["qofo.github.io/", "Hugo source: content/, themes/",
                              "content-phone/ is phone-only"],
           stroke=ORANGE, fill=CARD)
    s.line(244, 163, 300, 163, stroke=MUTED)
    s.node(300, 128, 210, 70, ["publish_blog.sh", "phone · pages · publish · status",
                               "one script, four verbs"],
           stroke=GREEN, fill=BG)

    s.path("M 510 150 L 566 110", stroke=BLUE)
    s.node(566, 76, 310, 74, ["blog_builds/<timestamp>/  →  blog_public",
                              "symlink swapped with rename(2), so a visitor",
                              "never sees a half-written build"],
           stroke=BLUE, fill=CARD)

    s.path("M 510 178 L 566 218", stroke=PURPLE)
    s.node(566, 190, 310, 74, ["gh-pages branch  →  GitHub Pages",
                               "pushed from the phone; a Pages build is",
                               "requested over the API when none starts"],
           stroke=PURPLE, fill=CARD)

    s.text(24, 240, "Why the phone builds Pages too", size=12.5, weight="bold")
    s.text(24, 262, "The git credential is a classic token with only the repo scope,",
           size=11, fill=MUTED)
    s.text(24, 278, "so a push that contains .github/workflows/ is refused. Building",
           size=11, fill=MUTED)
    s.text(24, 294, "on the phone takes about two seconds and needs no Actions minutes.",
           size=11, fill=MUTED)
    s.save("publish-pipeline.svg")


# --------------------------------------------------------------------------
# 5. Health check state machine
# --------------------------------------------------------------------------
def health_check():
    s = Svg(900, 330, "Active health check instead of a process check")
    s.text(24, 30, "A process that is alive but not working", size=16, weight="bold")
    s.text(24, 50, "pgrep said RUNNING for 23 minutes while visitors got an error page.",
           size=11.5, fill=MUTED)

    s.node(24, 100, 200, 56, ["every 10 s", "the supervisor wakes up"],
           stroke=BORDER, fill=CARD)
    s.line(224, 128, 268, 128, stroke=MUTED)
    s.node(268, 100, 210, 56, ["is the process there?", "pgrep on an anchored pattern"],
           stroke=BORDER, fill=BG)
    s.line(478, 128, 522, 128, stroke=MUTED)
    s.node(522, 100, 230, 56, ["does it answer correctly?",
                               "HTTP probe on the real port"],
           stroke=GREEN, fill=BG)

    s.path("M 637 156 L 637 196", stroke=RED)
    s.text(648, 182, "no, three times in a row", size=10.5, fill=RED)
    s.node(522, 196, 230, 56, ["kill it, then restart", "downtime written to a log"],
           stroke=RED, fill=CARD)
    s.path("M 522 224 L 400 224 L 400 160", stroke=MUTED)

    s.text(24, 216, "Thresholds that matter", size=12.5, weight="bold")
    rows = [
        ("3 consecutive failures", "one slow answer is not an outage"),
        ("90 s grace after a start", "code-server needs time to come up"),
        ("probe the endpoint, not the port", "ngrok answers on the port while offline"),
    ]
    y = 238
    for a, b in rows:
        s.text(30, y, "•", size=11, fill=MUTED)
        s.text(44, y, a, size=11, weight="bold")
        s.text(252, y, b, size=11, fill=MUTED)
        y += 17
    s.text(24, 310, "Full incident write-up: docs/07-troubleshooting.md and part 7 "
                    "of the blog series.", size=10.5, fill=MUTED)
    s.save("health-check.svg")


# --------------------------------------------------------------------------
# Terminal transcripts
# --------------------------------------------------------------------------
T_BG, T_CHROME, T_TXT, T_DIM = "#0d1117", "#161b22", "#e6edf3", "#8b949e"
T_GREEN, T_BLUE, T_YELL, T_RED, T_CYAN = "#3fb950", "#58a6ff", "#d29922", "#ff7b72", "#39c5cf"
CH, LH = 7.9, 20.5


def terminal(name, title, lines, width=None):
    cols = max(len(t) for _, t in lines) if lines else 40
    cols = max(cols, len(title) + 10)
    w = int(width or (cols * CH + 44))
    h = int(len(lines) * LH + 74)
    s = Svg(w, h, title)
    s.parts = []
    s.rect(0, 0, w, h, fill=T_BG, stroke="#30363d", rx=10, sw=1)
    s.rect(0, 0, w, 34, fill=T_CHROME, stroke=T_CHROME, rx=10, sw=1)
    s.rect(0, 24, w, 10, fill=T_CHROME, stroke=T_CHROME, rx=0, sw=0)
    for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        s.parts.append(f'<circle cx="{20 + i * 18}" cy="17" r="5.5" fill="{c}"/>')
    s.text(w / 2, 21, title, size=11.5, fill=T_DIM, font=MONO, anchor="middle")
    y = 58
    for kind, txt in lines:
        if kind == "cmd":
            s.text(16, y, "$", size=13, fill=T_GREEN, font=MONO, weight="bold")
            s.text(16 + 2 * CH, y, txt, size=13, fill=T_TXT, font=MONO)
        elif kind == "root":
            s.text(16, y, "#", size=13, fill=T_CYAN, font=MONO, weight="bold")
            s.text(16 + 2 * CH, y, txt, size=13, fill=T_TXT, font=MONO)
        else:
            colour = {"out": T_DIM, "ok": T_GREEN, "warn": T_YELL, "err": T_RED,
                      "hi": T_TXT, "note": T_BLUE}.get(kind, T_DIM)
            s.text(16, y, txt, size=13, fill=colour, font=MONO)
        y += LH
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">'
            f'<title>{esc(title)}</title>')
    with open(os.path.join(OUT, name), "w") as f:
        f.write(head + "".join(s.parts) + "</svg>\n")
    print("wrote", name)


def term_install():
    terminal("term-install.svg", "Termux — from a bare app to an Ubuntu shell", [
        ("cmd", "pkg update && pkg upgrade -y"),
        ("cmd", "pkg install proot-distro termux-api openssh"),
        ("cmd", "proot-distro install ubuntu"),
        ("out", "[*] Downloading ubuntu rootfs (aarch64) ..."),
        ("out", "[*] Extracting ...  [*] Installed"),
        ("cmd", "proot-distro login ubuntu"),
        ("root", "cat /etc/os-release | head -1"),
        ("ok", 'PRETTY_NAME="Ubuntu 26.04.1 LTS"'),
        ("root", "uname -m"),
        ("ok", "aarch64"),
        ("root", "apt-get update && apt-get install --reinstall ca-certificates"),
        ("note", "# a minimal rootfs ships ~90 packages and no usable CA bundle,"),
        ("note", "# so every HTTPS call fails until this runs"),
    ])


def term_status():
    terminal("term-status.svg", "the three status commands, on the live phone", [
        ("cmd", "./start_services.sh status"),
        ("hi", "=== Galaxy Note FE Service Status ==="),
        ("ok", "Supervisor:   [RUNNING] (PID 13261) - detached"),
        ("ok", "Blog Server:  [RUNNING] (PID 13325) - port 8080, HTTP 200"),
        ("ok", "ngrok Tunnel: [RUNNING] - https://<your-domain>.ngrok-free.dev (online)"),
        ("out", "Auto-start:   [ENABLED]"),
        ("warn", "Last Downtime: 168s (unexpected_shutdown_or_reboot)"),
        ("out", ""),
        ("cmd", "./private_docs.sh status"),
        ("hi", "=== Private Docs (Tailscale only) ==="),
        ("ok", "Server:     [RUNNING] - http://100.x.y.z:8081/ (HTTP 200)"),
        ("out", "Documents:  5 listed in /root/private_docs.list"),
        ("out", ""),
        ("cmd", "./code_server.sh status"),
        ("hi", "=== code-server (Tailscale only) ==="),
        ("ok", "Server:     [RUNNING] (352 MB) - https://100.x.y.z:8443/ (healthz 200)"),
        ("out", "            also https://<this-device>.<tailnet>.ts.net:8443/"),
        ("out", "TLS:        server certificate valid until Oct 22 04:32:44 2027 GMT"),
    ])


def term_specs():
    terminal("term-specs.svg", "what a 2017 phone actually gives you", [
        ("root", "uname -m && nproc && free -h | head -3"),
        ("ok", "aarch64"),
        ("ok", "5"),
        ("out", "               total        used        free      available"),
        ("out", "Mem:           3.7Gi       2.2Gi       174Mi         1.5Gi"),
        ("out", "Swap:          2.0Gi       1.3Gi       687Mi"),
        ("root", "df -h / | tail -1"),
        ("out", "/dev/block/dm-1   54G   15G   40G  27% /"),
        ("root", "python3 -V && hugo version | cut -d' ' -f1-2"),
        ("ok", "Python 3.14.6"),
        ("ok", "hugo v0.154.5+extended"),
        ("note", "# nproc reports 5, not 8: Android hot-unplugs idle cores."),
        ("note", "# /proc/stat and /proc/loadavg inside proot are static fakes,"),
        ("note", "# so CPU load has to be read from the Termux side instead."),
    ])


def term_verify():
    terminal("term-verify.svg", "proving it works, from outside the phone", [
        ("cmd", "curl -sI https://<your-domain>.ngrok-free.dev/ | head -2"),
        ("ok", "HTTP/2 200"),
        ("out", "content-type: text/html; charset=utf-8"),
        ("cmd", "python3 tests/test_serve_blog.py"),
        ("ok", "Ran 35 tests in 4.812s   OK"),
        ("cmd", "python3 tests/test_private_docs.py"),
        ("ok", "Ran 47 tests in 6.204s   OK"),
        ("cmd", "curl -s -o /dev/null -w '%{http_code}\\n' http://<lan-ip>:8081/"),
        ("err", "000        # refused: nothing is listening on the Wi-Fi address"),
        ("cmd", "./measure_downtime.py --once &"),
        ("cmd", "./start_services.sh restart"),
        ("out", "probing every 0.5 s until the address answers again"),
        ("ok", "downtime: 11.6 s   (appended to downtime.log)"),
    ])


if __name__ == "__main__":
    architecture()
    boot_chain()
    network_paths()
    publish_pipeline()
    health_check()
    term_install()
    term_status()
    term_specs()
    term_verify()
