# Release notes: v0.5.0 (T1012/T1017, DRAFT)

Draft: T1017 writes the full notes (v0.4.0's draft is the shape); this
file starts at T1012 with the release-tree verification receipts, the
way T812/T813/T814 built theirs as the 0.4.0 tree went green.

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
