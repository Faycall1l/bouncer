# Release notes: v0.3.0 (T627, DRAFT)

200 boxes (T431–T630) across persistence, router pools, multitenancy,
multilingual wiring, reliability, CLI, demo, eval/data, docs, and the 0.3.0
release itself. Still no model changes — same zero-shot behavior, far better
operations around it.

Highlights for users:

* **Pools**: routers are cached LRU-by-kwargs (`BOUNCER_POOL_MAX`,
  `BOUNCER_DEVICE`). Pin a checkpoint per request: `model=` on the API,
  `bouncer check --model`, demo dropdown. 5.4× faster steady-state vs
  rebuild-per-request (bench_pool), with the thrash case documented honestly.
* **Multitenancy**: `preset=` anywhere `rules=` is accepted (XOR — `E_PRESET`
  on mixing), `GET /presets/{name}`, `BOUNCER_DEFAULT_PRESET`, `bouncer presets`
  and `pack init FILE` for editing a pack before shipping it.
* **Reliability**: circuit breaker (`breaker_n`/`breaker_cool_s`, half-open
  probe, `cause=breaker-open` — open never allows), per-request `timeout_s`,
  `GET /ready` for load balancers, `BOUNCER_BREAKER=off` escape hatch.
* **Persistence**: `bouncer snapshot save/load`, `export --format json/
  --limit/--action`, `review --since/--rule/--prune`; runtime files all
  gitignored (test-enforced), audit still stores hashes only.
* **Multilingual**: `E_LANG` validation, `detect_script()`, 12-row i18n
  fixture set + CI-safe wiring eval, preset→lang autofill, `watch --json-in`
  per-line hints.
* **CLI**: 11 subcommands now include `models`, `presets`, `pack init`,
  `snapshot`, plus `--config/--user/--action/--lang` plumbing on
  `check`/`watch`.
* Docs: README operational sections, api.md reliability fields, architecture
  pool/breaker diagram, new SECURITY.md, glossary + FAQ + gates additions.

Bugs found by the release tests themselves:

* `serve --key-file` wrote `BOUNCER_API_KEY` while the server reads
  `BOUNCER_KEY` — the flag was a silent no-op (fixed by T609's env-var
  docs-consistency check).

Upgrade notes:

* New required-or-default behavior: requests to the API without `rules` or
  `preset` still 422 `E_PRESET` (set `BOUNCER_DEFAULT_PRESET` to soften).
* `__version__` / package version: `0.3.0`.
* `review.list_queue()` gained `since`/`rule` kwargs (back-compatible).
* `cli.build_parser()` extracted (parser construction testable standalone).
* 188 tests green without weights; `ruff check .` green.

Tag: `v0.3.0`.
