# Real Laya answer shape (T202, measured laya 0.4.6)

_(Last checked against v0.4.0.)_

```json
{"answers": {
  "choice_q": {"type": "choice", "choice": "billing",
               "probabilities": {"billing": 0.95, "other": 0.05},
               "confidence": 0.71, "answer_confidence": 0.95},
  "noul_q": {"type": "noul", "noul": 0.05, "confidence": 0.95},
  "score_q": {"type": "score", "score": 0.73, "legend": {"0": "low", "1": "high"},
              "probabilities": {"0": 0.27, "1": 0.73}, "confidence": 0.16}},
 "routing": {"model": "english", ...}, "usage": {...}}
```

Gotchas bouncer handles:
* `score` is a **float** (expected level) → snap `round()` to label (T203).
* score `probabilities` keyed by **index strings**, not labels.
* `confidence` ≠ top probability (act-aware) — gate on it, show both.
* Base checkpoint warns `invalid temperatures` → treat conf as uncalibrated until refit.

Terms used here are defined in the [Glossary](glossary.md).
