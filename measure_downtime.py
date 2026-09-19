#!/usr/bin/env python3
"""
measure_downtime.py - Service Availability & Downtime Measurement Tool

Monitors service reachability (HTTP/HTTPS) with high precision (sub-second polling).
Detects when the service goes offline (due to restart, reboot, crash, or network loss),
measures the exact unavailable duration down to the millisecond, and logs the result.

Usage:
  # Monitor the public ngrok endpoint continuously:
  python3 measure_downtime.py

  # Monitor local blog server:
  python3 measure_downtime.py --local

  # Wait for one downtime event (e.g. manual restart/reboot), measure it, and exit:
  python3 measure_downtime.py --once

  # Custom interval & URL:
  python3 measure_downtime.py --url https://daringly-marrow-penny.ngrok-free.dev --interval 0.2
"""

import sys
import os
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime

DEFAULT_PUBLIC_URL = "https://daringly-marrow-penny.ngrok-free.dev"
DEFAULT_LOCAL_URL = "http://127.0.0.1:8080"
DOWNTIME_LOG = "/root/downtime.log"

def check_endpoint(url, timeout=2.0):
    """
    Returns (is_online, status_code_or_error_str)
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DowntimeMonitor/1.0", "ngrok-skip-browser-warning": "true"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            if code == 200:
                return True, "HTTP 200"
            return False, f"HTTP {code}"
    except urllib.error.HTTPError as e:
        # ngrok 404 with error code or other HTTP errors
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"URLError: {e.reason}"
    except Exception as e:
        return False, f"Error: {e}"

def format_timestamp(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def main():
    parser = argparse.ArgumentParser(description="Service Downtime Measurement Tool")
    parser.add_argument("--url", default=None, help=f"Target URL (default: {DEFAULT_PUBLIC_URL})")
    parser.add_argument("--local", action="store_true", help=f"Target local server ({DEFAULT_LOCAL_URL})")
    parser.add_argument("--interval", type=float, default=0.5, help="Polling interval in seconds (default: 0.5s)")
    parser.add_argument("--timeout", type=float, default=2.0, help="HTTP request timeout in seconds (default: 2.0s)")
    parser.add_argument("--once", action="store_true", help="Exit after capturing a single downtime -> recovery cycle")
    parser.add_argument("--log", default=DOWNTIME_LOG, help="File to append downtime records to")

    args = parser.parse_args()

    target_url = args.url
    if not target_url:
        target_url = DEFAULT_LOCAL_URL if args.local else DEFAULT_PUBLIC_URL

    print("=" * 65)
    print("  Service Downtime & Availability Monitor")
    print(f"  Target URL: {target_url}")
    print(f"  Interval:   {args.interval}s (Timeout: {args.timeout}s)")
    print(f"  Mode:       {'Single Cycle (--once)' if args.once else 'Continuous'}")
    print(f"  Log File:   {args.log}")
    print("=" * 65)

    # Initial check
    initial_online, info = check_endpoint(target_url, timeout=args.timeout)
    state = "ONLINE" if initial_online else "OFFLINE"
    t_now = time.time()
    print(f"[{format_timestamp(t_now)}] Initial Status: [{state}] ({info})")

    downtime_start = t_now if not initial_online else None
    cycle_started = not initial_online

    try:
        while True:
            time.sleep(args.interval)
            t_check = time.time()
            is_online, info = check_endpoint(target_url, timeout=args.timeout)

            if state == "ONLINE" and not is_online:
                # Transition: ONLINE -> OFFLINE
                state = "OFFLINE"
                downtime_start = t_check
                cycle_started = True
                print(f"\n[{format_timestamp(t_check)}] ❌ [SERVICE DOWN] Outage started! Reason: {info}")
                sys.stdout.flush()

            elif state == "OFFLINE" and is_online:
                # Transition: OFFLINE -> ONLINE
                state = "ONLINE"
                downtime_end = t_check
                duration = downtime_end - (downtime_start or t_check)
                start_str = format_timestamp(downtime_start or t_check)
                end_str = format_timestamp(downtime_end)

                log_entry = (
                    f"[{end_str}] [DOWNTIME] Service was unavailable for "
                    f"{duration:.2f}s (probe_detected, from {start_str} to {end_str})"
                )
                print(f"\n[{end_str}] ✅ [SERVICE RECOVERED] Back online! ({info})")
                print(f"  >> Total Downtime: {duration:.2f} seconds ({duration:.1f}s)")
                print(f"  >> Outage Window: {start_str} ~ {end_str}")
                sys.stdout.flush()

                # Write to log file
                try:
                    with open(args.log, "a", encoding="utf-8") as f:
                        f.write(log_entry + "\n")
                    print(f"  >> Recorded to {args.log}")
                except Exception as e:
                    print(f"  >> Failed to write to {args.log}: {e}")

                if args.once and cycle_started:
                    print("\nSingle measurement completed. Exiting.")
                    return 0

                downtime_start = None

            else:
                # Ongoing state
                if state == "OFFLINE" and downtime_start:
                    elapsed = t_check - downtime_start
                    print(f"\r  ... Outage in progress: {elapsed:.1f}s elapsed (latest: {info})   ", end="", flush=True)

    except KeyboardInterrupt:
        print("\nMonitor interrupted by user.")
        if state == "OFFLINE" and downtime_start:
            elapsed = time.time() - downtime_start
            print(f"Service was still OFFLINE when stopped. Unfinished outage duration: {elapsed:.2f}s")
        return 0

if __name__ == "__main__":
    sys.exit(main())
