# Benchmarks

## Zero-shot base Laya on gatekeeper-chatmix (T108)

Kernel `faycal00/bouncer-eval-zero` (CPU, 200 rows, 1 choice question).

| metric | value | status |
|---|---|---|
| rule_acc | — | running |
| gate@0.85 prec | — | running |
| p50 latency (CPU) | — | running |
| overconfident errors | — | running |

Filled from kernel log when COMPLETE.

## Honest limits (T109)

* Template bootstrap: 6 message shapes × 3 rule-sets. Zero-shot numbers measure
  transfer to unseen phrasings, not open-world chat.
* Only 3 violation types + ok in v1 labels. Real communities need LLM-distilled rows.
* Base Laya is English-first; non-English routes to multilingual checkpoint (~23/51 usable alone).
* Keep choice questions ≤20 options (256-token head budget; Banking77 lesson).
* Refit temperatures on your own held-out data before trusting probabilities.
