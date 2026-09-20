# 3. A public address without buying a domain

<b>English</b> · [한국어](03-public-address.ko.md)

[← 2. Web server](02-web-server.md) · Next: [4. Staying up](04-always-on.md)

---

The phone has a private address on whatever network it happens to be on. Three
requirements decided which way out to take:

1. **Do not buy a domain.**
2. **Do not touch the router.**
3. **Keep the same address when the phone moves** — home Wi-Fi, café Wi-Fi, LTE.

Three approaches were tried in that order. Only one satisfied all three.

## 3.1 Why port forwarding is usually not the answer

The obvious approach is dynamic DNS plus a forwarded port. It failed in an
instructive way: an external request to the new DuckDNS name returned somebody
else's web server.

```
$ curl -I http://<my-subdomain>.duckdns.org
HTTP/1.1 200 OK
Server: Microsoft-IIS/10.0
```

DuckDNS was pointing at the right public IP. Port 80 on that IP had been forwarded
to a desktop PC years earlier. **A domain name gets a request to your front door;
the router decides which room it goes to.**

Adding a rule for port 8080 would have worked, and still fails the requirements:

- it needs administrator access to the router;
- it stops working the moment the phone leaves the house;
- you own the HTTPS certificate problem yourself.

And on many mobile and apartment networks there is nothing to forward. If your
router's WAN address is inside `100.64.0.0/10`, you are behind carrier-grade NAT and
no port can be opened at all. Check before you plan around it:

```bash
curl -s https://api.ipify.org          # what the internet sees
ip route get 1.1.1.1                   # what your router gave you
```

Different answers mean NAT, which is normal. A WAN address in `100.64.0.0/10` means
CGNAT, and only a tunnel will get you in.

## 3.2 Cloudflare Tunnel — excellent, if you own a domain

A tunnel dials out from the phone, so there is nothing to forward and nothing to
open. Cloudflare's version comes in two shapes.

**Quick Tunnel** needs no account and is the fastest way to show someone a page:

```bash
cloudflared tunnel --url http://localhost:8080
```

It prints a random `*.trycloudflare.com` address that changes on every restart, which
makes it a demo tool rather than a home for a blog.

**Named Tunnel** keeps a stable name. Create the tunnel in the dashboard and run it
with a token, rather than using `cloudflared tunnel login` — browser-based login on a
phone tends to expire mid-flow, and when it succeeds it leaves `cert.pem` in
Android's Downloads folder for you to move into the container by hand.

```bash
cloudflared tunnel run --token eyJh...
```

Connection quality was never the problem. It passed every preflight check and
attached to the nearest edge over QUIC:

```
INF  SUMMARY: Environment is healthy. cloudflared will use 'quic' as primary protocol.
INF  Registered tunnel connection location=icn01 protocol=quic
```

The wall is the **Public Hostname** step. Attaching a public address to a Named
Tunnel requires a domain **you own and have delegated to Cloudflare's nameservers**.
A free subdomain — `*.duckdns.org`, `*.ts.net` — cannot be delegated, so it cannot be
registered. That is requirement 1, failed.

> **Delete the configuration you stopped using.** Days after switching away, the
> Cloudflare dashboard still listed a hostname pointing at the ngrok domain — a
> tunnel aimed at an address it does not own, which cannot work and only confuses
> the next person reading the logs.

## 3.3 ngrok free static domain — what this repository uses

A free ngrok account includes one permanent domain. The whole configuration is a
token:

```yaml
# ~/.config/ngrok/ngrok.yml
version: "3"
agent:
  authtoken: <your token>
```

```bash
/usr/local/bin/ngrok http 8080 \
    --url https://<your-domain>.ngrok-free.dev \
    --pooling-enabled \
    --log stdout
```

Zero for the domain, zero router changes, and the same address on any network.

### `--pooling-enabled` is not optional here

Restart the agent quickly and ngrok refuses:

```
failed to start tunnel: The endpoint 'https://<your-domain>.ngrok-free.dev'
is already online. ... ERR_NGROK_334
```

The edge has not finished retiring the previous session when the new agent claims the
same address. `--pooling-enabled` lets the two sessions coexist briefly and hand over.
Any supervisor that restarts the process on a crash will hit this within a day, so
treat the flag as mandatory.

### The price of the free plan

A browser visiting a free ngrok domain gets an interstitial warning page first. The
same URL behaves differently depending on who asks:

```bash
$ curl -s -o /dev/null -w "%{http_code} %{size_download}\n" https://<your-domain>.ngrok-free.dev/
200 39813        # the blog

$ curl -s -A "Mozilla/5.0 (Linux; Android 14) ... Chrome/140.0" ... 
200 2902         # "You are about to visit ..."  (ERR_NGROK_6024)
```

So a human clicks one extra button; `curl`, RSS readers and API calls are unaffected.
Sending the `ngrok-skip-browser-warning` header skips it, which is exactly the
non-standard header that triggers the CORS preflight described in
[`02-web-server.md`](02-web-server.md).

## 3.4 The comparison

| | Cloudflare Named Tunnel | DuckDNS + port forwarding | ngrok free static domain |
|:---|:---|:---|:---|
| own domain | **required** | not needed | not needed |
| router access | not needed | **required** | not needed |
| works behind CGNAT | yes | **no** | yes |
| HTTPS | automatic | you issue and renew it | automatic |
| works away from home | yes | **no** | yes |
| visitor experience | clean | clean | **one warning page** |
| difficulty | medium (DNS delegation) | medium (router admin) | low |

If you already own a domain, Cloudflare is the cleanest answer. If you have nothing
and want a fixed address today, it is ngrok.

## 3.5 Keep the private services off this path

The public tunnel carries the blog and nothing else. The document viewer and
code-server are never exposed through it — not even with a password. They are bound
to a Tailscale address instead, which is [`05-private-access.md`](05-private-access.md).

Next: keep it running unattended → [4. Staying up](04-always-on.md)
