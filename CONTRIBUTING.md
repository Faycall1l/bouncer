# Contributing (T145)

* One TODO box = one commit + push. Keep diffs tiny and green.
* Tests run without weights (stub routers). Weight-needing scripts live in
  `eval/` + Kaggle kernels, never in unit tests.
* No secrets in code — tokens via env only.
* Rule packs: add to `presets.py` + fixtures + docs catalogue.
