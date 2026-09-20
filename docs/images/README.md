# Images

<b>English</b> · [한국어](README.ko.md)

Two kinds of asset live here.

**Generated diagrams and terminal transcripts** — the `.svg` files, all produced by
[`make_assets.py`](make_assets.py). They carry their own background so they stay
readable in GitHub's light and dark themes, and they are text, so a diff shows what
changed. Edit the script, not the SVG:

```bash
python3 docs/images/make_assets.py
```

| File | Used in |
|:---|:---|
| `architecture.svg` | README — the layer stack and the three trust zones |
| `boot-chain.svg` | README, `04-always-on` — triggers, launcher, supervisor |
| `network-paths.svg` | README, `05-private-access` — public path vs tailnet-only path |
| `publish-pipeline.svg` | `02-web-server` — one source, two servers |
| `health-check.svg` | `04-always-on` — probing instead of `pgrep` |
| `term-install.svg` | README, `01-install` — Termux to an Ubuntu shell |
| `term-status.svg` | README — the three `status` commands |
| `term-specs.svg` | README — what the hardware actually provides |
| `term-verify.svg` | `06-operations` — proving it works from outside |

**Photographs and screenshots** — these cannot be generated, and the list below is
what the documentation has room for. Each row gives the filename to use, so dropping
the file in this directory and adding the one-line snippet is all it takes.

## Wanted: photographs

| Filename | What it should show | Goes in |
|:---|:---|:---|
| `photo-phone-server.jpg` | the phone doing the job: plugged in, propped up, screen on the dashboard or a Termux session. Landscape, taken straight on. **This is the image at the top of the README.** | README, under the title |
| `photo-setup-wide.jpg` | the wider arrangement — charger, cable, wherever it lives. Shows how little space and equipment this takes | README, "Why an old phone" |
| `photo-case-off.jpg` | the phone with its back cover removed, which is the cooling fix | `06-operations` §6.2 |

## Wanted: screenshots on the phone

| Filename | What it should show | Goes in |
|:---|:---|:---|
| `shot-termux-ubuntu.png` | Termux right after `proot-distro login ubuntu`, with `cat /etc/os-release` visible | `01-install` §1.4 |
| `shot-android-battery-opt.png` | Android's battery settings with optimisation switched **off** for Termux | `01-install` §1.1 |
| `shot-battery-alert.png` | the Termux:API notification asking you to unplug at 80 % | `06-operations` §6.1 |
| `shot-tailscale-app.png` | the Tailscale app showing this phone connected, with its `100.x` address | `05-private-access` §5.2 |
| `shot-jobs.png` | `termux-job-scheduler -p` output, listing the pending jobs | `04-always-on` §4.3 |

## Wanted: screenshots from a laptop browser

| Filename | What it should show | Goes in |
|:---|:---|:---|
| `shot-blog-home.png` | the blog, loaded from the phone through the public address, with the address bar visible | README, "What you get" |
| `shot-dashboard.png` | the live hardware dashboard with real numbers | `06-operations` §6.3 |
| `shot-docs-viewer.png` | the private document viewer, with a document open | `05-private-access` §5.4 |
| `shot-code-server.png` | code-server in the browser, with the padlock and the `100.x:8443` address visible | `05-private-access` §5.7 |
| `shot-ngrok-warning.png` | ngrok's "You are about to visit …" interstitial | `03-public-address` §3.3 |

## Before you commit a screenshot

This repository is public, and a screenshot leaks more than a code block does. Check
each image for:

- **the tailnet name and MagicDNS name** — `something.tailnet-name.ts.net`. Mask it as
  `<this-device>.<tailnet>.ts.net`, the same way the documentation does.
- **the home public IP, the LAN subnet, and the DuckDNS or router hostname.** The
  documentation uses `203.0.113.10`, `192.168.0.42` and `100.x.y.z` as stand-ins.
- **the code-server password**, and any certificate private key.
- **private document titles** in the viewer's index, and anything readable inside an
  open document.
- **the Android status bar** — carrier name, notifications, Wi-Fi SSID.
- **Google or GitHub account names** in a browser's profile chip.

Crop rather than blur where you can; a blur that is too light can be undone.

## Adding one

Save the file here under the name from the table, then paste the matching line into the
place named in the "Goes in" column — and the same line, with the Korean caption, into
the `.ko.md` page beside it:

```markdown
![The phone, plugged in and serving](docs/images/photo-phone-server.jpg)   <!-- from README.md -->
![The phone, plugged in and serving](images/photo-phone-server.jpg)        <!-- from a docs/ page -->
```

Keep photographs under about 400 KB and screenshots under about 250 KB — this
repository is cloned onto the phone that serves it. Resizing to 1600 px on the long
edge is usually enough:

```bash
# on a machine that has ImageMagick
magick photo.jpg -resize 1600x -quality 82 photo-phone-server.jpg
```
