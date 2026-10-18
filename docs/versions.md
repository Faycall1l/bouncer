# Version notes (T797)

_(Last checked against v0.3.0.)_

This site tracks `main` — the newest code, currently package version
**0.3.0** (`pyproject.toml`, `bouncer --version`). If you're reading an
older release — a `v0.x.y` tag checkout or, once versioned builds ship,
the **version switcher** in the nav sidebar — this page is the bridge:
what the behavior deltas are between 0.1, 0.2, and 0.3, so old docs don't
mislead you. The authoritative list is the
[CHANGELOG](https://github.com/Faycall1l/bouncer/blob/main/CHANGELOG.md);
this page keeps only the deltas that change *what you observe*.

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

## On 0.3.0 (latest)

You're current — nothing above applies. Watch this page and the CHANGELOG
when a versioned build of the site starts serving older docs through the
switcher; each switcher entry will resolve to the delta section matching
its version.

Terms used here are defined in the [Glossary](glossary.md).
