# Contributing (T145)

* One TODO box = one commit + push. Keep diffs tiny and green.
* Verify gate before every push (T404): full `pytest -q` green AND
  `ruff check .` clean (T402+T745: repo-wide, not src/tests). Never push
  red — fix forward instead.
  Pipe exit codes through (`tail` swallows them); fail the chain on red.
* Tests run without weights (stub routers). Weight-needing scripts live in
  `eval/` + Kaggle kernels, never in unit tests.
* No secrets in code — tokens via env only.
* Rule packs: add to `presets.py` + fixtures + docs catalogue.
* Releases follow `docs/RELEASE-CHECKLIST.md` (T669): accuracy numbers must be
  refreshed from a measured eval report before any tag — never vibes.
* Branch protection (T745 — GitHub settings, repo files can't flip it):
  require the `ci` status checks (`lint`, `test` matrix, `weightless`,
  `eval-gate`) before merge to `main`, and block force-pushes. Reviews
  route through the maintainer via `.github/CODEOWNERS`.
