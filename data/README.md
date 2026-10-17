# Gatekeeper-ChatMix dataset

Full dataset card (splits, labels, license, limits): [`CARD.md`](CARD.md) (T638).

`gatekeeper-12k.jsonl`: one row = one message + THAT server's rule-set (K varies 3-6) + 5 labels.

```json
{"state": {"message": "...", "history": [], "rules": {"no-spam": "...", "be-kind": "..."}},
 "labels": {"rule": "no-spam", "harm": "harmful", "hype": "hyped", "jailbreak": false, "escalate": false}}
```

Splits: 10k train / 1k dev / 1k test, server-disjoint (test rule-sets unseen). Teacher: template bootstrap + Qwen/GPT distillation, spot-checked 200 rows.

Why classical fails: fixed 77-way classifier memorizes labels; here criteria text + K change per row. Must read rules, not memorize ids.

Build (one command: synth → validate → server-disjoint split, T631):
`python data/build_dataset.py --n 12000 --seed 42`
Low-level synth only: `python data/synth_rules.py --n 12000 --out data/gatekeeper-12k.jsonl`
Distribution check (no write): `python data/synth_rules.py --n 2000 --template-only --report` (T574)
HF push (dry-run by default, T639): `python data/upload_hf.py` then `--yes`.

## examples_i18n.jsonl (T504+T579)

12 wiring rows for non-English pipelines — 4 each in `es`, `fr`, `ar` (mixed
latin + arabic scripts). Same schema as `examples.jsonl` (no extra fields —
`eval_i18n.py` derives the language from the rule ids and asserts
`detect_script()` agrees with it, T498):

```json
{"state": {"message": "GG buena partida a todos", "history": [],
           "rules": {"sin-spam": "sin anuncios…", "se-amable": "sin insultos…"}},
 "labels": {"rule": "ok", "harm": "safe", "hype": "chill",
            "jailbreak": false, "escalate": false}}
```

Purpose: pin `lang` plumbing end-to-end (detect_script → reason → preset-lang
autofill), **not** quality — base-model accuracy in these languages is unproven
and stated in `BENCHMARKS.md#honest-limits`. Validate with
`python eval/validate_data.py data/examples_i18n.jsonl`, wire-check with
`python eval/eval_i18n.py` (report → `eval/reports/i18n.json`).
