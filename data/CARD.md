# Dataset card: gatekeeper-chatmix (T638)

Card for the synthetic chat-moderation dataset built by `data/build_dataset.py`.
Machine-readable fields for the HF upload live in `data/CARD.md` §HF fields.

## What it is

Per-row rule-sets (K varies 3–6) + one chat message + five labels. The model
must *read the rules*, not memorize label ids — rule-sets and K change every row.

```json
{"state": {"message": "...", "history": ["user: ...", "..."], "rules": {"no-spam": "..."}},
 "labels": {"rule": "no-spam", "harm": "harmful", "hype": "chill",
            "jailbreak": false, "escalate": false}}
```

## Splits (server-disjoint, T632)

| split | default share | guarantee |
|---|---|---|
| train | ~80% | its rule-sets appear in no other split |
| dev | ~10% | same |
| test | ~10% | same |

"Server" = one rule-set (the ids). Unseen-K and unseen-phrasing transfer is the
point; the split verifier test enforces zero rule-set leakage. Split files:
`gatekeeper-12k.{train,dev,test}.jsonl` from one `build_dataset.py` run.

## Labels

| field | values | notes |
|---|---|---|
| rule | any rule id in the row, or `ok` | 3 violation types in template mode |
| harm | safe / suspicious / harmful | ordered |
| hype | dead / chill / hyped | ordered |
| jailbreak | bool | `ignore-all-rules` shaped rows |
| escalate | bool | needs-human rows (fixed T636: no more `bool(0.1)` accidents) |

## Generation

* `data/synth_rules.py`: template bootstrap (offline, `--template-only`) +
  optional teacher rows (OpenAI-compatible endpoint, RLCD-style distillation).
* History windows: 2–4 neutral turns (T635) — never label-bearing.
* Hard negatives: linkless spam, polite insults, sarcasm (T636, default n//10).
* Dedupe: normalized-hash near-duplicate collapse (T634, opt-in `--dedupe`).

## License

Apache-2.0 — same as the repository (see `LICENSE`). Rows are synthetically
generated; no real user content is included.

## Limits (read before training)

* Template rows repeat a handful of message shapes; zero-shot numbers measure
  transfer to unseen phrasings, not open-world chat. Teacher rows fix scale,
  not realism.
* Only 3 violation types + ok in v1. Real communities need more.
* English-first. i18n fixtures (`examples_i18n.jsonl`, 12 rows) prove wiring,
  not quality.
* Regex baseline on `examples.jsonl`: **0.403** post-T637 (0.480 before hard
  negatives existed). Base Laya zero-shot: **0.305**. Both numbers and their
  measurement caveats: `BENCHMARKS.md`.
* Don't ship verdicts from the base model — fine-tune first (`kaggle/train`).

## HF fields

```yaml
license: apache-2.0
task_categories: [text-classification]
language: [en]
tags: [moderation, rule-following, calibrated-decisions, rlcd]
size_categories:
  - n<10K: dev/test
  - 10K<n<100K: train (default build n=12000)
```
