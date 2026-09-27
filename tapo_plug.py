#!/root/.local/share/tapo-venv/bin/python
"""Switch the Tapo P100 plug that feeds the phone's charger: status | on | off.

termux/battery-watch.sh calls this through proot-distro to keep the battery between 40%
and 80%. Prints the plug's state afterwards ("on" or "off") and exits 0, or prints the
reason to stderr and exits 1. Never prints the credentials.

Files, all under /root/.config/tapo/ (outside git):
  credentials   the Tapo account: e-mail on line 1, password on line 2 (chmod 600)
  host          the plug's LAN address; rewritten when the plug turns up somewhere else

Why it looks like this (measured 2026-09-27 against a P100 hw 2.0, fw 1.2.5):
  - The plug answers KLAP on port 80 but drops about 15% of packets even at -52 dBm (the
    router drops 1% from the same phone), so any single request can hang. Each request
    gets a short timeout and the whole exchange is retried; one status read took from
    0.1 s to 39 s over eight runs, and all eight succeeded.
  - python-kasa's Device.connect() negotiates every component first, several requests
    that each risk a loss. Only the three that matter are sent here: the two handshakes
    and one query.
  - Connections are not reused (force_close): the plug closes them without telling the
    client, and the next request on a reused one never returns. The cookie jar has to
    accept cookies from a bare IP address or handshake2 is answered with 400.
Needs python-kasa (0.10.2) in /root/.local/share/tapo-venv, a venv of Ubuntu's python3.
"""
import asyncio
import os
import sys

import aiohttp
from kasa import Credentials, DeviceConfig, DeviceConnectionParameters, DeviceEncryptionType, DeviceFamily, Discover
from kasa.protocols import SmartProtocol
from kasa.transports import KlapTransportV2

CONF = "/root/.config/tapo"
TIMEOUT = 12      # seconds per HTTP request
TRIES = 4         # whole exchanges (handshake1, handshake2, query) per address


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def credentials():
    try:
        with open(os.path.join(CONF, "credentials"), encoding="utf-8") as f:
            lines = [line.strip() for line in f.read().splitlines()]
    except OSError as e:
        fail(f"cannot read {CONF}/credentials ({e.strerror})")
    if len(lines) < 2 or not lines[0] or not lines[1]:
        fail(f"{CONF}/credentials needs the e-mail on line 1 and the password on line 2")
    return Credentials(lines[0], lines[1])


def saved_host():
    try:
        with open(os.path.join(CONF, "host"), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def save_host(host):
    path = os.path.join(CONF, "host")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(host + "\n")
    os.replace(path + ".tmp", path)


async def exchange(host, creds, request):
    """One KLAP session on fresh connections: handshake1, handshake2, then the request."""
    jar = aiohttp.CookieJar(unsafe=True, quote_cookie=False)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(force_close=True), cookie_jar=jar) as http:
        config = DeviceConfig(
            host=host, credentials=creds, timeout=TIMEOUT, http_client=http,
            connection_type=DeviceConnectionParameters(
                DeviceFamily.SmartTapoPlug, DeviceEncryptionType.Klap, login_version=2, http_port=80))
        protocol = SmartProtocol(transport=KlapTransportV2(config=config))
        try:
            return await protocol.query(request, retry_count=0)
        finally:
            await protocol.close()


async def with_retries(host, creds, request):
    last = None
    for _ in range(TRIES):
        try:
            return await asyncio.wait_for(exchange(host, creds, request), TIMEOUT * 3 + 5)
        except Exception as e:  # timeouts and transport errors alike: start a new session
            last = e
    raise last


async def find_plug():
    """The plug's address from a UDP broadcast, if exactly one Tapo plug answers."""
    found = await Discover.discover(timeout=6, discovery_timeout=6)
    plugs = [ip for ip, dev in found.items()
             if (getattr(dev, "_discovery_info", None) or {}).get("result", {}).get("device_type") == "SMART.TAPOPLUG"]
    return plugs[0] if len(plugs) == 1 else None


async def run(command):
    creds = credentials()
    if command == "status":
        request = "get_device_info"
    else:
        request = {"set_device_info": {"device_on": command == "on"}}

    host = saved_host()
    tried = []
    for attempt in range(2):
        if host is None or attempt == 1:
            moved = await find_plug()
            if moved is None or moved in tried:
                break
            host = moved
        tried.append(host)
        try:
            result = await with_retries(host, creds, request)
        except Exception as e:
            last = e
            continue
        if host != saved_host():
            save_host(host)
        if command != "status":
            # Read it back rather than trust the acknowledgement. The plug did accept the
            # command (an error code would have raised), so when only the read-back gets
            # lost in the packet loss, say so and let the caller check the phone itself.
            try:
                result = await with_retries(host, creds, "get_device_info")
            except Exception:
                return f"{command} (unconfirmed)"
        state = "on" if result["get_device_info"]["device_on"] else "off"
        if command != "status" and state != command:
            fail(f"asked for {command}, the plug reports {state}")
        return state
    fail(f"no answer from the plug at {', '.join(tried) or 'an unknown address'}"
         f" ({type(last).__name__ if tried else 'not found on the network'})")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("status", "on", "off"):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        print("usage: tapo_plug.py status|on|off", file=sys.stderr)
        sys.exit(2)
    print(asyncio.run(run(sys.argv[1])))


if __name__ == "__main__":
    main()
