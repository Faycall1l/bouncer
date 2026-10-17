# What a real fine-tune run changes (draft, T665)

**Status: draft.** Every "expected" number below is a template to fill after the
first real Kaggle run — nothing here is measured. When the run lands, replace
each EXPECTED line with the actual figure and its measurement conditions, then
update `BENCHMARKS.md`, the README honest-limits table, and the FAQ checkpoint
entry (T669 adds the release-checklist hook).

## Before (measured, current)

| number | value | where measured |
|---|---|---|
| zero-shot base rule_acc | **0.305** | 200 rows, CPU kernel (T108) |
| regex baseline | **0.403** | `data/examples.jsonl` 300 rows (T637; was 0.480 pre-hard-negatives) |
| gate@0.85 precision | n/a | base model never confident — honest abstention |
| calibration (ECE) | not refit | base temperatures only |
| engine overhead | p50 0.08ms | stub bench, no weights (T385) |

## After (EXPECTED — unmeasured until the run)

| number | expected direction | honest caveat |
|---|---|---|
| rule_acc on held-out 500 | well above 0.305; must be ≥ 0.403 to ship (T661 gate) | held-out from the same synthetic distribution — transfer to open chat is still unmeasured |
| gate@0.85 precision | populated for the first time | gated coverage may be tiny; report coverage alongside precision |
| ECE after temp refit | target ≤ 0.15 (P36 gate T673) | refit on the same distribution it will be judged on — refit on your own data before trusting it |
| p95 latency (T4) | ~33ms forward + RLCD sampling overhead | GPU numbers don't transfer to CPU hosts |
| calibration artifact | `temp.json` in the checkpoint (T662) | one temperature per run; do not mix artifacts across runs |

## What a real run does NOT change

* Engine overhead, breaker, cache, pool numbers — model-independent (T385/T453).
* The regex baseline — it is a property of `examples.jsonl`, not of the model.
* The honest-limits section's structural caveats: template bootstrap, 3 violation
  types + ok, English-first, K-varied synthetic rule-sets.
* Zero-shot numbers — they stay as the "before" column, not deleted.

## Post-run checklist (fill in this order)

1. Run `eval/eval_gatekeeper.py $OUT/test_split.jsonl --model $OUT` (T660) and
   paste the full report, not just rule_acc.
2. `BENCHMARKS.md`: new "fine-tuned (date, kernel id, N rows, epochs)" section —
   keep the zero-shot section for comparison.
3. README honest-limits table: update the "gatekeeper 200-row CPU zero-shot
   0.305" row with the finetuned counterpart, same caveats column.
4. FAQ "Which model checkpoint should I use?" (T600): update the base-vs-finetune
   comparison sentence with both measured numbers.
5. CHANGELOG 0.4.0 entry: model quality claims only from this report.
6. If the run fails the T661 gate (rule_acc < 0.403): ship nothing, document the
   failure in this file (a failed run is data, not shame), and try the next
   config — the gate exists so a bad model never becomes the default.
