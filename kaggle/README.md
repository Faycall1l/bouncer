# Kaggle fine-tune kernels

Three kernels, one pipeline. Everything here runs on 2xT4 quota
(~4–5h full run) and every box below is test-enforced in `tests/test_p35.py`
and `tests/test_p48.py` — the source of truth for behavior is those tests.

## Pre-flight (any machine, no GPU)

```bash
python kaggle/train/train.py --dry-run        # T911: parse + config-validate, exit 0/2
```

The dry run checks the knobs (LORA block, floors, flag values) and prints
`DRY_RUN_OK` with what it read — no torch import, no dataset, no weights.
A broken config exits 2 with `DRY_RUN_FAIL:` naming the flag. This is also
what CI runs (`tests/test_p48.py::test_train_parses_and_dry_run_config_validates_end_to_end`).

```bash
python scripts/ft_smoke.py            # T926: dry run + data validate, one command
```

`bouncer-ft smoke` chains this dry run with the dataset schema check
(`eval/validate_data.py`) — the whole pre-flight that runs on any CPU,
before quota is a thought. One receipt, one line per step; a failing step
is named in `FT_SMOKE_FAIL`.

## Flags (train.py)

| flag | default | effect | box |
|---|---|---|---|
| `--max-samples N` | 0 (full) | smoke: truncate to N rows, ~80/10/10 split, 1 epoch | T658 |
| `--epochs N` | 0 → 1 smoke / 3 full | override the epoch count | T913 |
| `--lr X` | 0 → 2.5e-5 | encoder LR; the head keeps its 4x ratio | T913 |
| `--seed N` | 7 | row-shuffle seed — same seed, same split order | T913 |
| `--dry-run` | off | parse + config-validate + exit (pre-flight) | T911 |
| `--resume` | off | continue from `checkpoint_latest` (see below) | T914 |

Knobs live in two places only: these flags, and the `LORA` block at the top
of `train.py` (T652). Nothing else is hardcoded-and-unsettable.

## Smoke first (T659)

`kaggle/train/train.py --max-samples 50` — 50 rows, 1 epoch, the exact same
code path (data → items → train → calibrate → eval → gate). If it can't
print `TRAIN_OK`, the full run won't either. Pre-flight checks:
`scripts/check_kaggle_env.py` (T656).

## Resume (T914)

A crashed or preempted run does not burn quota twice:

```bash
python kaggle/train/train.py --resume
```

restores `checkpoint_latest` weights, the exact early-stopping state
(`train_state.json`: epoch/best_dev/wait, written after each patience
update), and the optimizer/scheduler/scaler momenta (`optim.pt`). Honest
limit: the in-memory *best* weights from before the crash are gone — if the
resumed run never beats the restored `best_dev`, the shipped checkpoint is
the last epoch, not the best. Nothing to resume → loud refusal, not a silent
fresh start.

## Gate order (what has to pass before an HF push)

1. **data gate** — `validate_data.py` over the whole dataset (every row, bad
   JSON included) plus the publisher's `.sha256` pin from
   `upload_dataset_kaggle.py`, both run BEFORE training starts (T924). Schema
   error or hash mismatch → refuse, `return 1`, nothing trains, quota untouched;
   an absent pin is recorded as `absent`, never as a match. Then the row
   asserts: schema, ≥2000 rows, splits non-empty (T386/T651).
2. **train** — dev carve + early stopping; `DEV_FLOOR = 0.35` on dev
   rule_acc (T655).
3. **eval_gatekeeper** on the held-out 500 → `eval_test.json` (T660).
4. **gate.py eval_test.json** — the FULL threshold set: rule_acc floor,
   ECE ceiling, latency budget, abstention band, per-rule floor (T915).
   No threshold flags ride this call — a single source: gate.py's defaults
   are the ship gate's thresholds, pinned equal to `REGEX_FLOOR` by test (T920).
5. **model card** — `README.md` generated into the output folder with this
   run's numbers, the gate verdict, and the provenance record (T917).
6. **push** — only if `token and floors and gate_pass` (T915). A gate that
   never ran (`gate_pass=None`: eval failed, gate.py unreachable) refuses.
   Refusals are logged as `no_push` with every input (T654).

Provenance: every `train_log.jsonl` line carries `dataset_sha256`,
`git_sha`, and the knob config (T916) — any number in the trail is traceable.

## i18n eval of a run (T918)

```bash
python eval/eval_i18n.py --model /kaggle/working/bouncer-421m
```

scores per-language decision quality against that checkpoint (CPU). A dir
that isn't a checkpoint → `status: fail` + exit 1; laya missing → skip with
a receipt. Never a fabricated per-language score.

## Failure modes (T667)

| symptom | likely cause | fix |
|---|---|---|
| CUDA OOM mid-epoch | T4 16GB ceiling, batch too hot | `MICRO` 8→4 (double `ACCUM` to keep effective batch), drop `max_len` 1024→512, or enable the LoRA block (T652) — checkpointing + fp16 are already on |
| `SKIPPED` ≈ half the rows (T651 assert fires) | token cap: rows whose rule-sets blow `head_max_len=256` | fewer/shorter rules per row (lower K in the build), or trim rule text in `data/synth_rules.py` |
| dev rule_acc plateaus near 0.30 | label noise from teacher distillation, or base-model collapse | inspect the quarantine file (T645) for teacher garbage, check label balance (`build_dataset.py --report`, T633), re-synth with more hard negatives (T636) |
| run dies at hour 4, no push | quota exhaustion / preemption | `--resume` (T914) continues from `checkpoint_latest`; re-run with `--max-samples` sanity first, then full |
| training fine, no HF push | the gate said no: dev < 0.35, test_acc < 0.403 (T655/T661), or **gate.py failed** (ECE/per-rule/abstention/latency — T915), or no `HF_TOKEN` | read `train_log.jsonl`: `no_push` records carry both floors **and** `full_gate`; a refusal is information, not an error |
| `full_gate=not run` in `no_push` | eval_gatekeeper or gate.py unreachable (repo not a kernel input) | add the repo as a kernel input so both scripts are found, or run them locally against the written split |
| `DATA_GATE: refusing to train` at startup | validate_data found bad rows, the `.sha256` pin doesn't match the downloaded dataset, or validate_data.py is unreachable (T924) | re-publish with `upload_dataset_kaggle.py --yes` (the pins travel with the dataset), or add the repo as a kernel input; nothing trained, no quota spent |
| `temp.json` temps look extreme (>5, <0.5) | calibration slice too small or too easy | check `calib_items` count in `temp.json`; refit with more calibration rows before trusting probabilities |

**Status: NOT RUN.** These kernels are documented and test-pinned; the
full 4–5h fine-tune itself has not been executed in this repo's history.
