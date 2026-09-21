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

## In the repository already

| File | Shows | Used in |
|:---|:---|:---|
| `shot-blog-home.png` | the blog over its permanent public address | README, "What you get" |
| `shot-dashboard.png` | the live dashboard: per-core usage, memory, swap, battery, temperature | `06-operations` §6.3 |
| `shot-battery-alert.jpg` | the 80 % unplug notification, beside Termux's wake lock and Tailscale's connection | `06-operations` §6.1 |
| `shot-jobs.jpg` | `termux-job-scheduler -p` listing all four persisted jobs | `04-always-on` §4.3 |
| `shot-ngrok-warning.png` | ngrok's interstitial warning page | `03-public-address` §3.3 |
| `shot-tailscale-app.png` | the Tailscale app with the phone connected — *redacted* | `05-private-access` §5.2 |
| `shot-docs-viewer.png` | the document viewer's index — *redacted* | `05-private-access` §5.4 |

## Still wanted: photographs

Only the first is worth making a point of. It is the one image that shows the premise
is real — everything else in this repository would look the same on a rented VPS — and
GitHub uses the README's first image as the link preview when the repository is shared.

| Filename | What it should show | Goes in |
|:---|:---|:---|
| `photo-phone-server.jpg` | the phone doing the job: plugged in, propped up, screen on the dashboard or a Termux session. Landscape, taken straight on | README, under the title |
| `photo-case-off.jpg` | *optional* — the phone with its back cover removed, which is the cooling fix | `06-operations` §6.2 |

## Still wanted: screenshots

| Filename | What it should show | Goes in |
|:---|:---|:---|
| `shot-termux-ubuntu.png` | Termux right after `proot-distro login ubuntu`, with `cat /etc/os-release` output on screen. An empty prompt does not show anything | `01-install` §1.4 |
| `shot-code-server.png` | code-server with a file actually open and the terminal panel showing output — not the loading skeleton | `05-private-access` §5.7 |
| `shot-android-battery-opt.png` | Android's battery settings with optimisation switched **off** for Termux | `01-install` §1.1 |

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

Crop rather than blur where you can; a blur that is too light can be undone, and so is
pixelated text. Solid bars are the only redaction that cannot be reversed.

Three of the images here were redacted that way before being committed: the ngrok page
carried the phone's public IPv6 address, the Tailscale screen carried an account
address, a real name and three device addresses, and the viewer's index carried the
titles of an unreleased private project along with the real tailnet address.

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
