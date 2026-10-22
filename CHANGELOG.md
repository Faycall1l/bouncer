# Changelog (T146/T168/T601)

## Unreleased

## 0.5.0 — 2026-10-22 (T1016)

Draft: T819's release sweep demands this dated heading the moment
pyproject reads 0.5.0, so the T1011 bump creates it — T1016 owns the
content review before the tag. Themes since 0.4.0: eval gates wired into
CI (T739), the pip-audit security job with a pinned ignore list (T984),
versioned docs snapshots per tag on the site (T991/T1000), and the
P51–P52 docs-honesty passes (T981–T1010).

## 0.4.0 — 2026-10-19 (T811)

* Eval gates (T671-T689): `eval/gate.py` pass/fail runner over report JSONs —
  exit-code contract 0/1/2 (`--ci` one-liner), threshold flags
  (`--min-rule-acc` 0.403, `--max-ece` 0.15, `--max-p95-ms` 44, abstention
  band, per-rule worst-case, pool `--min-speedup` 2x), report-kind dispatch
  (eval/i18n/breaker/pool), `--against` deltas, `--changelog` diff blocks,
  `--check-docs` drift check vs the BENCHMARKS Known-numbers table, `--all`
  make-style run, stale-report warnings. Baseline report normalized to
  `n`/`acc`/`per_label` (T678); `eval/reports/latest.json` pointer (T686).
* Platform adapters (T691-T710): Discord/Twitch/Telegram/Matrix/Mattermost/
  Zulip bots plus webhooks with Slack-signature verification — matrix-tested
  against stubs; destructive chat actions became opt-in flags
  (`BOUNCER_TG_DELETE`, `BOUNCER_MX_REDACT`, `BOUNCER_MM_DELETE`,
  `BOUNCER_ZL_DELETE`), `BOUNCER_DRY_RUN=1` prints instead of posting,
  `BOUNCER_RULES_<ADAPTER>` per-adapter rule overrides, fail-closed
  startup with coded `E_ADAPTER` faults, platform env vars documented.
* Packaging (T711-T730): optional-deps groups (`server`/`demo`/`adapters`,
  `finetune` pins training deps separately), `bouncer` console script, clean
  `uv build` wheel + sdist (LICENSE/README/examples included), Dockerfile
  (slim, non-root, OCI labels, start-time self-test) + docker-compose,
  dependency floor pins (`>=`), core import stays weightless (no numpy/laya
  hard dep), `py.typed` marker, `bouncer doctor` self-diagnosis command.
* CI/CD (T731-T750): GitHub Actions on push/PR — pytest + ruff across the
  3.10–3.13 matrix (fail-fast off), wheel build on tags, release job
  attaching wheel + SBOM, tag-vs-version guard, weightless bench +
  eval-gate jobs, secret scan, coverage artifact, nightly stub suite,
  release-notes check, PR/issue templates.
* Performance (T751-T770): warm-pool/cache-hit latency benches, batch-size
  sweep, coalescing metric in `/stats`, question-count knob, token-budget
  context guard, `watch` throughput summary, audit write batching, review
  queue append, `/stats` under threaded load, lazy gradio import (import
  budget < 200ms), fixed bench-report schema (T765) gated by `gate.py`
  perf budgets (T766), measured dated numbers in README/BENCHMARKS with
  honest before/after-finetune columns, pool memory footprint documented.
* Security & ops (T771-T790): threat-model/runbook/SECURITY doc set,
  key-rotation window (`BOUNCER_KEY_OLD`, T776), proxy-pinned rate keys
  (`BOUNCER_TRUSTED_PROXY`, T777), `/v1/systemone` passthrough with
  `E_STATE` key caps (T772-T775), review queue `0600` with bounded raw
  keep (T784), forwarder SSRF pin (`BOUNCER_FORWARD_ALLOW`, T785).
* Docs site (T791-T810): mkdocs-material site whose nav equals the file
  set, six new pages (getting-started, cookbook, version notes, roadmap,
  environment-variable table, error-code index), three runnable example
  scripts, test-enforced link/heading/fence/diagram-fallback/freshness
  lints, GitHub Pages workflow behind the `DOCS_DEPLOY` flag, rewritten
  CONTRIBUTING with a shipped `verify.sh`.
* Fixes found by the first green release CI (T814-T815): `tomli>=2.0`
  backport dep for python < 3.11 (`tomllib` is stdlib only from 3.11 —
  the whole 3.10 matrix leg used to cascade-fail) with import shims at
  all 8 sites; the T781 audit job now extracts pyproject deps to a
  requirements file before `pip-audit -r` (it read TOML as requirements
  and errored on line 1 every run since introduction); `cmd_pack` guards
  `RecursionError` on adversarially deep JSON (exit 4); the
  `latest.json` eval pointer lands beside `--out` so test runs never
  poison the real reports dir.

## 0.3.0 — 2026-10-17 (T626)
* Persistence: atomic writes + `E_SNAPSHOT`, decision/stats snapshots
  (`bouncer snapshot save/load`), review-queue timestamps + pruning, audit
  `tail()` bounded reads, `export --format json/--limit/--action`.
* Router pools: LRU pool keyed by kwargs (`BOUNCER_POOL_MAX`), `BOUNCER_DEVICE`,
  per-request `model=` (engine/serve/CLI/demo) with capability probe, auto
  model-by-language routing (`model_for_lang`), `E_MODEL_NAME`, pool stats in
  `/stats`, `/ready`, `bouncer models`.
* Multitenancy: `preset` field everywhere rules are accepted (`XOR`, `E_PRESET`),
  `GET /presets/{name}`, `BOUNCER_DEFAULT_PRESET`, `bouncer presets`,
  `pack init FILE`.
* Multilingual: lang in reasons, `detect_script()` (latin/arabic), `E_LANG`,
  i18n fixtures + `eval/eval_i18n.py`, preset→lang autofill, per-line `lang` in
  `watch --json-in`, demo language wiring.
* Reliability: circuit breaker (`breaker_n`/`breaker_cool_s`, half-open probe,
  `cause=breaker-open`, `BOUNCER_BREAKER=off`), per-request `timeout_s`
  (0.5–60s, `BOUNCER_TIMEOUT`), `GET /ready`, `bouncer_breaker_open` metric,
  retry backoff.
* CLI: `check/watch --config/--user`, `watch --action/--lang/--json-in`,
  `review --since/--rule/--prune`, `export --format/--action`, `models`,
  `presets`, `serve --key-file/--cors`, `demo --preset`.
* Demo: user box + strikes meter, model dropdown, night mode, require-calm,
  severity box, per-preset threshold memory, history download, queue viewer.
* Eval/data: `breaker_sim.py`, `bench_pool.py` (5.4× pooled vs rebuild; thrash
  case), `eval_gatekeeper --model`, `baseline/validate --limit`,
  `synth_rules --report`, i18n fixtures (12 rows).
* Docs: README persistence/pools/presets/i18n/breaker, api.md preset + readiness
  fields, architecture pool/breaker diagram, SECURITY (key-file + rotation),
  glossary + FAQ additions, eval/reports manifest.

## 0.2.0 — 2026-10-16 (T428)
* Observability: joint action×rule counts, latency p50/p95, cheap-path counter,
  escalate causes, richer audit lines (lang/ctx/thresholds), metrics + /stats
  growth, harm in reasons, review filters.
* Robustness: severity + full config validation (`E_CONFIG`), structured
  422/500s, timeout-named fallbacks observed + queued, shared inference pool.
* Engine: flag band / severity offset / require_calm knobs, margin + thresholds
  + lang + quiet in results, `user_id` strikes, lang-aware questions.
* API/CLI/demo: split gates everywhere, batch/context/size caps, gzip, security
  headers, key hygiene, 20 CLI flags, split demo sliders, language picker.
* Adapters: discord stats + perms fallback, twitch reconnect + redaction,
  webhook headers + escalate forwarding, slack validation.
* Eval/data: argparse everywhere, Brier/p95/abstention/actions/confusions,
  schema checker, `--seed`, stub benches (0.08ms p50 overhead).

## 0.1.2 — 2026-10-14
* Correctness: cache key covers all decision inputs (both thresholds, lang,
  context, quiet-state) — same message under other settings no longer gets a
  stale verdict. Fastpath `"ad"` substring over-match fixed (word boundaries).
* Observability: fastpath/empty decisions now count in stats + audit trail.
* API/CLI: split `allow_threshold`/`delete_threshold` on `/predict`, `/batch`,
  `check`, `watch` (single `threshold` still works); threshold range validated.
* Hardening: batch capped at 32 + shares rate/auth guards, `/v1/systemone`
  guarded, rate-bucket idle eviction, lifespan replaces deprecated `on_event`,
  thread-safe cache + audit, bounded review tail, `CACHE.clear()` for tests.

## 0.1.1 — 2026-10-13
* Real-model shakedown: score floats→labels, forced overrides survive abstention,
  reasons match actions. Golden transcript + MPS notes. Eval dogfoods moderate().
  Review auto-queue, `--version`, publish workflow, es/fr/ar packs.

## 0.1.0 — 2026-10-12
* First tagged release: 200-box build-out complete, 29 tests green, ruff clean,
  sdist builds, zero-shot eval 0.305 (honest baseline for the finetune).
* Programmable mod over base Laya: dynamic-K choice + harm/hype scores + jailbreak/escalate nouls, one pass.
* Gates (allow/flag/delete/escalate), severity, margin abstention, fastpath, cache + coalescing, audit, strikes.
* Server (/predict, /batch, /v1/systemone, /metrics), CLI (check/watch/review/stats/export/pack), Discord/Twitch/webhook stubs.
* Demo Space, 4 presets (+lint), 20+ tests green without weights.
