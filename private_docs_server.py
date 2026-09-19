#!/usr/bin/env python3
"""Private Markdown viewer that answers only inside the Tailscale network.

The server binds to this device's Tailscale IPv4 address (100.64.0.0/10), never to
0.0.0.0, so the LAN, mobile data and the public ngrok tunnel (which forwards to
:8080) cannot reach it. On top of the bind address every request is checked for a
peer IP and a Host header inside the tailnet. Which documents exist is decided by
an allow-list file, not by the filesystem.

Environment (used by the tests; the defaults are the production values):
  PRIVATE_DOCS_BIND   "auto" (Tailscale address) or an explicit tailnet/loopback IP
  PRIVATE_DOCS_PORT   listening port (8081)
  PRIVATE_DOCS_ALLOW  comma-separated peer/Host networks
  PRIVATE_DOCS_LIST   allow-list file (private_docs.list next to this script)
  PRIVATE_DOCS_STATE  state file read by private_docs.sh (the supervisor)
"""
import datetime
import fcntl
import html
import http.server
import ipaddress
import json
import os
import re
import signal
import socket
import socketserver
import stat
import struct
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PRIVATE_DOCS_PORT", "8081"))
BIND = os.environ.get("PRIVATE_DOCS_BIND", "auto")
LIST_FILE = os.environ.get("PRIVATE_DOCS_LIST", os.path.join(HERE, "private_docs.list"))
STATE_FILE = os.environ.get("PRIVATE_DOCS_STATE", os.path.join(HERE, ".private_docs.state"))
STATIC_DIR = os.path.join(HERE, "private_docs_static")
MAX_DOC_BYTES = 2 * 1024 * 1024
KST = datetime.timezone(datetime.timedelta(hours=9))

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
ALLOWED_NETS = [
    ipaddress.ip_network(n.strip())
    for n in os.environ.get("PRIVATE_DOCS_ALLOW", f"{TAILNET_V4},{TAILNET_V6}").split(",")
    if n.strip()
]

NAME_RE = re.compile(r"^(?!\.)[\w.\-]+\.md$")
STATIC_FILES = {
    "style.css": "text/css",
    "viewer.js": "application/javascript",
    "marked.umd.min.js": "application/javascript",
    "purify.min.js": "application/javascript",
}

# Scripts and styles come from this origin only; images may not leave the device.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
}


def log(message):
    print(f"[{datetime.datetime.now(KST):%Y-%m-%d %H:%M:%S KST}] {message}", flush=True)


def write_state(text):
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(text + "\n")
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def find_tailnet_ip():
    """Return this device's Tailscale IPv4 address, whatever the interface is called.

    /proc/net/fib_trie is unreadable here, so ask the kernel per interface
    (SIOCGIFADDR). The Android VPN interface name changes between boots (tun0, tun1...).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            try:
                packed = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
            except OSError:
                continue
            ip = socket.inet_ntoa(packed[20:24])
            if ipaddress.ip_address(ip) in TAILNET_V4:
                return ip
    finally:
        sock.close()
    return None


def bind_address_allowed(ip):
    addr = ipaddress.ip_address(ip)
    return addr in TAILNET_V4 or addr.is_loopback


def load_docs():
    """Map file name -> real path for every entry of the allow-list that is a regular .md file."""
    docs = {}
    base = os.path.dirname(os.path.abspath(LIST_FILE))
    try:
        with open(LIST_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return docs
    for raw in lines:
        entry = raw.split("#", 1)[0].strip()
        if not entry:
            continue
        path = os.path.normpath(entry if os.path.isabs(entry) else os.path.join(base, entry))
        name = os.path.basename(path)
        if not NAME_RE.match(name) or name in docs:
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode) and st.st_size <= MAX_DOC_BYTES:
            docs[name] = path
    return docs


def doc_title(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            for _, line in zip(range(60), f):
                if line.startswith("# "):
                    return re.sub(r"[`*_]", "", line[2:]).strip() or fallback
    except OSError:
        pass
    return fallback


def page(title, body, extra_head=""):
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex,nofollow\"><meta name=\"referrer\" content=\"no-referrer\">"
        f"<title>{html.escape(title)}</title><link rel=\"stylesheet\" href=\"/static/style.css\">{extra_head}"
        f"</head><body>{body}</body></html>"
    ).encode("utf-8")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "PrivateDocs"
    sys_version = ""
    timeout = 30

    def log_message(self, fmt, *args):
        pass  # routine requests are not logged; refusals are (see _refuse)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # --- access control -------------------------------------------------
    def _peer_ok(self):
        try:
            peer = ipaddress.ip_address(self.client_address[0].split("%")[0])
        except ValueError:
            return False
        if peer.version == 6 and peer.ipv4_mapped:
            peer = peer.ipv4_mapped
        return any(peer in net for net in ALLOWED_NETS)

    def _host_ok(self):
        """Refuse Host headers that are not this device's tailnet address or name (DNS rebinding)."""
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):
            name = host[1:].split("]")[0]
        elif host.count(":") == 1:
            name = host.rsplit(":", 1)[0]
        else:
            name = host
        try:
            addr = ipaddress.ip_address(name)
            return any(addr in net for net in ALLOWED_NETS)
        except ValueError:
            pass
        name = name.lower().rstrip(".")
        return bool(name) and (name.endswith(".ts.net") or "." not in name)

    def _refuse(self, why):
        log(f"[DENY] {why} peer={self.client_address[0]} host={self.headers.get('Host')!r} path={self.path[:80]!r}")
        self._send(403, b"forbidden\n", "text/plain; charset=utf-8")

    # --- responses --------------------------------------------------------
    def _send(self, code, body, ctype, head=False, extra=None, security=True):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if security:
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _not_allowed(self):
        self._send(405, b"method not allowed\n", "text/plain; charset=utf-8", extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed

    def do_HEAD(self):
        self._dispatch(True)

    def do_GET(self):
        self._dispatch(False)

    def _dispatch(self, head):
        if not self._peer_ok():
            return self._refuse("peer outside the tailnet")
        if not self._host_ok():
            return self._refuse("Host header outside the tailnet")

        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            return self._index(head)
        if path == "/healthz":
            return self._send(200, b"ok\n", "text/plain; charset=utf-8", head)
        if path == "/api/docs":
            return self._api_docs(head)
        if path.startswith("/doc/"):
            return self._viewer(urllib.parse.unquote(path[5:]), head)
        if path.startswith("/raw/"):
            return self._raw(urllib.parse.unquote(path[5:]), head)
        if path.startswith("/static/"):
            return self._static(path[8:], head)
        self._send(404, b"not found\n", "text/plain; charset=utf-8", head)

    def _index(self, head):
        rows = []
        for name, path in load_docs().items():
            st = os.stat(path)
            when = datetime.datetime.fromtimestamp(st.st_mtime, KST).strftime("%Y-%m-%d %H:%M")
            rows.append(
                f"<tr><td><a href=\"/doc/{urllib.parse.quote(name)}\">{html.escape(doc_title(path, name))}</a></td>"
                f"<td><code>{html.escape(name)}</code></td><td>{when}</td><td class=\"num\">{st.st_size / 1024:.1f} KB</td></tr>"
            )
        table = (
            "<div class=\"tablewrap\"><table><thead><tr><th>문서</th><th>파일</th><th>수정 (KST)</th><th>크기</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>" if rows else "<p>공개된 문서가 없다.</p>"
        )
        body = (
            "<header class=\"bar\"><span>내부 문서</span><span class=\"scope\">Tailscale 전용</span></header>"
            f"<main class=\"index\"><h1>내부 문서</h1><p class=\"note\">이 서버는 Tailscale 대역에서만 응답한다. "
            f"공개 블로그와 ngrok 주소에서는 보이지 않는다.</p>{table}</main>"
        )
        self._send(200, page("내부 문서", body), "text/html; charset=utf-8", head)

    def _api_docs(self, head):
        data = [{"name": n, "title": doc_title(p, n)} for n, p in load_docs().items()]
        self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", head)

    def _lookup(self, name):
        return load_docs().get(name) if NAME_RE.match(name) else None

    def _viewer(self, name, head):
        path = self._lookup(name)
        if not path:
            return self._send(404, b"not found\n", "text/plain; charset=utf-8", head)
        body = (
            "<header class=\"bar\"><a href=\"/\">&larr; 문서 목록</a><span class=\"scope\">Tailscale 전용</span></header>"
            "<div class=\"layout\"><nav id=\"toc\" aria-label=\"목차\"></nav>"
            f"<main id=\"content\" data-doc=\"{html.escape(name, quote=True)}\"><p class=\"loading\">불러오는 중…</p></main></div>"
            "<noscript><p class=\"note\">문서를 보려면 자바스크립트가 필요하다. 원문: "
            f"<a href=\"/raw/{urllib.parse.quote(name)}\">{html.escape(name)}</a></p></noscript>"
            "<script src=\"/static/marked.umd.min.js\"></script><script src=\"/static/purify.min.js\"></script>"
            "<script src=\"/static/viewer.js\"></script>"
        )
        self._send(200, page(doc_title(path, name), body), "text/html; charset=utf-8", head)

    def _raw(self, name, head):
        path = self._lookup(name)
        if not path:
            return self._send(404, b"not found\n", "text/plain; charset=utf-8", head)
        try:
            with open(path, "rb") as f:
                data = f.read(MAX_DOC_BYTES + 1)
        except OSError:
            return self._send(404, b"not found\n", "text/plain; charset=utf-8", head)
        self._send(200, data, "text/plain; charset=utf-8", head)

    def _static(self, name, head):
        ctype = STATIC_FILES.get(name)
        if not ctype:
            return self._send(404, b"not found\n", "text/plain; charset=utf-8", head)
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                data = f.read()
        except OSError:
            return self._send(404, b"not found\n", "text/plain; charset=utf-8", head)
        self._send(200, data, f"{ctype}; charset=utf-8", head, extra={"Cache-Control": "max-age=300"})


class DocsServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def cleanup(*_):
    try:
        os.remove(STATE_FILE)
    except OSError:
        pass


def on_signal(signum, _frame):
    log(f"signal {signum}; shutting down")
    cleanup()
    os._exit(0)


def wait_for_address():
    """Block until there is an address to bind to (the VPN may come up after boot)."""
    announced = 0.0
    while True:
        ip = find_tailnet_ip() if BIND == "auto" else BIND
        if ip:
            return ip
        write_state("waiting")
        if time.time() - announced > 60:
            log("no Tailscale address yet; waiting for the VPN")
            announced = time.time()
        time.sleep(5)


def watch_address(bound):
    """Exit when the Tailscale address changed so the supervisor rebinds; report VPN outages."""
    while True:
        time.sleep(30)
        if BIND != "auto":
            continue
        current = find_tailnet_ip()
        if current is None:
            write_state(f"offline {bound}:{PORT}")
        elif current != bound:
            log(f"Tailscale address changed {bound} -> {current}; exiting to rebind")
            os._exit(3)
        else:
            write_state(f"listening {bound}:{PORT}")


def main():
    if BIND != "auto" and not bind_address_allowed(BIND):
        log(f"refusing to bind to {BIND}: only tailnet (100.64.0.0/10) or loopback addresses are allowed")
        return 2
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    address = wait_for_address()
    if not bind_address_allowed(address):
        log(f"refusing to bind to {address}")
        return 2
    try:
        server = DocsServer((address, PORT), Handler)
    except OSError as exc:
        log(f"cannot bind {address}:{PORT}: {exc}")
        return 1
    write_state(f"listening {address}:{PORT}")
    log(f"listening on http://{address}:{PORT}/ (tailnet only, {len(load_docs())} documents)")
    threading.Thread(target=watch_address, args=(address,), daemon=True).start()
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
