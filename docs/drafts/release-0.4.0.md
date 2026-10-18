# Release notes: v0.4.0 (T812/T817, DRAFT)

200 boxes (T631–T830) across eval gates, adapters, packaging, CI/CD,
performance, security & ops, the docs site, and the 0.4.0 release itself.
Still no model changes — same zero-shot behavior, far better operations,
surface, and docs around it.

## Verification

* `pytest -q`: **412 passed, 1 warning** (2026-10-18, weightless env,
  macOS arm64) — T812.
* `ruff check .`: **clean** (repo-wide, line-length 100) — T813.

(Highlights / bugs / upgrade notes land with T817.)
