# Release notes: v0.4.0 (T812/T817, DRAFT)

200 boxes (T631–T830) across eval gates, adapters, packaging, CI/CD,
performance, security & ops, the docs site, and the 0.4.0 release itself.
Still no model changes — same zero-shot behavior, far better operations,
surface, and docs around it.

## Verification

* `pytest -q`: **412 passed, 1 warning** (2026-10-18, weightless env,
  macOS arm64) — T812.
* `ruff check .`: **clean** (repo-wide, line-length 100) — T813.
* `ci workflow` (release commit): **green** — red for 30+ runs on four
  macOS/3.10-only root causes, all fixed in this release tree: `tomllib`
  is stdlib only from 3.11 so the whole py3.10 matrix leg cascaded
  (added `tomli>=2.0; python_version < '3.11'` marker dep + import shims
  at all 8 sites), the PR-template test read `PULL_REQUEST_TEMPLATE.md`
  while git tracks lowercase `pull_request_template.md` (case-insensitive
  APFS hid it), the bench_warm refusal test assumed "no laya anywhere"
  but CI installs the package *with* laya so real mode actually ran (now
  forced hermetically via a raising-laya shadow), and a 2000-deep JSON
  pack raises `RecursionError` on ≤3.11/3.13 which the pack-load guard
  didn't catch (now `OSError, ValueError, RecursionError` → exit 4) —
  T814.

(Highlights / bugs / upgrade notes land with T817.)
