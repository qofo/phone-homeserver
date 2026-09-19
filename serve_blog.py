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
POSTS_DIR = "/posts"
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
# Posts & Metadata
# ---------------------------------------------------------
def plain_text(text):
    # Card excerpts are inserted as plain text, so drop markdown link and emphasis marks
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_]", "", text)
    return text.strip()

def extract_metadata(filename, content):
    # Everything comes from the file itself: "# 제목", a "작성일"/"태그" quote block,
    # and the first ordinary paragraph as the card excerpt.
    title = ""
    date = ""
    tags = []
    excerpt = ""

    for line in content.splitlines():
        line_s = line.strip()
        if not title and line_s.startswith("# "):
            title = re.sub(r"^\[(.*)\]$", r"\1", line_s[2:].strip())
        elif not date and "작성일" in line_s:
            match = re.search(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", line_s)
            if match:
                date = match.group(0)
        elif not tags and "태그" in line_s:
            tags = re.findall(r"`([^`]+)`", line_s)
        elif not excerpt and line_s and line_s[0] not in "#>-*|`":
            line_s = plain_text(line_s)
            excerpt = line_s[:160] + "..." if len(line_s) > 160 else line_s

    return {
        "id": filename.replace(".md", ""),
        "filename": filename,
        "title": title or filename.replace(".md", ""),
        "date": date,
        "tags": tags,
        "excerpt": excerpt
    }

def get_all_posts():
    if not os.path.exists(POSTS_DIR):
        return []
    files = sorted([f for f in os.listdir(POSTS_DIR) if f.endswith(".md")])
    posts = []
    for f in files:
        path = os.path.join(POSTS_DIR, f)
        try:
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()
            meta = extract_metadata(f, content)
            posts.append(meta)
        except Exception as e:
            print(f"Error reading {f}: {e}")
    return posts

# ---------------------------------------------------------
# HTML Single Page App Template
# ---------------------------------------------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>스마트폰 한 대로 서버 만들기 · Mobile DevLog</title>
  <!-- Pretendard Font -->
  <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css" />
  <!-- Marked.js for Markdown parsing -->
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <!-- Highlight.js for syntax highlighting -->
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <style>
    :root {
      --bg-color: #0b0f19;
      --card-bg: #151c2c;
      --card-border: #233047;
      --card-hover: #1e293b;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-glow: rgba(56, 189, 248, 0.15);
      --accent-hover: #0ea5e9;
      --code-bg: #0b0f19;
      --table-border: #233047;
      --table-stripe: #151c2c;
      --table-header: #1e293b;
      --badge-bg: rgba(56, 189, 248, 0.12);
      --badge-text: #38bdf8;
      --header-bg: rgba(11, 15, 25, 0.88);
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
    }

    [data-theme="light"] {
      --bg-color: #f8fafc;
      --card-bg: #ffffff;
      --card-border: #e2e8f0;
      --card-hover: #f1f5f9;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --accent: #0284c7;
      --accent-glow: rgba(2, 132, 199, 0.1);
      --accent-hover: #0369a1;
      --code-bg: #f1f5f9;
      --table-border: #e2e8f0;
      --table-stripe: #f8fafc;
      --table-header: #f1f5f9;
      --badge-bg: #e0f2fe;
      --badge-text: #0284c7;
      --header-bg: rgba(248, 250, 252, 0.88);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
      background-color: var(--bg-color);
      color: var(--text-main);
      line-height: 1.75;
      padding-bottom: 80px;
      -webkit-font-smoothing: antialiased;
      transition: background-color 0.2s ease, color 0.2s ease;
    }

    /* Top Sticky Header */
    .top-header {
      position: sticky;
      top: 0;
      z-index: 100;
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      background-color: var(--header-bg);
      border-bottom: 1px solid var(--card-border);
      padding: 12px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      max-width: 1000px;
      margin: 0 auto;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 700;
      font-size: 1.15rem;
      color: var(--text-main);
      text-decoration: none;
      cursor: pointer;
    }

    .brand .logo-icon {
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      color: white;
      width: 32px;
      height: 32px;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.1rem;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .nav-btn {
      background: none;
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s ease;
    }

    .nav-btn.active {
      background-color: var(--badge-bg);
      border-color: var(--accent);
      color: var(--accent);
    }

    .nav-btn:hover {
      background-color: var(--card-hover);
      border-color: var(--accent);
    }

    .theme-toggle {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      width: 34px;
      height: 34px;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 1.05rem;
      transition: all 0.2s ease;
    }

    .container {
      max-width: 960px;
      margin: 0 auto;
      padding: 24px 16px 0;
    }

    /* Views */
    #homeView, #articleView, #dashboardView {
      display: none;
    }

    /* Hero / Intro section */
    .hero {
      background: linear-gradient(135deg, var(--card-bg) 0%, rgba(30, 41, 59, 0.4) 100%);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 24px 20px;
      margin-bottom: 28px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
    }

    .hero-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background-color: var(--badge-bg);
      color: var(--badge-text);
      font-size: 0.8rem;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 9999px;
      margin-bottom: 12px;
    }

    .hero h1 {
      font-size: 1.6rem;
      font-weight: 800;
      line-height: 1.35;
      margin-bottom: 10px;
      background: linear-gradient(135deg, #ffffff 40%, var(--accent) 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    [data-theme="light"] .hero h1 {
      background: linear-gradient(135deg, #0f172a 40%, var(--accent) 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .hero p {
      color: var(--text-muted);
      font-size: 0.92rem;
      margin-bottom: 16px;
    }

    /* Live Mini Telemetry Pill Widget in Hero */
    .telemetry-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px;
      background: rgba(0, 0, 0, 0.2);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      cursor: pointer;
      transition: all 0.2s;
    }

    .telemetry-pills:hover {
      border-color: var(--accent);
      background: rgba(56, 189, 248, 0.05);
    }

    .pill-item {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.82rem;
      background: var(--card-bg);
      padding: 4px 10px;
      border-radius: 8px;
      border: 1px solid var(--card-border);
    }

    .pill-label { color: var(--text-muted); }
    .pill-val { font-weight: 700; color: var(--accent); }

    /* Post Cards */
    .section-title {
      font-size: 1.25rem;
      font-weight: 700;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .posts-grid {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .post-card {
      background-color: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px;
      cursor: pointer;
      text-decoration: none;
      color: inherit;
      transition: all 0.2s ease;
      display: block;
    }

    .post-card:hover {
      transform: translateY(-2px);
      border-color: var(--accent);
      box-shadow: 0 8px 24px var(--accent-glow);
    }

    .post-card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 8px;
      gap: 12px;
    }

    .post-card-title {
      font-size: 1.15rem;
      font-weight: 700;
      color: var(--text-main);
      line-height: 1.45;
    }

    .post-card:hover .post-card-title { color: var(--accent); }

    .post-card-date {
      font-size: 0.8rem;
      color: var(--text-muted);
      white-space: nowrap;
    }

    .post-card-excerpt {
      font-size: 0.9rem;
      color: var(--text-muted);
      margin-bottom: 14px;
      line-height: 1.6;
    }

    .post-card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }

    .tags { display: flex; flex-wrap: wrap; gap: 6px; }
    .tag {
      background-color: var(--badge-bg);
      color: var(--badge-text);
      font-size: 0.75rem;
      padding: 2px 8px;
      border-radius: 6px;
      font-weight: 500;
    }
    .read-more {
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--accent);
    }

    /* Article Viewer */
    .article-header-nav {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
    }

    .back-btn {
      background-color: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s ease;
    }

    .back-btn:hover {
      background-color: var(--card-hover);
      border-color: var(--accent);
      color: var(--accent);
    }

    .post-switcher { display: flex; gap: 6px; }
    .post-switch-btn {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
    }
    .post-switch-btn.active {
      background-color: var(--badge-bg);
      color: var(--accent);
      border-color: var(--accent);
    }

    .article-card {
      background-color: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 32px 28px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
    }

    @media (max-width: 640px) {
      .article-card { padding: 20px 16px; border-radius: 12px; }
    }

    /* Markdown Styles */
    .markdown-body h1 {
      font-size: 1.7rem; font-weight: 800; margin-bottom: 16px; line-height: 1.35;
      padding-bottom: 12px; border-bottom: 1px solid var(--card-border); color: var(--text-main);
    }
    .markdown-body h2 {
      font-size: 1.35rem; font-weight: 700; margin-top: 36px; margin-bottom: 14px;
      line-height: 1.4; color: var(--accent);
    }
    .markdown-body h3 { font-size: 1.15rem; font-weight: 600; margin-top: 24px; margin-bottom: 10px; }
    .markdown-body p { margin-bottom: 16px; color: var(--text-main); }
    .markdown-body blockquote {
      border-left: 4px solid var(--accent); padding: 12px 18px; background: var(--badge-bg);
      color: var(--text-main); border-radius: 0 8px 8px 0; margin: 18px 0;
    }
    .markdown-body pre {
      background-color: var(--code-bg) !important; border: 1px solid var(--card-border);
      border-radius: 10px; padding: 16px; overflow-x: auto; margin: 18px 0; position: relative;
    }
    .markdown-body code { font-family: "JetBrains Mono", Consolas, Menlo, monospace; font-size: 0.88rem; }
    .markdown-body p code, .markdown-body li code {
      background: var(--code-bg); border: 1px solid var(--card-border); padding: 2px 6px;
      border-radius: 4px; color: var(--accent);
    }
    .copy-btn {
      position: absolute; top: 8px; right: 8px; background: var(--card-bg);
      border: 1px solid var(--card-border); color: var(--text-muted); border-radius: 6px;
      padding: 4px 8px; font-size: 0.75rem; cursor: pointer; transition: all 0.2s;
    }
    .copy-btn:hover { background: var(--card-hover); color: var(--text-main); border-color: var(--accent); }
    .copy-btn.copied { background: #10b981; color: white; border-color: #10b981; }
    .markdown-body table { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 0.88rem; overflow-x: auto; display: block; }
    .markdown-body th, .markdown-body td { border: 1px solid var(--table-border); padding: 10px 14px; text-align: left; }
    .markdown-body th { background-color: var(--table-header); font-weight: 600; }
    .markdown-body tr:nth-child(even) { background-color: var(--table-stripe); }
    .markdown-body hr { border: none; border-top: 1px solid var(--card-border); margin: 32px 0; }
    .markdown-body a { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
    .markdown-body ul, .markdown-body ol { margin-bottom: 16px; padding-left: 24px; }
    .markdown-body li { margin-bottom: 6px; }

    .article-footer-nav {
      display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 32px;
      padding-top: 24px; border-top: 1px solid var(--card-border);
    }
    @media (max-width: 600px) { .article-footer-nav { grid-template-columns: 1fr; } }
    .footer-nav-card {
      background-color: var(--card-bg); border: 1px solid var(--card-border);
      padding: 16px; border-radius: 10px; cursor: pointer; text-decoration: none;
      color: inherit; transition: all 0.2s;
    }
    .footer-nav-card:hover { border-color: var(--accent); background-color: var(--card-hover); }
    .footer-nav-label { font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px; }
    .footer-nav-title { font-size: 0.92rem; font-weight: 700; color: var(--text-main); }

    /* --------------------------------------------------------- */
    /* DASHBOARD VIEW STYLING */
    /* --------------------------------------------------------- */
    .dash-header {
      background: linear-gradient(135deg, var(--card-bg) 0%, rgba(30, 41, 59, 0.4) 100%);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 24px 20px;
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
    }

    .dash-device-title h2 { font-size: 1.35rem; font-weight: 800; margin-bottom: 4px; }
    .dash-device-meta { font-size: 0.84rem; color: var(--text-muted); display: flex; flex-wrap: wrap; gap: 10px; }

    .live-status {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: var(--success);
      font-size: 0.8rem;
      font-weight: 600;
      padding: 4px 12px;
      border-radius: 9999px;
    }

    .live-dot {
      width: 8px;
      height: 8px;
      background-color: var(--success);
      border-radius: 50%;
      animation: pulse 1.5s infinite;
    }

    @keyframes pulse {
      0% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(1.3); }
      100% { opacity: 1; transform: scale(1); }
    }

    .dash-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 18px;
      margin-bottom: 24px;
    }

    .dash-card {
      background-color: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
    }

    .dash-card-title {
      font-size: 0.92rem;
      font-weight: 700;
      color: var(--text-muted);
      margin-bottom: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .dash-big-stat {
      font-size: 2rem;
      font-weight: 800;
      color: var(--text-main);
      line-height: 1.1;
      margin-bottom: 12px;
    }

    .dash-progress-wrap {
      width: 100%;
      background: rgba(255, 255, 255, 0.08);
      height: 8px;
      border-radius: 4px;
      overflow: hidden;
      margin-bottom: 12px;
    }

    .dash-progress-bar {
      height: 100%;
      background: var(--accent);
      border-radius: 4px;
      transition: width 0.3s ease;
    }

    .dash-sub-stats {
      display: flex;
      justify-content: space-between;
      font-size: 0.82rem;
      color: var(--text-muted);
    }

    /* CPU Cores Cluster Grid */
    .cores-section-title {
      font-size: 0.8rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin: 12px 0 8px;
    }

    .cores-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .core-pill {
      background: rgba(0, 0, 0, 0.25);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 8px 10px;
    }

    .core-header {
      display: flex;
      justify-content: space-between;
      font-size: 0.75rem;
      margin-bottom: 4px;
    }

    .core-name { font-weight: 600; color: var(--text-main); }
    .core-freq { font-family: monospace; color: var(--accent); }

    .core-bar-wrap {
      width: 100%;
      height: 5px;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 3px;
      overflow: hidden;
    }

    .core-bar {
      height: 100%;
      background: var(--accent);
      border-radius: 3px;
      transition: width 0.2s ease;
    }

    /* Battery Card */
    .battery-status-box {
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 16px;
    }

    .battery-icon-large {
      font-size: 2.4rem;
      line-height: 1;
    }

    .battery-info-text h3 { font-size: 1.8rem; font-weight: 800; line-height: 1.1; }
    .battery-info-text p { font-size: 0.82rem; color: var(--text-muted); }

    .battery-notice {
      background: rgba(245, 158, 11, 0.1);
      border: 1px solid rgba(245, 158, 11, 0.3);
      padding: 10px 12px;
      border-radius: 8px;
      font-size: 0.8rem;
      color: #fbbf24;
      line-height: 1.45;
    }

    .battery-notice code {
      background: rgba(0, 0, 0, 0.3);
      padding: 2px 6px;
      border-radius: 4px;
      font-family: monospace;
      color: #fff;
    }

    .loading-spinner {
      text-align: center;
      padding: 40px;
      color: var(--text-muted);
      font-size: 1rem;
    }
  </style>
</head>
<body>

  <!-- Top Sticky Header -->
  <header class="top-header">
    <div class="brand" onclick="goHome()">
      <div class="logo-icon">⚡</div>
      <span>Antigravity DevLog</span>
    </div>
    <div class="header-actions">
      <button class="nav-btn" id="navBlogBtn" onclick="goHome()">
        <span>📚</span>
        <span>글 목록</span>
      </button>
      <button class="nav-btn" id="navDashBtn" onclick="goDashboard()">
        <span>📊</span>
        <span>대시보드</span>
      </button>
      <button class="theme-toggle" id="themeToggle" onclick="toggleTheme()" title="테마 전환">🌓</button>
    </div>
  </header>

  <div class="container">
    <!-- 1. HOME VIEW: Post List & Live Mini Telemetry -->
    <main id="homeView">
      <div class="hero">
        <div class="hero-badge">🚀 Mobile Edge Workstation</div>
        <h1>스마트폰 한 대로 서버 만들기</h1>
        <p>서랍에 있던 갤럭시 노트 FE에 Termux와 proot 우분투를 올려 24시간 도는 블로그 서버로 만든 기록입니다. 설치와 외부 공개부터 장애 분석과 재설계까지 차례로 기록하고 있습니다. 이 페이지는 그 폰이 직접 응답하고 있습니다.</p>

        <!-- Live Telemetry Mini Banner -->
        <div class="telemetry-pills" onclick="goDashboard()" title="클릭하여 상세 시스템 대시보드 열기">
          <div class="pill-item">
            <span class="pill-label">🔥 CPU</span>
            <span class="pill-val" id="miniCpu">--%</span>
          </div>
          <div class="pill-item">
            <span class="pill-label">💾 RAM</span>
            <span class="pill-val" id="miniRam">--%</span>
          </div>
          <div class="pill-item">
            <span class="pill-label">🌐 NET</span>
            <span class="pill-val" id="miniNet">-- KB/s</span>
          </div>
          <div class="pill-item">
            <span class="pill-label">🔋 BATT</span>
            <span class="pill-val" id="miniBatt">--%</span>
          </div>
          <div class="pill-item">
            <span class="pill-label">⏱️ UPTIME</span>
            <span class="pill-val" id="miniUptime">--</span>
          </div>
        </div>
      </div>

      <h2 class="section-title">📖 시리즈 포스트 목록</h2>
      <div class="posts-grid" id="postsList">
        <div class="loading-spinner">포스트 목록을 불러오는 중...</div>
      </div>
    </main>

    <!-- 2. ARTICLE VIEW: Post Reader -->
    <article class="article-view" id="articleView">
      <div class="article-header-nav">
        <button class="back-btn" onclick="goHome()">← 목록으로 돌아가기</button>
        <div class="post-switcher" id="postSwitcher"></div>
      </div>

      <div class="article-card">
        <div class="markdown-body" id="articleContent">
          <div class="loading-spinner">글을 불러오는 중입니다...</div>
        </div>
        <div class="article-footer-nav" id="articleFooterNav"></div>
      </div>
    </article>

    <!-- 3. DASHBOARD VIEW: Full System Telemetry -->
    <section class="dashboard-view" id="dashboardView">
      <div class="dash-header">
        <div class="dash-device-title">
          <h2>📱 스마트폰 시스템 실시간 텔레메트리</h2>
          <div class="dash-device-meta">
            <span>Samsung Galaxy Note FE (SM-N935L)</span>
            <span>Exynos 8890 8-Core (aarch64)</span>
            <span>Ubuntu 26.04 LTS (PRoot)</span>
          </div>
        </div>
        <div class="live-status">
          <span class="live-dot"></span>
          <span id="lastUpdatedText">실시간 수신 중 (2s)</span>
        </div>
      </div>

      <!-- Metrics Grid -->
      <div class="dash-grid">
        <!-- Card 1: CPU Overview -->
        <div class="dash-card">
          <div class="dash-card-title">
            <span>🔥 8코어 CPU 사용률</span>
            <span id="dashCpuTotalFreq" style="font-family: monospace; color: var(--accent);">-- MHz</span>
          </div>
          <div class="dash-big-stat" id="dashCpuTotal">--%</div>
          <div class="dash-progress-wrap">
            <div class="dash-progress-bar" id="dashCpuBar" style="width: 0%;"></div>
          </div>
          <div class="dash-sub-stats">
            <span>Load Avg: <b id="dashLoadAvg">--</b></span>
            <span>업타임: <b id="dashUptime">--</b></span>
          </div>
        </div>

        <!-- Card 2: Memory (RAM & Swap) -->
        <div class="dash-card">
          <div class="dash-card-title">
            <span>💾 메모리 (RAM & zRAM)</span>
            <span id="dashRamText">-- / -- MB</span>
          </div>
          <div class="dash-big-stat" id="dashRamPercent">--%</div>
          <div class="dash-progress-wrap">
            <div class="dash-progress-bar" id="dashRamBar" style="width: 0%;"></div>
          </div>
          <div class="dash-sub-stats">
            <span>zRAM Swap: <b id="dashSwapText">--%</b></span>
            <span>가용 RAM: <b id="dashRamAvail">-- MB</b></span>
          </div>
        </div>

        <!-- Card 3: Storage & Network -->
        <div class="dash-card">
          <div class="dash-card-title">
            <span>📶 네트워크 & 스토리지</span>
            <span id="dashStorageText">내장 32GB 가용</span>
          </div>
          <div class="dash-big-stat" style="font-size: 1.5rem; display: flex; justify-content: space-between;">
            <div><small style="font-size: 0.8rem; color: var(--text-muted); display: block;">다운로드 (RX)</small><span id="dashNetRx">-- KB/s</span></div>
            <div><small style="font-size: 0.8rem; color: var(--text-muted); display: block;">업로드 (TX)</small><span id="dashNetTx">-- KB/s</span></div>
          </div>
          <div class="dash-progress-wrap" style="margin-top: 14px;">
            <div class="dash-progress-bar" id="dashStorageBar" style="width: 40%; background: #818cf8;"></div>
          </div>
          <div class="dash-sub-stats">
            <span>내장 스토리지 사용률: <b id="dashStoragePct">--%</b></span>
            <span>활성 IF: <b id="dashIfaces">wlan0, tun1</b></span>
          </div>
        </div>

        <!-- Card 4: Battery & Thermals (Termux:API) -->
        <div class="dash-card">
          <div class="dash-card-title">
            <span>🔋 배터리 & 하드웨어 전원</span>
            <span id="dashBattPlugged">전원 연결됨</span>
          </div>
          <div class="battery-status-box">
            <div class="battery-icon-large" id="dashBattIcon">⚡</div>
            <div class="battery-info-text">
              <h3 id="dashBattPct">--%</h3>
              <p id="dashBattStatus">상태 확인 중...</p>
            </div>
          </div>
          <div class="dash-sub-stats" id="dashBattDetails">
            <span>온도: <b id="dashBattTemp">-- °C</b></span>
            <span>상태: <b id="dashBattHealth">GOOD</b></span>
          </div>
          <div class="battery-notice" id="dashBattNotice" style="display: none; margin-top: 10px;">
            <span>ℹ️ <b>Termux:API 미설치</b>: 폰의 실제 배터리/온도를 읽어오려면 Termux 터미널에서 <code>pkg install termux-api</code>를 실행하세요.</span>
          </div>
        </div>
      </div>

      <!-- CPU 8-Core Clustered Detail Card -->
      <div class="dash-card" style="margin-bottom: 30px;">
        <div class="dash-card-title">
          <span>⚙️ Samsung Exynos 8890 코어별 클러스터 상세 (big.LITTLE)</span>
          <span style="color: var(--text-muted); font-size: 0.8rem;">4x Exynos-M1 (Big) + 4x Cortex-A53 (Little)</span>
        </div>

        <div class="cores-section-title">🚀 고성능 빅코어 클러스터 (Cores 4~7: Exynos-M1, 최대 2.6GHz)</div>
        <div class="cores-grid" id="bigCoresGrid"></div>

        <div class="cores-section-title" style="margin-top: 16px;">🌱 저전력 리틀코어 클러스터 (Cores 0~3: Cortex-A53, 최대 1.58GHz)</div>
        <div class="cores-grid" id="littleCoresGrid"></div>
      </div>
    </section>
  </div>

  <script>
    let postsData = [];
    let currentPostId = null;
    let metricsTimer = null;

    // Theme Management
    function initTheme() {
      const saved = localStorage.getItem('theme');
      if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
      } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
        document.documentElement.setAttribute('data-theme', 'light');
      }
    }

    function toggleTheme() {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
    }

    // Navigation & Routing
    function goHome() {
      window.location.hash = '';
      showHome();
    }

    function goDashboard() {
      window.location.hash = '#dashboard';
      showDashboard();
    }

    function showHome() {
      document.getElementById('homeView').style.display = 'block';
      document.getElementById('articleView').style.display = 'none';
      document.getElementById('dashboardView').style.display = 'none';
      document.getElementById('navBlogBtn').classList.add('active');
      document.getElementById('navDashBtn').classList.remove('active');
      window.scrollTo(0, 0);
      startPollingMetrics(4000); // lighter polling on home
    }

    function showDashboard() {
      document.getElementById('homeView').style.display = 'none';
      document.getElementById('articleView').style.display = 'none';
      document.getElementById('dashboardView').style.display = 'block';
      document.getElementById('navBlogBtn').classList.remove('active');
      document.getElementById('navDashBtn').classList.add('active');
      window.scrollTo(0, 0);
      fetchMetrics(); // immediate fetch
      startPollingMetrics(2000); // 2s polling
    }

    function showPost(postId) {
      currentPostId = postId;
      document.getElementById('homeView').style.display = 'none';
      document.getElementById('articleView').style.display = 'block';
      document.getElementById('dashboardView').style.display = 'none';
      document.getElementById('navBlogBtn').classList.add('active');
      document.getElementById('navDashBtn').classList.remove('active');
      window.scrollTo(0, 0);
      stopPollingMetrics();
      loadPostContent(postId);
    }

    // Polling Controller
    function startPollingMetrics(intervalMs) {
      stopPollingMetrics();
      fetchMetrics();
      metricsTimer = setInterval(fetchMetrics, intervalMs);
    }

    function stopPollingMetrics() {
      if (metricsTimer) {
        clearInterval(metricsTimer);
        metricsTimer = null;
      }
    }

    // Metrics Fetcher & DOM Updater
    async function fetchMetrics() {
      try {
        const res = await fetch('/api/metrics');
        if (!res.ok) return;
        const data = await res.json();
        updateTelemetryUI(data);
      } catch (err) {
        // quiet error
      }
    }

    function updateTelemetryUI(data) {
      // 1. Mini widgets (Hero)
      const cpuTot = data.cpu.total_percent;
      document.getElementById('miniCpu').innerText = cpuTot + '%';
      document.getElementById('miniRam').innerText = data.memory.ram_percent + '%';
      document.getElementById('miniNet').innerText = (data.network.rx_kbs + data.network.tx_kbs).toFixed(1) + ' KB/s';
      document.getElementById('miniUptime').innerText = data.system.uptime_str;

      if (data.battery && data.battery.available) {
        document.getElementById('miniBatt').innerText = data.battery.percentage + '%';
      } else {
        document.getElementById('miniBatt').innerText = 'AC연결';
      }

      // 2. Full Dashboard View Update
      if (document.getElementById('dashboardView').style.display === 'block') {
        // CPU Total Card
        document.getElementById('dashCpuTotal').innerText = cpuTot + '%';
        const cpuBar = document.getElementById('dashCpuBar');
        cpuBar.style.width = cpuTot + '%';
        cpuBar.style.backgroundColor = cpuTot > 80 ? 'var(--danger)' : cpuTot > 50 ? 'var(--warning)' : 'var(--accent)';

        // Average freq
        const avgFreq = Math.round(data.cpu.cores.reduce((acc, c) => acc + c.freq_mhz, 0) / 8);
        document.getElementById('dashCpuTotalFreq').innerText = avgFreq + ' MHz avg';
        document.getElementById('dashLoadAvg').innerText = data.system.load_avg.join(', ');
        document.getElementById('dashUptime').innerText = data.system.uptime_str;

        // RAM Card
        const ram = data.memory;
        document.getElementById('dashRamPercent').innerText = ram.ram_percent + '%';
        document.getElementById('dashRamText').innerText = ram.ram_used_mb + ' / ' + ram.ram_total_mb + ' MB';
        document.getElementById('dashRamBar').style.width = ram.ram_percent + '%';
        document.getElementById('dashRamAvail').innerText = (ram.ram_total_mb - ram.ram_used_mb) + ' MB';
        document.getElementById('dashSwapText').innerText = ram.swap_percent + '% (' + ram.swap_used_mb + ' MB)';

        // Network & Storage
        document.getElementById('dashNetRx').innerText = data.network.rx_kbs + ' KB/s';
        document.getElementById('dashNetTx').innerText = data.network.tx_kbs + ' KB/s';
        document.getElementById('dashStoragePct').innerText = data.storage.percent + '%';
        document.getElementById('dashStorageText').innerText = data.storage.free_gb + ' GB 가용';
        document.getElementById('dashStorageBar').style.width = data.storage.percent + '%';
        document.getElementById('dashIfaces').innerText = data.network.active_interfaces.join(', ');

        // Battery
        const batt = data.battery;
        const battNotice = document.getElementById('dashBattNotice');
        const battDetails = document.getElementById('dashBattDetails');
        if (batt && batt.available) {
          battNotice.style.display = 'none';
          battDetails.style.display = 'flex';
          document.getElementById('dashBattPct').innerText = batt.percentage + '%';
          document.getElementById('dashBattStatus').innerText = (batt.status === 'CHARGING' ? '⚡ 고속 충전 중' : '🔋 배터리 방전 중') + ' (' + batt.plugged + ')';
          document.getElementById('dashBattIcon').innerText = batt.status === 'CHARGING' ? '⚡' : '🔋';
          document.getElementById('dashBattPlugged').innerText = batt.plugged;
          document.getElementById('dashBattTemp').innerText = batt.temperature + ' °C';
          document.getElementById('dashBattHealth').innerText = batt.health;
        } else {
          battNotice.style.display = 'block';
          battDetails.style.display = 'none';
          document.getElementById('dashBattPct').innerText = '상시 전원';
          document.getElementById('dashBattStatus').innerText = 'Termux:API 보조 앱 필요';
          document.getElementById('dashBattIcon').innerText = '🔌';
          document.getElementById('dashBattPlugged').innerText = 'AC 상시 공급';
          if (batt && batt.cli_installed && !batt.app_installed) {
            battNotice.innerHTML = '<span>ℹ️ <b>Termux:API 안드로이드 앱 설치 필요</b>: 터미널 패키지(<code>pkg install termux-api</code>)는 정상 설치되었습니다! 스마트폰에 <b>Termux:API 보조 앱(APK)</b>을 설치하시면 배터리 잔량과 온도가 즉시 연동됩니다.</span>';
          } else if (batt && batt.reason) {
            battNotice.innerHTML = '<span>ℹ️ <b>' + batt.reason + '</b></span>';
          }
        }

        // 8 Cores Breakdown Grid
        renderCoresList('littleCoresGrid', data.cpu.cores.slice(0, 4));
        renderCoresList('bigCoresGrid', data.cpu.cores.slice(4, 8));

        // Timestamp
        const d = new Date();
        document.getElementById('lastUpdatedText').innerText = '실시간 수신 중 (' + d.toLocaleTimeString() + ')';
      }
    }

    function renderCoresList(elementId, coresList) {
      const el = document.getElementById(elementId);
      el.innerHTML = '';
      coresList.forEach(core => {
        const div = document.createElement('div');
        div.className = 'core-pill';
        const barColor = core.usage_percent > 80 ? 'var(--danger)' : core.usage_percent > 50 ? 'var(--warning)' : 'var(--accent)';
        div.innerHTML = `
          <div class="core-header">
            <span class="core-name">${core.name}</span>
            <span class="core-freq">${core.freq_mhz > 0 ? core.freq_mhz + ' MHz' : 'Sleep'} · ${core.usage_percent}%</span>
          </div>
          <div class="core-bar-wrap">
            <div class="core-bar" style="width: ${core.usage_percent}%; background-color: ${barColor};"></div>
          </div>
        `;
        el.appendChild(div);
      });
    }

    // Load Post Content
    async function loadPostContent(postId) {
      const contentEl = document.getElementById('articleContent');
      contentEl.innerHTML = '<div class="loading-spinner">글을 불러오는 중입니다...</div>';
      updatePostSwitcher(postId);

      try {
        const res = await fetch('/api/post?id=' + encodeURIComponent(postId));
        if (!res.ok) throw new Error('게시글을 찾을 수 없습니다.');
        const markdown = await res.text();

        marked.setOptions({
          highlight: function(code, lang) {
            const language = hljs.getLanguage(lang) ? lang : 'plaintext';
            return hljs.highlight(code, { language }).value;
          },
          breaks: true,
          gfm: true
        });

        contentEl.innerHTML = marked.parse(markdown);

        // Add copy buttons
        contentEl.querySelectorAll('pre').forEach(pre => {
          const btn = document.createElement('button');
          btn.className = 'copy-btn';
          btn.innerText = 'Copy';
          btn.onclick = () => {
            const code = pre.querySelector('code')?.innerText || pre.innerText;
            navigator.clipboard.writeText(code).then(() => {
              btn.innerText = 'Copied!';
              btn.classList.add('copied');
              setTimeout(() => {
                btn.innerText = 'Copy';
                btn.classList.remove('copied');
              }, 2000);
            });
          };
          pre.appendChild(btn);
        });

        updateFooterNav(postId);
      } catch (err) {
        contentEl.innerHTML = '<div style="color: #ef4444; padding: 20px;">' + err.message + '</div>';
      }
    }

    function updatePostSwitcher(activeId) {
      const switcher = document.getElementById('postSwitcher');
      switcher.innerHTML = '';
      postsData.forEach((post, idx) => {
        const btn = document.createElement('button');
        btn.className = 'post-switch-btn' + (post.id === activeId ? ' active' : '');
        btn.innerText = (idx + 1) + '편';
        btn.onclick = () => { window.location.hash = '#post=' + post.id; };
        switcher.appendChild(btn);
      });
    }

    function updateFooterNav(postId) {
      const navEl = document.getElementById('articleFooterNav');
      navEl.innerHTML = '';
      const idx = postsData.findIndex(p => p.id === postId);
      if (idx === -1) return;

      const prev = idx > 0 ? postsData[idx - 1] : null;
      const next = idx < postsData.length - 1 ? postsData[idx + 1] : null;

      if (prev) {
        const prevCard = document.createElement('div');
        prevCard.className = 'footer-nav-card';
        prevCard.innerHTML = '<div class="footer-nav-label">← 이전 글</div><div class="footer-nav-title">' + prev.title + '</div>';
        prevCard.onclick = () => window.location.hash = '#post=' + prev.id;
        navEl.appendChild(prevCard);
      } else {
        navEl.appendChild(document.createElement('div'));
      }

      if (next) {
        const nextCard = document.createElement('div');
        nextCard.className = 'footer-nav-card';
        nextCard.style.textAlign = 'right';
        nextCard.innerHTML = '<div class="footer-nav-label">다음 글 →</div><div class="footer-nav-title">' + next.title + '</div>';
        nextCard.onclick = () => window.location.hash = '#post=' + next.id;
        navEl.appendChild(nextCard);
      }
    }

    async function loadPosts() {
      try {
        const res = await fetch('/api/posts');
        postsData = await res.json();
        renderPostsList();
        handleHash();
      } catch (err) {
        document.getElementById('postsList').innerHTML = '<div style="color: #ef4444; padding: 20px;">포스트를 불러오는 중 오류가 발생했습니다.</div>';
      }
    }

    function renderPostsList() {
      const container = document.getElementById('postsList');
      container.innerHTML = '';

      postsData.forEach(post => {
        const card = document.createElement('a');
        card.className = 'post-card';
        card.href = '#post=' + post.id;

        const tagsHtml = post.tags.map(t => '<span class="tag">#' + t + '</span>').join('');

        card.innerHTML = `
          <div class="post-card-header">
            <h3 class="post-card-title">${post.title}</h3>
            <span class="post-card-date">${post.date}</span>
          </div>
          <p class="post-card-excerpt">${post.excerpt}</p>
          <div class="post-card-footer">
            <div class="tags">${tagsHtml}</div>
            <span class="read-more">읽기 →</span>
          </div>
        `;
        container.appendChild(card);
      });
    }

    function handleHash() {
      const hash = window.location.hash;
      if (hash === '#dashboard') {
        showDashboard();
      } else if (hash.startsWith('#post=')) {
        const postId = hash.replace('#post=', '');
        showPost(postId);
      } else {
        showHome();
      }
    }

    window.addEventListener('hashchange', handleHash);

    // Initial Execution
    initTheme();
    loadPosts();
  </script>
</body>
</html>
"""

# ---------------------------------------------------------
# HTTP Request Handler
# ---------------------------------------------------------
class BlogRequestHandler(http.server.BaseHTTPRequestHandler):
    # Drop idle or stalled clients instead of holding a worker thread forever
    timeout = 30

    def do_HEAD(self):
        self.do_GET(head_only=True)

    def do_GET(self, head_only=False):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/metrics":
            data = json.dumps(telemetry.get_metrics(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if not head_only:
                self.wfile.write(data)
            return

        elif path == "/api/posts":
            posts = get_all_posts()
            data = json.dumps(posts, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if not head_only:
                self.wfile.write(data)
            return

        elif path == "/api/post":
            post_id = query.get("id", [""])[0]
            if not post_id or "/" in post_id or ".." in post_id:
                self.send_error(400, "Invalid post ID")
                return

            file_path = os.path.join(POSTS_DIR, f"{post_id}.md")
            if not os.path.exists(file_path):
                self.send_error(404, "Post not found")
                return

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if not head_only:
                self.wfile.write(content)
            return

        else:
            # SPA HTML
            content = HTML_TEMPLATE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            if not head_only:
                self.wfile.write(content)

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
        print(f"Blog & Dashboard server running on http://0.0.0.0:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run()
