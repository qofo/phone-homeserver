import http.server
import socketserver
import os
import json
import re
import time
import threading
import shutil
import subprocess
import urllib.parse
import ctypes
import sys

PORT = int(os.environ.get("BLOG_PORT", "8080"))
BATTERY_SYSFS = "/sys/class/power_supply/battery"

# proot-distro replaces /proc/stat, /proc/uptime and /proc/loadavg with static files
# (Android denies the real ones), so live values come from sysfs and syscalls instead.
class _SysInfo(ctypes.Structure):
    # Leading fields of struct sysinfo; the tail buffer covers the rest
    _fields_ = [("uptime", ctypes.c_long), ("loads", ctypes.c_ulong * 3), ("_rest", ctypes.c_char * 128)]

try:
    _libc = ctypes.CDLL(None, use_errno=True)
except OSError:
    _libc = None

# ---------------------------------------------------------
# Telemetry Collector Engine
# ---------------------------------------------------------
class TelemetryCollector:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_cpu_time = time.time()
        self.last_cpu_stat = self._read_cpu_times()
        self.last_net_time = time.time()
        self.last_net_bytes = self._read_net_bytes()
        
        self.cached_battery = None
        self.last_battery_check = 0
        
        self.cached_metrics = None
        self.last_metrics_time = 0

        # Start asynchronous background battery worker thread
        self.battery_thread = threading.Thread(target=self._battery_worker, daemon=True)
        self.battery_thread.start()

    def _online_cpus(self):
        cpus = set()
        try:
            with open("/sys/devices/system/cpu/online", "r") as f:
                for part in f.read().strip().split(","):
                    lo, _, hi = part.partition("-")
                    cpus.update(range(int(lo), int(hi or lo) + 1))
        except (OSError, ValueError):
            pass
        return cpus

    def _read_cpu_times(self):
        # Per-core (idle, total) in microseconds: idle is the sum of the cpuidle state
        # counters, total is wall time. Offline cores have no cpuidle directory and are skipped.
        cpus = {}
        wall_us = int(time.monotonic() * 1_000_000)
        for i in self._online_cpus():
            base = f"/sys/devices/system/cpu/cpu{i}/cpuidle"
            idle = 0
            try:
                for state in os.listdir(base):
                    if state.startswith("state"):
                        with open(f"{base}/{state}/time", "r") as f:
                            idle += int(f.read())
            except (OSError, ValueError):
                continue
            cpus[f"cpu{i}"] = (idle, wall_us)
        return cpus

    def _read_net_bytes(self):
        net = {"rx": 0, "tx": 0, "interfaces": {}}
        try:
            with open("/proc/net/dev", "r") as f:
                lines = f.readlines()
            for line in lines[2:]:
                parts = line.split(":")
                if len(parts) == 2:
                    iface = parts[0].strip()
                    if iface in ["lo"]:
                        continue
                    data = parts[1].split()
                    rx = int(data[0])
                    tx = int(data[8])
                    net["rx"] += rx
                    net["tx"] += tx
                    net["interfaces"][iface] = {"rx": rx, "tx": tx}
        except Exception:
            pass
        return net

    def _read_cpu_freqs(self):
        freqs = {}
        for i in range(8):
            p = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq"
            try:
                with open(p, "r") as f:
                    freqs[i] = int(f.read().strip()) // 1000
            except:
                freqs[i] = 0
        return freqs

    def _read_memory(self):
        mem = {}
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        mem[key] = int(val)
        except Exception:
            pass

        total = mem.get("MemTotal", 1)
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        used = total - avail
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = swap_total - swap_free

        return {
            "ram_total_mb": total // 1024,
            "ram_used_mb": used // 1024,
            "ram_percent": round((used / total) * 100, 1) if total > 0 else 0,
            "swap_total_mb": swap_total // 1024,
            "swap_used_mb": swap_used // 1024,
            "swap_percent": round((swap_used / swap_total) * 100, 1) if swap_total > 0 else 0
        }

    def _read_storage(self):
        try:
            s = os.statvfs("/")
            total_gb = round((s.f_blocks * s.f_frsize) / (1024**3), 1)
            free_gb = round((s.f_bavail * s.f_frsize) / (1024**3), 1)
            used_gb = round(total_gb - free_gb, 1)
            pct = round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0
            return {
                "total_gb": total_gb,
                "used_gb": used_gb,
                "free_gb": free_gb,
                "percent": pct
            }
        except Exception:
            return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}

    def _read_battery_sysfs(self):
        # The kernel exposes the battery directly, so readings keep working when the
        # Termux:API app is not running. Returns None if the nodes are not readable.
        def node(path, default=""):
            try:
                with open(path, "r") as f:
                    return f.read().strip()
            except OSError:
                return default

        level = node(f"{BATTERY_SYSFS}/capacity")
        if not level.isdigit():
            return None

        plugged = "UNPLUGGED"
        for source, label in (("ac", "PLUGGED_AC"), ("usb", "PLUGGED_USB"), ("wireless", "PLUGGED_WIRELESS")):
            if node(f"/sys/class/power_supply/{source}/online") == "1":
                plugged = label
                break

        temp = node(f"{BATTERY_SYSFS}/temp")
        return {
            "available": True,
            "cli_installed": True,
            "app_installed": True,
            "percentage": int(level),
            "status": node(f"{BATTERY_SYSFS}/status", "UNKNOWN").upper().replace(" ", "_"),
            "plugged": plugged,
            "temperature": round(int(temp) / 10.0, 1) if temp.lstrip("-").isdigit() else 0,
            "health": node(f"{BATTERY_SYSFS}/health", "UNKNOWN").upper().replace(" ", "_"),
            "source": "sysfs",
        }

    def _battery_worker(self):
        # Fallback path only. Each termux-battery-status call starts an Android VM
        # (app_process), so it is skipped entirely while sysfs answers.
        cmd = shutil.which("termux-battery-status")
        while True:
            if self._read_battery_sysfs() is not None:
                time.sleep(60)
                continue

            if not cmd:
                cmd = shutil.which("termux-battery-status")

            if not cmd:
                self.cached_battery = {
                    "available": False,
                    "cli_installed": False,
                    "app_installed": False,
                    "reason": "Termux 터미널에서 'pkg install termux-api' 실행이 필요합니다."
                }
                time.sleep(5)
                continue

            # Check if Android companion APK (com.termux.api) is installed
            app_installed = False
            try:
                pm = subprocess.run(["/system/bin/pm", "list", "packages", "com.termux.api"], capture_output=True, text=True, timeout=1.5)
                if "package:com.termux.api" in pm.stdout:
                    app_installed = True
            except Exception:
                app_installed = True

            if not app_installed:
                self.cached_battery = {
                    "available": False,
                    "cli_installed": True,
                    "app_installed": False,
                    "reason": "터미널 패키지(CLI)는 정상 설치되었으나, 스마트폰에 'Termux:API' 안드로이드 보조 앱(APK)이 아직 설치되지 않았습니다."
                }
                time.sleep(5)
                continue

            try:
                res = subprocess.run([cmd], capture_output=True, text=True, timeout=6.0)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    self.cached_battery = {
                        "available": True,
                        "cli_installed": True,
                        "app_installed": True,
                        "percentage": data.get("percentage", 0),
                        "status": data.get("status", "UNKNOWN"),
                        "plugged": data.get("plugged", "UNPLUGGED"),
                        "temperature": data.get("temperature", 0),
                        "health": data.get("health", "GOOD")
                    }
                else:
                    self.cached_battery = {
                        "available": False,
                        "cli_installed": True,
                        "app_installed": True,
                        "reason": "Termux:API 응답 없음 (안드로이드 앱 권한 확인 필요)"
                    }
            except Exception as e:
                # Do not overwrite a previously valid battery reading on a single timeout
                if not self.cached_battery or not self.cached_battery.get("available"):
                    self.cached_battery = {
                        "available": False,
                        "cli_installed": True,
                        "app_installed": True,
                        "reason": str(e)
                    }

            time.sleep(4)

    def _read_battery(self):
        # sysfs first: no app, no subprocess, no timeout
        live = self._read_battery_sysfs()
        if live:
            return live
        if self.cached_battery:
            return self.cached_battery
        return {
            "available": False,
            "cli_installed": True,
            "app_installed": True,
            "reason": "배터리 상태 초기화 중..."
        }


    def _read_uptime_load(self):
        uptime_sec = 0
        try:
            uptime_sec = time.clock_gettime(time.CLOCK_BOOTTIME)
        except (AttributeError, OSError):
            pass

        load = [0.0, 0.0, 0.0]
        try:
            info = _SysInfo()
            if _libc is not None and _libc.sysinfo(ctypes.byref(info)) == 0:
                load = [round(x / 65536.0, 2) for x in info.loads]
        except (AttributeError, OSError):
            pass

        days = int(uptime_sec // 86400)
        hours = int((uptime_sec % 86400) // 3600)
        minutes = int((uptime_sec % 3600) // 60)
        uptime_str = f"{days}일 {hours}시간 {minutes}분" if days > 0 else f"{hours}시간 {minutes}분"

        return {
            "uptime_seconds": uptime_sec,
            "uptime_str": uptime_str,
            "load_avg": load
        }

    def _read_downtime(self):
        last_dt = None
        if os.path.exists("/root/.last_downtime"):
            try:
                with open("/root/.last_downtime", "r", encoding="utf-8") as f:
                    parts = f.read().strip().split("|")
                    if len(parts) >= 4:
                        last_dt = {
                            "duration_seconds": int(parts[0]),
                            "reason": parts[1],
                            "start": parts[2],
                            "end": parts[3]
                        }
            except Exception:
                pass

        current_outage = None
        if os.path.exists("/root/.downtime_start"):
            try:
                with open("/root/.downtime_start", "r", encoding="utf-8") as f:
                    parts = f.read().strip().split("|")
                    if len(parts) >= 3:
                        cur_ts = int(parts[0])
                        current_outage = {
                            "ongoing_seconds": max(0, int(time.time() - cur_ts)),
                            "reason": parts[1],
                            "start": parts[2]
                        }
            except Exception:
                pass

        return {
            "last_downtime": last_dt,
            "current_outage": current_outage
        }

    def get_metrics(self):
        with self.lock:
            now = time.time()
            if self.cached_metrics and (now - self.last_metrics_time < 0.8):
                return self.cached_metrics

            # CPU Delta Calculation
            cur_cpu = self._read_cpu_times()
            cur_cpu_time = now
            dt_cpu = cur_cpu_time - self.last_cpu_time
            if dt_cpu <= 0: dt_cpu = 0.001

            cpu_usage = {}
            for k in cur_cpu:
                if k in self.last_cpu_stat:
                    idle_d = cur_cpu[k][0] - self.last_cpu_stat[k][0]
                    total_d = cur_cpu[k][1] - self.last_cpu_stat[k][1]
                    if total_d > 0:
                        pct = round(100.0 * (1.0 - (idle_d / total_d)), 1)
                        cpu_usage[k] = max(0.0, min(100.0, pct))
                    else:
                        cpu_usage[k] = 0.0
                else:
                    cpu_usage[k] = 0.0

            # Overall usage is the average of the online cores
            if cpu_usage:
                cpu_usage["cpu"] = round(sum(cpu_usage.values()) / len(cpu_usage), 1)

            self.last_cpu_stat = cur_cpu
            self.last_cpu_time = cur_cpu_time

            # Network Delta Calculation
            cur_net = self._read_net_bytes()
            dt_net = now - self.last_net_time
            if dt_net <= 0: dt_net = 0.001

            rx_diff = max(0, cur_net["rx"] - self.last_net_bytes["rx"])
            tx_diff = max(0, cur_net["tx"] - self.last_net_bytes["tx"])
            rx_kbs = round((rx_diff / 1024.0) / dt_net, 1)
            tx_kbs = round((tx_diff / 1024.0) / dt_net, 1)

            self.last_net_bytes = cur_net
            self.last_net_time = now

            freqs = self._read_cpu_freqs()
            mem = self._read_memory()
            storage = self._read_storage()
            battery = self._read_battery()
            uptime_load = self._read_uptime_load()

            # Structure 8 CPU Cores
            # 0-3: Little Cores (Cortex-A53)
            # 4-7: Big Cores (Exynos-M1)
            cores = []
            for i in range(8):
                cname = f"cpu{i}"
                is_big = i >= 4
                cores.append({
                    "id": i,
                    "name": f"Core {i} ({'Exynos-M1' if is_big else 'Cortex-A53'})",
                    "type": "big" if is_big else "little",
                    "usage_percent": cpu_usage.get(cname, 0.0),
                    "freq_mhz": freqs.get(i, 0)
                })

            metrics = {
                "timestamp": now,
                "device": {
                    "model": "Samsung Galaxy Note Fan Edition (SM-N935L)",
                    "soc": "Samsung Exynos 8890 (8-Core aarch64)",
                    "os": "Ubuntu 26.04.1 LTS (Termux PRoot)"
                },
                "cpu": {
                    "total_percent": cpu_usage.get("cpu", 0.0),
                    "cores": cores
                },
                "memory": mem,
                "storage": storage,
                "network": {
                    "rx_kbs": rx_kbs,
                    "tx_kbs": tx_kbs,
                    "active_interfaces": list(cur_net["interfaces"].keys())
                },
                "battery": battery,
                "system": uptime_load,
                "downtime": self._read_downtime()
            }

            self.cached_metrics = metrics
            self.last_metrics_time = now
            return metrics

telemetry = TelemetryCollector()

# ---------------------------------------------------------
# Static site (Hugo build) + telemetry API
# ---------------------------------------------------------
# publish_blog.sh builds the Hugo site into a fresh directory and repoints this
# symlink at it, so a request never sees a half-written build.
SITE_DIR = os.environ.get("BLOG_SITE_DIR", "/root/blog_public")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

# Hugo fingerprints bundled CSS/JS (site.min.<sha256>.css), so those never change in place
FINGERPRINTED = re.compile(r"\.[0-9a-f]{64}\.(css|js)$")

# Served only when no build exists yet. A restart cannot fix a missing build, so this
# answers 200 and the supervisor's health check does not loop restarting the server.
NO_BUILD_PAGE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>준비 중</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; padding: 0 1rem; line-height: 1.7;">
<h1>폰 사본을 준비하고 있다</h1>
<p>이 폰에는 아직 블로그 빌드가 없다. 같은 글을 <a href="https://qofo.github.io/">GitHub Pages</a>에서 읽을 수 있다.</p>
</body></html>
""".encode("utf-8")
_warned_no_build = False

METRICS_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    # GitHub Pages visitors fetch through ngrok, whose free plan answers browsers with a
    # warning page unless this header is present; the header makes the browser preflight.
    "Access-Control-Allow-Headers": "ngrok-skip-browser-warning",
    "Access-Control-Max-Age": "7200",
}


def resolve_static(url_path):
    """Map a URL path to (kind, value).

    kind is "file" (value = absolute path), "redirect" (value = path with a trailing slash),
    "missing" or "no_build". Paths that escape the site root, contain dot segments or
    control characters are reported as "missing".
    """
    root = os.path.realpath(SITE_DIR)
    if not os.path.isfile(os.path.join(root, "index.html")):
        return "no_build", None

    path = urllib.parse.unquote(url_path, errors="strict") if "%" in url_path else url_path
    if not path.startswith("/") or "\\" in path or any(ord(c) < 32 for c in path):
        return "missing", None
    parts = [p for p in path.split("/") if p]
    if any(p.startswith(".") for p in parts):
        return "missing", None

    def inside(p):
        return p == root or p.startswith(root + os.sep)

    candidate = os.path.realpath(os.path.join(root, *parts))
    if not inside(candidate):
        return "missing", None

    if os.path.isdir(candidate):
        if not path.endswith("/"):
            # Rebuilt from the segments, so "//host" can never become a protocol-relative Location
            return "redirect", "/" + "/".join(parts) + "/"
        candidate = os.path.realpath(os.path.join(candidate, "index.html"))
        if not inside(candidate):
            return "missing", None
    if os.path.isfile(candidate):
        return "file", candidate
    return "missing", None


class BlogRequestHandler(http.server.BaseHTTPRequestHandler):
    # Drop idle or stalled clients instead of holding a worker thread forever
    timeout = 30

    def do_HEAD(self):
        self.do_GET(head_only=True)

    def do_OPTIONS(self):
        # CORS preflight for /api/metrics from the GitHub Pages copy of the site
        self.send_response(204)
        if urllib.parse.urlsplit(self.path).path == "/api/metrics":
            for k, v in METRICS_CORS.items():
                self.send_header(k, v)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self, head_only=False):
        path = urllib.parse.urlsplit(self.path).path

        if path == "/api/metrics":
            data = json.dumps(telemetry.get_metrics(), ensure_ascii=False).encode("utf-8")
            self.send_body(200, data, "application/json; charset=utf-8", head_only,
                           {"Cache-Control": "no-store", **METRICS_CORS})
            return

        try:
            kind, value = resolve_static(path)
        except UnicodeDecodeError:
            kind, value = "missing", None

        if kind == "file":
            self.send_file(value, head_only)
        elif kind == "redirect":
            self.send_response(301)
            self.send_header("Location", urllib.parse.quote(value))
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif kind == "no_build":
            global _warned_no_build
            if not _warned_no_build:
                print(f"[WARN] No site build at {SITE_DIR}; run /root/publish_blog.sh phone", flush=True)
                _warned_no_build = True
            if path == "/":
                self.send_body(200, NO_BUILD_PAGE, "text/html; charset=utf-8", head_only,
                               {"Cache-Control": "no-store"})
            else:
                self.send_body(404, NO_BUILD_PAGE, "text/html; charset=utf-8", head_only,
                               {"Cache-Control": "no-store"})
        else:
            page = os.path.join(os.path.realpath(SITE_DIR), "404.html")
            try:
                with open(page, "rb") as f:
                    body = f.read()
            except OSError:
                body = b"Not Found"
            self.send_body(404, body, "text/html; charset=utf-8", head_only, {"Cache-Control": "no-cache"})

    def send_body(self, code, body, content_type, head_only, extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def send_file(self, file_path, head_only):
        try:
            f = open(file_path, "rb")
        except OSError:
            self.send_error(404)
            return
        with f:
            st = os.fstat(f.fileno())
            etag = '"%x-%x"' % (st.st_mtime_ns, st.st_size)
            if FINGERPRINTED.search(file_path):
                cache = "public, max-age=31536000, immutable"
            else:
                cache = "no-cache"

            if etag in [t.strip() for t in self.headers.get("If-None-Match", "").split(",")]:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", cache)
                self.end_headers()
                return

            ext = os.path.splitext(file_path)[1].lower()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(st.st_size))
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only:
                shutil.copyfileobj(f, self.wfile)

    def log_message(self, format, *args):
        pass

class BlogServer(socketserver.ThreadingTCPServer):
    # One thread per request, so a slow client cannot block everyone else
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Visitors dropping the connection mid-response is routine; keep other tracebacks
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)

def run():
    with BlogServer(("0.0.0.0", PORT), BlogRequestHandler) as httpd:
        print(f"Blog & Dashboard server running on http://0.0.0.0:{PORT}, serving {SITE_DIR}")
        httpd.serve_forever()

if __name__ == "__main__":
    run()
