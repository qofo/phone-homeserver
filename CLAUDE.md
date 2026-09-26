# Working on this repository

This repository is two things at once: a **bilingual guide** to building a server on
an Android phone, and the **actual code** that phone runs. The rules below exist
because breaking either half is easy and not obvious from a diff.

## Every document is a pair

`README.md` is English and is what GitHub renders; `README.ko.md` is the Korean
mirror. Every page under `docs/` exists twice, as `<name>.md` and `<name>.ko.md`,
including `docs/images/README.md` and `docs/reference/README.md`.

- **Change both, or change neither.** A fix applied to one language and not the other
  is worse than no fix, because nothing marks the other copy as stale.
- Keep the reciprocal language link directly under each H1, and the previous/next
  navigation line under that.
- Korean pages link to Korean pages (`04-always-on.ko.md`), English to English.
- Korean prose uses 해라체, matching the blog. Tables, code blocks, environment
  variable names and link targets stay identical across both languages.

The layout follows the convention of comparable projects — English default, a
`README.<lang>.md` beside it, `<name>.md` / `<name>.ko.md` pairs — rather than
anything invented here. Keep it that way.

## Images

- **Diagrams and terminal transcripts are generated.** Edit
  `docs/images/make_assets.py` and re-run it; never hand-edit an SVG, it will be
  overwritten. `python3 docs/images/make_assets.py`
- The SVGs carry their own light background on purpose, so they stay readable in
  GitHub's dark theme. Do not make them transparent.
- **Screenshots must be redacted before they are committed**, with opaque bars.
  Blur and pixelation of text can both be reversed. This phone has no image
  libraries, so use `/root/redact_screenshot.py` (standard library only; it reads
  PNG and baseline JPEG and writes PNG):

  ```bash
  python3 /root/redact_screenshot.py shot.png --scan 0,0,1080,400   # find coordinates
  python3 /root/redact_screenshot.py shot.png out.png --box 214,104,800,160
  ```

- What to cover: the tailnet and MagicDNS name, the home public IP (v4 **and** v6),
  the LAN subnet, account addresses and real names, private document titles,
  passwords and key material, and the carrier name in the Android status bar.
- `docs/images/README.md` lists the screenshots still wanted, with the filename to
  use and where each one goes. Update that list when one arrives.
- Flat-colour screenshots (terminals, notification shades) are smaller as PNG than
  as the phone's JPEG. Convert rather than commit a large JPEG.

## `docs/reference/` is a one-way copy

Those four documents are the server's own working notes, **Korean only**, copied
from `/root/docs/*.md` with private addresses replaced by examples. Filenames map one to
one onto the originals, which is why they were not renamed to `.ko.md`.

Copies flow **from the phone into this repository, never back**. Editing a copy here
and expecting `/root` to pick it up silently loses the change.

## Code files mirror `/root`

`serve_blog.py`, `publish_blog.sh`, `start_services.sh`, `private_docs.sh`,
`private_docs_server.py`, `measure_downtime.py`, `termux/` and `tests/` must match
the running files in `/root`. Fix `/root` first, then copy here.

**One deliberate exception:** `code_server.sh` keeps `MAGIC_DNS=""` in this copy.
The real MagicDNS name lives only in `/root`.

## Before committing

```bash
python3 tests/test_serve_blog.py        # 35 tests
python3 tests/test_private_docs.py      # 47 security tests
git log --all -p | grep -nE '182\.214|duckdns\.org|192\.168\.219|100\.100\.134|taileee507|authtoken|PRIVATE KEY'
```

Guide text uses placeholders — `<your-domain>.ngrok-free.dev`, `100.x.y.z`,
`192.168.0.42`, `203.0.113.10` — even though the scripts contain the real ngrok
domain, which is already public because the blog is served at it.

Commits here use `67111752+qofo@users.noreply.github.com`, set as `user.email` local
to this repository. Do not commit with the personal address.

**Ask before pushing.** This repository is public and a push cannot be undone.
