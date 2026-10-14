# Changelog (T146/T168)

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
