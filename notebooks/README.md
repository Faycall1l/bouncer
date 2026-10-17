# Fine-tune on Kaggle 2xT4 (4-5h)

Don't write RLCD from scratch — fork Laya's notebook, swap dataset:

1. Open [laya_finetune_typed_decisions_2xT4_kaggle.ipynb](https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb) → Copy to your Kaggle.
2. Replace dataset cell with:
```python
# gatekeeper rows -> laya format (state + questions + teacher dist)
import json
from gatekeeper_format import to_laya_records  # see finetune_kaggle.py
records = to_laya_records("/kaggle/input/gatekeeper-12k.jsonl")
```
3. Keep RLCD defaults: backbone lr 1e-5, head lr 1e-4, 4 epochs, Gaussian logit noise, log+spherical reward + soft CE.
4. Run all → temperature refit on dev → push `YOUR_HF/gatekeeper-laya-421m`.

`finetune_kaggle.py` here = the 3 cells you paste (converter + train call + push). Full loop already proven by Laya; your novelty is the dynamic-K dataset.

**Smoke first (T659):** before any full run, execute
`kaggle/train/train.py --max-samples 50` — 50 rows, 1 epoch, the exact same code
path (data → items → train → calibrate → eval → gate). If it can't print
`TRAIN_OK`, the 4-5h run won't either. Pre-flight checks: `scripts/check_kaggle_env.py` (T656).

## Failure modes (T667)

| symptom | likely cause | fix |
|---|---|---|
| CUDA OOM mid-epoch | T4 16GB ceiling, batch too hot | `MICRO` 8→4 (double `ACCUM` to keep effective batch), drop `max_len` 1024→512, or enable the LoRA block (T652) — checkpointing + fp16 are already on |
| `SKIPPED` ≈ half the rows (T651 assert fires) | token cap: rows whose rule-sets blow `head_max_len=256` | fewer/shorter rules per row (lower K in the build), or trim rule text in `data/synth_rules.py` |
| dev rule_acc plateaus near 0.30 | label noise from teacher distillation, or base-model collapse | inspect the quarantine file (T645) for teacher garbage, check label balance (`build_dataset.py --report`, T633), re-synth with more hard negatives (T636) |
| run dies at hour 4, no push | quota exhaustion / preemption | rolling `checkpoint_latest` survives per epoch (T653+); re-run with `--max-samples` sanity first, then full |
| training fine, no HF push | gate said no: dev < 0.35 or test_acc < 0.403 (T655/T661), or no `HF_TOKEN` secret | read `train_log.jsonl` `no_push` records — both metrics and both floors are in there; a refusal is information, not an error |
| `temp.json` temps look extreme (>5, <0.5) | calibration slice too small or too easy | check `calib_items` count in `temp.json`; refit with more calibration rows before trusting probabilities |
