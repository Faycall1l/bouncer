# Release notes: v0.2.0 (T429, DRAFT)

200 boxes (T231–T430) across observability, robustness, engine gates, API/CLI,
adapters, eval, and docs. No model changes — same zero-shot behavior, richer
shapes around it.

Highlights for users:

* Split gates everywhere: `--allow-threshold` / `--delete-threshold` on CLI,
  API, and demo sliders. Tune allows and deletes independently.
* Stale-cache class of bug closed: the key covers every decision input, and a
  regression test pins it.
* Cheap paths (fastpath/empty) and failure fallbacks now appear in stats,
  audit, and review — no more invisible decisions.
* Hardened server: batch caps, body/context limits, gzip, security headers,
  constant-time auth, structured 422/500s, `Retry-After`.
* 102 tests green without weights; `ruff check .` fully green; CI runs both.

Upgrade notes:

* `review.list_queue()` tail window widened (1000) when filtering by action.
* `appeal_text()` takes an optional `rules` second arg (back-compatible).
* `moderate()` results carry new keys (`cause`, `margin`, `thresholds`, `lang`,
  `quiet_active`, explicit `cached`) — additive only.
* `eval/reports/*.json` are now gitignored; committed tables live in
  BENCHMARKS.md.

Tag: `v0.2.0`.
