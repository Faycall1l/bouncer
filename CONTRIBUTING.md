# Contributing (T145)

* One TODO box = one commit + push. Keep diffs tiny and green.
* Verify gate before every push (T404): full `pytest -q` green AND
  `ruff check src tests` clean. Never push red — fix forward instead.
  Pipe exit codes through (`tail` swallows them); fail the chain on red.
* Tests run without weights (stub routers). Weight-needing scripts live in
  `eval/` + Kaggle kernels, never in unit tests.
* No secrets in code — tokens via env only.
* Rule packs: add to `presets.py` + fixtures + docs catalogue.
