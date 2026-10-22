# Version notes (T797)

_(Last checked against v0.5.0.)_

This site tracks `main` — the newest code, currently package version
**0.5.0** (`pyproject.toml`, `bouncer --version`). If you're reading an
older release — a `v0.x.y` tag checkout, or a versioned snapshot at
`/<tag>/` on this site — this page is the bridge: what the behavior
deltas are between the 0.x releases, so old docs don't
mislead you. (The 0.5.0 notes live in the CHANGELOG; this page's 0.5.0 delta
section comes at T1016 — until then, treat 0.4.0 as the last
*documented* delta.) The authoritative list is the
[CHANGELOG](https://github.com/Faycall1l/bouncer/blob/main/CHANGELOG.md);
this page keeps only the deltas that change *what you observe*.

## Where each version resolves (T993)

Every versioned snapshot on this site is built from that tag's own
`docs/` tree by the docs workflow — one directory per tag, served
beside the root site; the site and its snapshots publish together,
behind the same `DOCS_DEPLOY` flag. Each version a reader can be on
resolves to its delta section here:

| You are reading docs as of | Start here | Versioned snapshot |
| --- | --- | --- |
| `v0.4.0` | [On 0.4.0 (latest)](#on-040-latest) | yes — `/v0.4.0/` |
| `v0.3.0` | [Coming from 0.3.x](#coming-from-03x) | no — docs didn't exist yet |
| `v0.2.0` | [Coming from 0.2.0](#coming-from-020) | no — docs didn't exist yet |
| `v0.1.0`, `v0.1.1`, `v0.1.2` | [Coming from 0.1.x](#coming-from-01x) | no — docs didn't exist yet |

A tag from before `v0.4.0` can't have a snapshot — there is nothing to
build — so the versioned build names it and moves on rather than
serving a broken half-site. On one of those checkouts, read this page
here on `main`. A new tag that carries docs gets a snapshot directory
from the workflow and a row in this table by hand, resolving to its
own "Coming from ..." section once the next release lands one.

## Coming from 0.1.x

* **Stale-verdict bug fixed in 0.1.2** — the cache key now covers every
  decision input (both thresholds, lang, context, quiet-state). On 0.1.0/0.1.1
  the same message under different settings could return a cached verdict from
  the old settings.
* **Split gates completed by 0.2.0** — `allow_threshold`/`delete_threshold`
  on `/predict` and `/batch` existed from 0.1.2, but the `--allow-threshold` /
  `--delete-threshold` flags on `check`/`watch` and the two demo sliders only
  arrived with 0.2.0. Single `--threshold` still sets both everywhere.
* **Result objects gained keys in 0.2.0** (`cause`, `margin`, `thresholds`,
  `lang`, `quiet_active`, explicit `cached`) — additive only; nothing was
  removed or renamed.
* **Errors became structured in 0.2.0** — 422/500 bodies are
  `{"detail": {"code": "E_*", "message": ...}}`, request caps are enforced
  (batch 32, body 1 MB, context 20×8000), and `/metrics` + `/stats` growth
  landed. Old docs showing bare-string errors are pre-0.2.

## Coming from 0.2.0

* **`preset` vs `rules` is an XOR in 0.3.0** — send exactly one;
  mixing them is `422 E_PRESET` (it used to be accepted).
* **Model pinning and routing exist from 0.3.0** — `model=` on the API,
  `bouncer check --model`, the demo dropdown; `GET /presets/{name}` and
  `bouncer presets` / `pack init FILE` are new commands.
* **Circuit breaker from 0.3.0** — `cause: "breaker-open"` means the breaker
  tripped and **open never allows** (fail-closed); `timeout_s` (0.5–60 s),
  `GET /ready` (model-aware readiness), and the `BOUNCER_BREAKER=off`
  escape hatch are all new knobs.
* **Persistence from 0.3.0** — `bouncer snapshot save/load`,
  `export --format/--limit/--action`, `review --since/--rule/--prune`.
  Snapshots are written `0600` and refuse schema mismatches with
  `E_SNAPSHOT`.
* **Language handling from 0.3.0** — `E_LANG` validation, `detect_script()`,
  preset→lang autofill, per-line `lang` in `watch --json-in`. Non-latin
  scripts (ar/zh/ru/fa/ur/he) pin the `multilingual` checkpoint.

## Coming from 0.3.x

* **Auth rotation in 0.4.0** — `BOUNCER_KEY_OLD` keeps the outgoing key
  accepted (constant-time compare) while `BOUNCER_KEY` becomes current:
  rotate without a restart window. Keys under 16 chars warn at boot.
* **Proxy-pinned rate keys in 0.4.0** — `BOUNCER_TRUSTED_PROXY` names the
  proxy peer IPs whose `X-Forwarded-For` may set the rate-limit key;
  everyone else is keyed by peer IP.
* **Forwarder SSRF pin in 0.4.0** — the webhook forwarder only speaks
  http(s), and once `BOUNCER_FORWARD_ALLOW` is set, only its exact hosts
  (case-insensitive, no wildcards) — anything else is `E_WEBHOOK`.
* **Destructive chat actions became opt-in in 0.4.0** — Telegram deletes,
  Matrix redactions and Mattermost/Zulip deletes fire only with
  `BOUNCER_TG_DELETE` / `BOUNCER_MX_REDACT` / `BOUNCER_MM_DELETE` /
  `BOUNCER_ZL_DELETE`; `BOUNCER_DRY_RUN=1` prints every action instead of
  posting.
* **`/v1/systemone` exists from 0.4.0** — a raw single-shot passthrough
  route with the same bounded inputs; oversized `state`/`questions` keys
  are `422 E_STATE`.
* **Review queue hardened in 0.4.0** — written `0600`, raw messages
  bounded per line and on disk.
* **Eval gate runner in 0.4.0** — `eval/gate.py` pass/fail over report
  JSONs: threshold flags, deltas against a baseline report, and a
  docs-drift check against the BENCHMARKS known-numbers table.

## On 0.4.0 (latest)

You're current — nothing above applies. This same page is what the
`/v0.4.0/` snapshot serves, so the table at the top lands you in the
right place either way. When the next release tags, it joins that
table with its own delta section.

Terms used here are defined in the [Glossary](glossary.md).
