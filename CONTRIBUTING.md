# Contributing (T145, extended T804)

## Boxes workflow

* Work comes in TODO batches (~200 boxes with `T###` ids, e.g.
  P42 = T791–T810). One TODO box = one commit + push. Keep diffs tiny
  and green.
* Tick a box (`- [x]`) only when its work is done, in the same commit as
  the work — the tick and the change land together. Commit messages start
  with the box id: `T804 docs: ...`.
* Receipts (evidence a box was really done) live in commit messages,
  tests, and docs — never as prose inside TODO.md. If a box's text went
  stale, correct the box text in the same commit. A "design" box may be
  delivered as a working implementation (a superset of the ask).

## Verify gate

* `./verify.sh "T### message"` is the gate: full `pytest -q` green AND
  `ruff check .` clean (T402+T745: repo-wide, not a src/tests subset),
  then commit + push. It stops at the first red. Never push red — fix
  forward instead.
* Pipe exit codes through (`tail` swallows them); fail the chain on red.
* Tests run without weights (stub routers). Weight-needing scripts live in
  `eval/` + Kaggle kernels, never in unit tests.

## Code style

* ruff over the whole repo (`ruff check .`), `line-length = 100`
  (pyproject `[tool.ruff]`). The narrow src/tests lint wording is dead
  since T745.
* Every non-obvious change carries the box id that made it: `# T###` in
  code, `(T###)` in doc headings; tests for a batch live in
  `tests/test_pNN.py` (one file per batch).
* Env vars read from the environment (`BOUNCER_*`, platform tokens) must
  be documented in the same commit: core/CLI vars in the docs env table,
  adapters in `src/gatekeeper/adapters/README.md` (CI gate since T710).
* Numbers are receipts: benchmark or accuracy figures come from real eval
  reports (BENCHMARKS.md) — never invented, never vibes.
* No secrets in code — tokens via env only.
* Rule packs: add to `presets.py` + fixtures + docs catalogue.
* Releases follow `docs/RELEASE-CHECKLIST.md` (T669): accuracy numbers must be
  refreshed from a measured eval report before any tag — never vibes.
* Branch protection (T745 — GitHub settings, repo files can't flip it):
  require the `ci` status checks (`lint`, `test` matrix, `weightless`,
  `eval-gate`) before merge to `main`, and block force-pushes. Reviews
  route through the maintainer via `.github/CODEOWNERS`.
