# Release notes: v0.5.0 (T1012/T1017, DRAFT)

200 boxes (T831–T1010) across server hardening, adapter depth,
CLI/rules/storage, multilingual routing, the fine-tune pipeline,
observability, repo-wide refactor & hygiene, a security refresh, and
the docs site — plus the release boxes T1011–T1030 that carry it.
Still no model changes — same zero-shot behavior, a much harder
surface and far better tooling around it.

Highlights for users:

* **Appeals, adjudication, amnesty**: platform users can `APPEAL` a
  removal and get the newest review-queue row rendered with its id;
  operators answer with `bouncer adjudicate ROW_ID approve|reject`
  (reject runs strike amnesty) or `bouncer amnesty USER` directly —
  both CLI-only (platform users cannot adjudicate) and both audited
  with who/when/why.
* **Multilingual routing**: checkpoints are chosen by detected script,
  not just the caller's `lang` — `/predict` autofills it when omitted
  (batch included), `check`/`watch` take `--lang auto`, adapters pass
  script-detected `lang=` (ar/zh/ru) with `BOUNCER_ADAPTER_LANG` as
  the per-platform override, and `eval_i18n.py` measures routing as a
  gated `i18n` report kind.
* **Observability**: the `/metrics` surface is complete — per-rule,
  cause, latency p95, strikes, coalesce/breaker, review-queue depth,
  per-adapter counters, request/auth/429 classes — with cardinality
  capped (fresh rule ids fold into `_other`), a strict Prometheus
  exposition test, a scrape + alert recipe in the runbook, and a
  `metrics` report kind gated on format and p50 ≤ 100ms.
* **Server hardening**: `/v1/systemone` runs through the safe predict
  path (timeout/breaker/retry) behind a typed schema, chunked bodies
  are capped like content-length ones, unknown request fields are 422
  instead of silently dropped, a batch shares one overall deadline,
  `/stats` sits behind `BOUNCER_KEY` like `/metrics`, shutdown drains
  in-flight work and flushes audit, and `platform:user` namespaced
  strikes keep per-user state from crossing identities.
* **CLI & packs**: `bouncer config validate`, `pack diff`, `pack
  sign`/`verify` (E_PACK_SIG), `check --file` batch scoring,
  `completion bash|zsh` generated from the parser, snapshot schema v2
  with v1 migration, and pack lint guards against duplicate ids and
  invisible-only rules.
* **Adapter depth**: shared retry/backoff honoring `Retry-After`,
  mattermost websocket reconnect, health/rate-cap parity, threaded
  removal notices on every platform, forwarding of platform traffic
  through the SSRF-pinned `BOUNCER_FORWARD_URL`, per-adapter decision
  counters, and `user=` stamped at all seven call sites.
* **Fine-tune pipeline (built, not run)**: import-safe CPU training
  with flags, resume, provenance (dataset hash + git sha + config),
  generated model card, data gate that refuses hash mismatch, ship
  gate on the full `gate.py` thresholds, and a nightly CPU smoke —
  the run itself is still NOT RUN, exactly as the roadmap says.
* **Docs site**: per-tag versioned snapshots behind `DOCS_DEPLOY`,
  versions.md resolving every tag to its delta, and refreshed api /
  error-code / environment / cookbook (9 recipes) / getting-started /
  glossary / threat-model / runbook pages whose claims are pinned to
  source by tests.

Bugs found by the release tests themselves:

* The graceful-shutdown drain test assumed warmup beat its 0.3s
  in-flight sleep — CI (huggingface/laya installed) warmed up slower
  and the drain legitimately measured ~0; work now starts after
  `__aenter__` (T849).
* The i18n eval test asserted only the skip branch — CI has weights,
  so the eval honestly reports present and defers; the test accepts
  either honest branch and never a fabricated score (T906).
* An audit-row assertion matched the spaced stdlib serializer while
  full installs take gradio's orjson fastpath — now parsed, never
  separator-matched, proven by installing orjson locally (T989).
* Three CI reds in the P50 sweep: the stricter-ruff receipt imported
  stdlib-only `tomllib` bare (3.10 leg; now the tomli-fallback
  pattern), the suite wall-time budget flaked on slow runners (CI now
  has a documented 5s backstop, local keeps 1s), and pillow CVEs
  surfaced through gradio's pin (each named `--ignore-vuln` with the
  written reason) (T969).
* The pip-audit job caught the advisory DB growing on release day —
  the pillow ignore list went from 8 to 35 pinned ids across three
  hotfixes, each re-verified live with pip-audit rc=0 (T984).
* The P52 docs degradations: tag-derived assertions and number pins
  degrade honestly where CI has no tags or bench reports — and the
  audit gained GHSA-78g4-xqwv-q3g8 (pillow 12.3.0, fix unreachable
  under gradio's cap).

Upgrade notes:

* Unknown request fields are now **422** (`extra=forbid`) instead of
  silently dropped — drop stale keys from clients (T835).
* A batch shares **one overall deadline**; the old worst case
  (32 messages × 60s) is gone (T837).
* `/stats` requires the key when `BOUNCER_KEY` is set, like
  `/metrics` (T842).
* Chunked uploads are capped before read — bypassing the body cap
  via transfer-encoding no longer works (T831).
* Snapshots are schema **v2**: v1 loads through an in-memory
  migration (noted on stdout); unknown versions refuse (T876).
* Strike keys from platform traffic are `platform:user` namespaced;
  CLI keys stay raw and addressable (T858).
* `bouncer serve` gains `--timeout-keep-alive` and
  `--limit-concurrency` wired to uvicorn (T838).
* `__version__` / package version: `0.5.0`.
* 622 tests green without weights; `ruff check .` green; CI green on
  the release tree (status recorded below).

Tag: `v0.5.0` (cut at T1030, after the final green at T1028).

## Verification

* `pytest -q`: **622 passed, 1 warning** (2026-10-22, weightless env,
  macOS arm64, tree = the T1011 version-bump commit) — T1012.
* `ruff check .`: **clean** — All checks passed under both ruff 0.17.2
  (uvx latest) and the pinned 0.11.0 parity run, repo-wide — T1013.
* `ci workflow` + `docs workflow`: **green** on every release-tree
  commit so far — 7d32ac0 (T1011), 292bec3 (T1012), 7226d1b (T1013):
  ci run conclusion `success` (full matrix, coverage, audit, eval gate,
  secret scan) and docs run `success` on each — T1014. The commit that
  ends up tagged is pushed at T1029; this status is re-recorded as the
  remaining release boxes land.
* `eval/gate.py --all --check-docs`: **PASS — 10 reports gated, 0
  failed** (15–19 checks per report, including the docs-drift pass over
  the BENCHMARKS Known-numbers table). Report dates: i18n + pool
  2026-10-22, import 2026-10-21, metrics 2026-10-20, the other six
  2026-10-19. The one number that cannot be re-measured in a weightless
  env — zero_shot_rule_acc — stays marked **STALE** in the table's
  status column with its reason (T815 row, T1008 refresh), so nothing
  claims freshness it does not have — T1015.
