# Changelog (T146/T168/T601)

## Unreleased

## 0.5.0 — 2026-10-22 (T1016)

200 boxes (T831–T1010) across server hardening, adapter depth,
CLI/rules/storage, multilingual routing, the fine-tune pipeline,
observability, repo-wide refactor & hygiene, a security refresh, and
the docs site — plus the release boxes T1011–T1016 that carry this
section (its date comes from the T1011 bump, which T819's release
sweep forces the moment pyproject reads 0.5.0). Still no model changes:
same zero-shot behavior, a much harder surface around it.

* Server hardening (T831-T850): stream-bound body cap — chunked POST can
  no longer bypass MAX_BODY; `/v1/systemone` gets a typed schema (unknown
  fields 422) routed through the safe predict path (timeout/breaker/
  retry) with decision+audit parity; `ModReq` `extra=forbid`; batch
  lang/preset autofill and one overall batch deadline (was 32×60s worst
  case); uvicorn `--timeout-keep-alive`/`--limit-concurrency`; graceful
  shutdown drains in-flight predicts and flushes audit; X-Request-ID
  correlates access and decision logs; thread-safe rate-limit buckets;
  `/stats` gated behind `BOUNCER_KEY` like `/metrics`.
* Adapter depth (T851-T870): shared `http_json` retry/backoff honoring
  Retry-After (jittered ladder, 5s doubling to a 60s cap), mattermost
  websocket reconnect, Health+RateCap parity for discord/twitch, `user=`
  at all seven call sites with `platform:user` namespaced strikes
  (per-user accrual from platform traffic, decision-cache isolation),
  script-detected `lang=` (ar/zh/ru), in-thread notices on every
  platform, the APPEAL flow linked to review-queue row ids,
  `bouncer adjudicate` + strike amnesty, `BOUNCER_FORWARD_URL` firing
  from platform traffic, per-adapter decision counters, and the README
  Capabilities matrix (T868).
* CLI, rules, storage (T871-T890): `bouncer config validate`, `pack
  diff`, `pack sign`/`pack verify` (E_PACK_SIG), `check --file` batch
  scoring, `completion bash|zsh` generated from the parser itself,
  snapshot schema v2 with v1 migration + cache snapshot wiring, pack
  lint duplicate/invisible-text guards, review and audit rows gain
  cause/model/preset/rid, `/metrics` gains per-rule/cause/p95/strikes/
  request-status/auth/429 families, `export` gains the review format.
* Multilingual routing (T891-T910): checkpoint routing keys off detected
  script — `/predict` autofills `lang` when omitted (batch parity),
  `check`/`watch` accept `--lang auto`, `BOUNCER_ADAPTER_LANG`
  per-platform override (explicit beats detected), lang-tagged pool
  checkout stats, `eval_i18n.py` measures routing with a gated `i18n`
  report kind, mixed-language pool bench (thrash measured, not
  folklore), cookbook recipe.
* Fine-tune pipeline (T911-T930): `train.py` import-safe on CPU with
  `--epochs/--lr/--seed`, LoRA targets corrected for bert-style
  encoders, resume-from-checkpoint, provenance in every log line
  (dataset hash + git sha + config), generated model card,
  `validate_data` refusing hash mismatch before training, ship gate on
  gate.py's FULL thresholds, CPU smoke (`bouncer-ft smoke`) on the
  nightly — the pipeline is receipted; the run itself is still NOT RUN
  and the roadmap says so.
* Observability (T931-T950): the `/metrics` surface completed and
  pinned — coalesce/breaker, review-queue depth, per-adapter counters,
  request/auth status classes, cardinality caps (fresh rule ids fold to
  `_other`; labeled lines stay ≤300 under 5k adversarial ids), a strict
  Prometheus-exposition parser test (HELP/TYPE complete), worker-scope
  warning, scrape+alert recipe in the runbook, and a `metrics` report
  kind gated structurally and at p50 ≤ 100ms (T948).
* Refactor & repo hygiene (T951-T970): shared adapter plumbing deleted
  13 copies (`api()`, command table, moderate skeleton), dead code
  removed or demoted with receipts (no-dead-code sweep walks 178 defs),
  adapter-parity matrix test, stricter ruff subset with 148 violations
  fixed and zero `noqa`, help-text sweep over all 63 undocumented
  flags, suite wall-time budget with written justifications (T967),
  import budget re-verified at 31.9ms p50 of 200ms, CONTRIBUTING
  rewritten around the new gates.
* Security refresh (T971-T990): threat model / SECURITY / runbook
  updated for this surface — adjudicate and amnesty are operator-only
  and audited (pinned), preflight OPTIONS side-effect-free, rate-limit
  proven under parallel threads, SIGTERM drain-vs-force race documented,
  review queue `0600` enforced through every rewrite path, audit
  rotation re-stormed at the 5MB budget, docker non-root re-verified
  (`site/` added to .dockerignore), SBOM covers the new extras,
  secret scan covers `hf_` tokens, pip-audit job with a per-advisory
  ignore list pinned with written reasons, serializer-agnostic CI fix.
* Docs site & versioned docs (T991-T1010): per-tag site snapshots
  (`scripts/build_docs_version.py` — git-archive extraction + strict
  build to `site/<tag>/`) wired into the docs workflow behind
  DOCS_DEPLOY; versions.md resolves every tag to its delta; api route
  table, error-code index, environment table, cookbook (now 9 recipes),
  getting-started, release checklist, roadmap, glossary, adapters
  README, and BENCHMARKS all refreshed for 0.5.0 with test-pinned
  claims; example scripts re-run green; nav == file set; union link
  checker; freshness markers track pyproject's version exactly (T1005).

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
