# Reference documents

<b>English</b> · [한국어](README.ko.md)

These four are the server's own working documents, copied from the phone with private
addresses replaced by examples. **They are in Korean only** — they are internal
records, not part of the bilingual guide, and they go into far more detail than a guide
should.

| Document | What it is |
|:---|:---|
| [`SERVER_ENVIRONMENT_SPEC.md`](SERVER_ENVIRONMENT_SPEC.md) | the full environment specification and handoff guide: hardware, the `proot` layer, every path and port, and a command cheat sheet |
| [`CODE_SERVER_GUIDE.md`](CODE_SERVER_GUIDE.md) | how to use code-server on this phone, including why Remote-SSH cannot work |
| [`HUGO_MIGRATION_PLAN.md`](HUGO_MIGRATION_PLAN.md) | the plan for moving the blog to Hugo, with a table of everything that turned out differently and why |
| [`STRESS_TEST_SPEC.md`](STRESS_TEST_SPEC.md) | the load-test specification: staged load, cooldowns, and the client tools that drive it |

The originals live in `/root` on the phone and are the source of truth. Copies flow in
one direction only — from the phone into this repository — and the private addresses in
them are replaced on the way (`192.168.0.42`, `100.x.y.z`, `203.0.113.10`,
`<this-device>.<tailnet>.ts.net`). Never edit a copy here and expect the phone to pick
it up.

For the guide itself, in both languages, see [`../`](..) and the table in the
[README](../../README.md).
