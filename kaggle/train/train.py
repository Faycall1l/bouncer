"""Full bouncer fine-tune, single-GPU adaptation of Laya's 2xT4 DDP script.
Needs GPU quota (30h/week). Rolling checkpoint per epoch + HF push via HF_TOKEN secret.
Smoke-validated: 7500/7500 items build clean (bouncer-smoke-cpu v6).

Input schema (T386): JSONL rows from data/synth_rules.py —
  {state: {message: str, history: [str], rules: {rule_id: rule_text}},
   labels: {rule: rule_id | "ok", harm: safe|suspicious|harmful,
            hype: dead|chill|hyped, jailbreak: bool, escalate: bool}}
Input is read from the first /kaggle/input/**/*.jsonl file; 1500 train / 500 test.
Smoke path (T659): `--max-samples 50` truncates to 50 rows (40/5/5 split) and
defaults to 1 epoch (T913: `--epochs` overrides) — validates data -> items ->
train -> calibrate -> eval for a
fraction of the quota. Run it first, every time; if it can't print TRAIN_OK,
the full run won't either.
Hyperparameters (T913): `--epochs`/`--lr`/`--seed` — 0/absent means the
shipped default, so a plain `python train.py` reproduces the 2xT4 recipe.
Import-safe on CPU (T911): importing this module does no pip install, no GPU
assert, no data read — deps install and the CUDA check happen inside main(),
and `--dry-run` parses + config-validates on any machine (T919).
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
import time

FLAGS = argparse.ArgumentParser(add_help=False)  # T658: --max-samples smoke flag
FLAGS.add_argument("--max-samples", type=int, default=0,
                   help="truncate total rows for a smoke run (0 = full dataset)")
FLAGS.add_argument("--dry-run", action="store_true",
                   help="T911: parse + config-validate, then exit (no GPU/data/weights)")
FLAGS.add_argument("--epochs", type=int, default=0,  # T913: the three knobs
                   help="epoch count (0 = default: 1 for smoke runs, 3 full)")
FLAGS.add_argument("--lr", type=float, default=0.0,
                   help="encoder learning rate (0 = default 2.5e-5); the head "
                        "learns 4x the encoder rate, as in the 2xT4 recipe")
FLAGS.add_argument("--seed", type=int, default=7,
                   help="row-shuffle seed (default 7); same seed, same split order")
FLAGS.add_argument("--resume", action="store_true",  # T914
                   help="continue an interrupted run from OUT/checkpoint_latest + "
                        "train_state.json + optim.pt (written every epoch). NOTE: "
                        "in-memory best weights don't survive a crash — if the "
                        "resumed run never beats the restored best_dev, the "
                        "shipped checkpoint is the last epoch, not the best")
_known, _rest = FLAGS.parse_known_args()  # tolerate Kaggle's own argv noise
MAX_SAMPLES = _known.max_samples
DRY_RUN = _known.dry_run
EPOCHS_FLAG = _known.epochs
LR_FLAG = _known.lr
SEED = _known.seed
RESUME = _known.resume

# --- T652: the only block you edit for adapter runs ---
# target_modules must match YOUR encoder's attention projections.
# This model's encoder is ModernBERT-large (answerdotai/ModernBERT-large per
# rl_agent_config.json — a bert-style encoder, so train.py builds `encoder.`
# params), whose attention projections are query/value (T912). The llama-style
# q_proj/v_proj that shipped here before would match ZERO modules — peft would
# wrap nothing and an "adapter run" would train no adapter at all; a wrong
# value sitting disabled is worse than an absent one (someone WILL enable it),
# so the shipped names now match the shipped encoder.
LORA = {"enabled": False, "r": 8, "alpha": 16, "dropout": 0.05,
        "target_modules": ["query", "value"]}

DEV_FLOOR = 0.35  # T655: below this, the checkpoint is not worth shipping
REGEX_FLOOR = 0.403  # T661: regex baseline on examples.jsonl (post-T637; was 0.480)
                     # T920: must equal gate.py's rule-acc threshold default — the
                     # ship gate invokes gate.py with NO threshold flags, so
                     # this number and gate.py's floor are one source, pinned
                     # equal by test_p48 (drift fails the suite, not a push)
HARM = ["safe", "suspicious", "harmful"]
HYPE = ["dead", "chill", "hyped"]
OUT = "/kaggle/working/bouncer-421m"
LOG = os.path.join(OUT, "train_log.jsonl")  # T654: loss trail, no wandb required
t0 = None  # training clock — set in main() when the epochs start (T911). Records
           # written before that (the T924 data-gate receipt, the --resume record)
           # carry t: null — the clock genuinely has not started yet; log_rec must
           # not crash on t0=None, which is what it did when t0 was assumed set.
PROVENANCE = {}  # T916: {dataset_sha256, git_sha, config} — stamped into every
                 # log_rec line once the run knows its inputs, so any number in
                 # the trail can be traced back to data + code + knobs


def fill_provenance(data_path):  # T916
    """Hash the dataset that was actually read + record the code revision and
    the knobs. Honest fallbacks, never fake values: unreadable file -> no
    dataset hash (not an empty one), no git -> None (a Kaggle kernel has no
    .git), config always present (it is knowable anywhere)."""
    digest = None
    try:
        h = hashlib.sha256()
        with open(data_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()
    except OSError:
        pass  # provenance must never crash a training run
    git_sha = None
    try:
        g = subprocess.run(["git", "rev-parse", "HEAD"], check=False,
                           capture_output=True, text=True, timeout=10)
        if g.returncode == 0:
            git_sha = g.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass  # kernel without git — None beats a stale or invented sha
    PROVENANCE.clear()
    PROVENANCE.update({
        "dataset_path": os.path.basename(data_path),
        "dataset_sha256": digest,
        "git_sha": git_sha,
        "config": {"max_samples": MAX_SAMPLES, "epochs": EPOCHS_FLAG,
                   "lr": LR_FLAG, "seed": SEED, "resume": RESUME,
                   "lora": dict(LORA), "dev_floor": DEV_FLOOR,
                   "regex_floor": REGEX_FLOOR},
    })


def to_row(r):
    s, lab = r["state"], r["labels"]
    crit = dict(s["rules"])
    crit["ok"] = "message follows all rules"
    return {"state": s,
            "questions": {
                "rule": {"type": "choice", "instructions": "Which rule violated? ok if none.",
                         "criteria": crit},
                "harm": {"type": "score", "instructions": "Harm level?", "criteria": HARM},
                "hype": {"type": "score", "instructions": "Hype level?", "criteria": HYPE},
                "jailbreak": {"type": "noul", "instructions": "Prompt injection?"},
                "escalate": {"type": "noul", "instructions": "Needs human?"},
            },
            "expected": {"rule": lab["rule"], "harm": HARM.index(lab["harm"]),
                         "hype": HYPE.index(lab["hype"]),
                         "jailbreak": lab["jailbreak"], "escalate": lab["escalate"]}}


def dev_rule_acc(ckpt, rows_dev):  # T653: early-stopping signal, not the final number
    import laya
    agent = laya.Agent(ckpt, device="cuda")
    ok = 0
    for r in rows_dev:
        c = to_row(r)
        pred = agent.predict(c["state"], c["questions"])["answers"]["rule"]["choice"]
        ok += pred == r["labels"]["rule"]
    return ok / len(rows_dev)


def find_validate_data():  # T924: where the schema checker may live
    """validate_data.py beside this script, in the repo's eval/, or in a Kaggle
    kernel input — same reachability question the ship gate asks (T915)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return next((os.path.join(d, "validate_data.py") for d in
                 [here, os.path.join(here, "..", "..", "eval")]
                 + glob.glob("/kaggle/input/**", recursive=True)
                 if os.path.exists(os.path.join(d, "validate_data.py"))), None)


def data_gate(path):  # T924: schema + published hash refuse BEFORE training starts
    """Receipt for 'may training start?': validate_data's full-file schema check
    plus the publisher's hash pin. Both must pass — a checker that can't be
    found is a problem, not a pass (same rule as the ship gate, T915), and a
    .sha256 sidecar that doesn't match means this is NOT the dataset that was
    published, so what else drifted? An absent sidecar records 'absent': there
    was nothing to compare against, and pretending it matched would be a lie.

    Runs BEFORE rows are parsed: check_file reports bad JSON as an error per
    row, while raw json.loads would just crash with a traceback."""
    vd = find_validate_data()
    if vd is None:
        return {"problems": [("validate_data.py not reachable — add the repo as a "
                              "kernel input (T924): schema gate cannot run")],
                "pin": "not checked"}
    spec = importlib.util.spec_from_file_location("validate_data", vd)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    problems = [f"schema: {e}" for e in mod.check_file(path)]

    pin = "absent"
    pin_path = path + ".sha256"
    if os.path.exists(pin_path):
        try:
            with open(pin_path) as f:
                want = f.read().split()[0].lower()
        except OSError as e:
            return {"problems": problems + [f"pin unreadable: {e}"],
                    "pin": "unreadable"}
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        got = h.hexdigest()
        if got == want:
            pin = "match"
        else:
            pin = "mismatch"
            problems.append(
                f"hash mismatch: dataset sha256 {got[:12]} != published {want[:12]} "
                f"({os.path.basename(pin_path)}) — not the dataset that was "
                "published; re-run scripts/upload_dataset_kaggle.py --yes")
    return {"problems": problems, "pin": pin}


def log_rec(**kw):  # T654: append-only JSONL — one object per line
    kw.setdefault("t", None if t0 is None else round(time.time() - t0, 1))
    for k, v in PROVENANCE.items():  # T916: every record is traceable to its inputs
        kw.setdefault(k, v)
    os.makedirs(os.path.dirname(LOG) or ".", exist_ok=True)  # T924: the trail can
    with open(LOG, "a") as f:                               # open before any ckpt
        f.write(json.dumps(kw) + "\n")


def validate_config():  # T911: what a dry run can honestly check without a GPU
    """Config problems detectable on any machine — the knobs a human edits
    (LORA block, floors, smoke flag) checked BEFORE quota is spent. Data and
    weights are validated at training start (T924), not here: a dry run
    refuses to pretend it saw a dataset it cannot see."""
    problems = []
    if MAX_SAMPLES < 0:
        problems.append(f"--max-samples must be >= 0 (got {MAX_SAMPLES})")
    if EPOCHS_FLAG < 0:  # T913: 0 means "default", negative is nonsense
        problems.append(f"--epochs must be >= 0 (got {EPOCHS_FLAG})")
    if LR_FLAG < 0:  # T913: 0 means "default", negative is nonsense
        problems.append(f"--lr must be >= 0 (got {LR_FLAG})")
    if LORA["enabled"]:  # only validate the adapter knobs when they're live
        if LORA["r"] < 1:
            problems.append(f"LORA.r must be >= 1 (got {LORA['r']})")
        if LORA["alpha"] <= 0:
            problems.append(f"LORA.alpha must be > 0 (got {LORA['alpha']})")
        if not 0 <= LORA["dropout"] < 1:
            problems.append(f"LORA.dropout must be in [0, 1) (got {LORA['dropout']})")
        mods = LORA["target_modules"]
        if not isinstance(mods, list) or not mods or not all(
                isinstance(m, str) and m for m in mods):
            problems.append("LORA.target_modules must be a non-empty list of module "
                            "names (query/value for bert-style encoders)")
    for name, floor in (("DEV_FLOOR", DEV_FLOOR), ("REGEX_FLOOR", REGEX_FLOOR)):
        if not 0 < floor <= 1:
            problems.append(f"{name} must be in (0, 1] (got {floor})")
    return problems


def write_model_card(out_dir, best_dev, test_acc, gate_pass):  # T917
    """Generate the README.md that the HF upload ships along with the weights —
    until now the repo got a folder of checkpoints and NO card. Source-true by
    construction: metrics come from this run's variables, provenance from the
    T916 record, and the held-out distribution caveat stays in (a card that
    oversells synthetic-distribution accuracy would be the dishonest artifact
    this repo refuses to ship)."""
    prov = PROVENANCE or {}
    cfg = prov.get("config") or {}
    card = [
        "# bouncer-421m",
        "",
        "Fine-tuned moderation checkpoint for the bouncer/gatekeeper engine,",
        "trained from convaiinnovations/laya (ModernBERT-large encoder + RLCD head).",
        "",
        "## Intended use",
        "",
        ("Drop-in router checkpoint for the bouncer engine "
        "(`BOUNCER_MODEL_DIR=/path/to/bouncer-421m`). Decides rule/harm/hype/"),
        "jailbreak/escalate per message. Not a chat model, not an alignment claim.",
        "",
        "## Run metrics (this run, not documentation)",
        "",
        f"- dev rule_acc: {best_dev:.3f} (ship floor {DEV_FLOOR})",
        f"- held-out test rule_acc: {test_acc:.3f} (regex floor {REGEX_FLOOR})",
        (f"- full gate.py thresholds (rule_acc/ECE/latency/abstention/per-rule): "
        f"{'PASS' if gate_pass else 'FAIL or not run — this checkpoint was not pushed'}"),
        "",
        ("Held-out rows come from the same synthetic distribution as training "
        "(data/synth_rules.py) — transfer to open chat is unmeasured."),
        "",
        "## Provenance",
        "",
        f"- dataset: {prov.get('dataset_path')} sha256 `{prov.get('dataset_sha256')}`",
        f"- code: `{prov.get('git_sha')}` (null = kernel without git)",
        (f"- knobs: epochs={cfg.get('epochs') or 'default'} "
        f"lr={cfg.get('lr') or 'default'} seed={cfg.get('seed')} "
        f"max_samples={cfg.get('max_samples')} "
        f"resume={cfg.get('resume')} lora_enabled={cfg.get('lora', {}).get('enabled')}"),
        "",
        "Generated by kaggle/train/train.py (T917) on every run — not hand-edited.",
        "",
    ]
    card_path = os.path.join(out_dir, "README.md")
    with open(card_path, "w") as f:
        f.write("\n".join(card))
    return card_path


def main():  # T911: every GPU/network/data step lives behind this guard
    global t0
    if DRY_RUN:
        problems = validate_config()
        for p in problems:
            print("DRY_RUN_FAIL:", p, file=sys.stderr)
        if not problems:
            print(f"DRY_RUN_OK max_samples={MAX_SAMPLES} lora_enabled={LORA['enabled']} "
                  f"epochs={EPOCHS_FLAG or '(default)'} lr={LR_FLAG or '(default)'} "
                  f"seed={SEED} dev_floor={DEV_FLOOR} regex_floor={REGEX_FLOOR}")
        return 2 if problems else 0

    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                    "laya>=0.1.6", "transformers>=4.48.0", "datasets>=3.0.0",
                    "safetensors", "huggingface_hub", "accelerate"], check=True)

    import torch

    assert torch.cuda.is_available(), "needs GPU — wait for quota reset"
    device = torch.device("cuda")

    # --- rows: gatekeeper jsonl -> {state, questions, expected} (T651: assert each stage) ---
    paths = glob.glob("/kaggle/input/**/*.jsonl", recursive=True)
    assert paths, "no /kaggle/input/**/*.jsonl — upload the dataset first (T657)"
    fill_provenance(paths[0])  # T916: hash THIS file — the T924 receipt carries it too
    gate = data_gate(paths[0])  # T924: schema + hash pin BEFORE anything trains
    for p in gate["problems"]:
        print("DATA_GATE:", p, file=sys.stderr, flush=True)
    log_rec(kind="data_gate", pin=gate["pin"], refused=bool(gate["problems"]))  # receipt
    if gate["problems"]:  # refusal is loud and refuses TRAINING, not just push
        print(f"DATA_GATE: refusing to train — {len(gate['problems'])} problem(s), "
              f"hash pin={gate['pin']} (T924)", file=sys.stderr, flush=True)
        return 1
    with open(paths[0]) as f:
        rows_raw = [json.loads(line) for line in f]
    assert len(rows_raw) >= 2000, f"need 2000 rows (1500 train + 500 test), got {len(rows_raw)}"
    sample = rows_raw[0]
    assert "state" in sample and "labels" in sample, "row schema mismatch (T386)"
    assert isinstance(sample["state"].get("rules"), dict) and sample["state"]["rules"], \
        "state.rules must be a non-empty mapping"
    assert set(sample["labels"]) >= {"rule", "harm", "hype", "jailbreak", "escalate"}, \
        "labels missing heads"
    random.seed(SEED)
    random.shuffle(rows_raw)  # T913: --seed makes the order reproducible
    if MAX_SAMPLES:  # T658: smoke path — data must still be complete on disk (asserts above)
        rows_raw = rows_raw[:MAX_SAMPLES]
    if len(rows_raw) < 2000:  # T658: smoke split ~80/10/10 when truncated
        cut = max(1, int(len(rows_raw) * 0.8))
        dev_cut = min(len(rows_raw), cut + max(1, len(rows_raw) // 10))
        train_rows, dev_rows, test_rows = rows_raw[:cut], rows_raw[cut:dev_cut], rows_raw[dev_cut:]
    else:
        train_rows, test_rows = rows_raw[:1500], rows_raw[1500:2000]
        train_rows, dev_rows = train_rows[:-200], train_rows[-200:]  # T653: dev from train tail
    assert train_rows and dev_rows and test_rows, "split left an empty part"

    from huggingface_hub import snapshot_download
    from laya.agent import _fix_tokenizer_config
    from laya.train import items_from_rows
    from transformers import AutoTokenizer

    model_dir = snapshot_download("convaiinnovations/laya")
    _fix_tokenizer_config(model_dir)
    tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, "tokenizer"))
    with open(os.path.join(model_dir, "rl_agent_config.json")) as f:
        cfg = json.load(f)
    cfg.update({"gradient_checkpointing": True, "max_tokens_per_batch": 4096,
                "max_len": 1024, "head_max_len": 256})

    items, skipped = items_from_rows(tok, [to_row(r) for r in train_rows],
                                     cfg["max_len"], cfg["head_max_len"])
    print(f"ITEMS={len(items)} SKIPPED={skipped}", flush=True)
    assert items, "tokenizer produced zero items — check max_len/head_max_len"
    assert skipped < len(train_rows) * 0.5, \
        f"skipped {skipped}/{len(train_rows)} rows — malformed data?"

    # --- single-GPU RLCD (same canonical fns as train_ddp.py) ---
    from laya.calibrate import fit_temperature_map
    from laya.common import build_model, collate_items
    from laya.train import (
        calibration_records,
        encode_item,
        rlcd_loss,
        save_checkpoint,
        sigma_at,
        split_calibration,
    )
    from safetensors.torch import load_file

    model = build_model(cfg, encoder_dir=os.path.join(model_dir, "encoder"))
    model.load_state_dict(load_file(os.path.join(model_dir, "model.safetensors")), strict=True)
    assert any("encoder." in n for n, _ in model.named_parameters()), \
        "no encoder params — wrong build?"
    model.encoder.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False})
    if LORA["enabled"]:  # T652: adapter run — train ~1% of params, not the full model
        from peft import LoraConfig, get_peft_model
        model = get_peft_model(model, LoraConfig(
            r=LORA["r"], lora_alpha=LORA["alpha"], lora_dropout=LORA["dropout"],
            target_modules=LORA["target_modules"]))
        model.print_trainable_parameters()
    model.head_checkpointing = True
    model.to(device).train()

    train_items, calib_items = split_calibration(items, calib_max=400, calib_frac=0.1,
                                                 seed=20260922)
    assert train_items and calib_items, "empty train or calibration split"
    EPOCHS = EPOCHS_FLAG or (1 if MAX_SAMPLES else 3)  # T659+T913: smoke=1 epoch, flag overrides
    MICRO, ACCUM = 8, 8  # eff batch 64, same as 2xT4 recipe
    PATIENCE = 1  # T653: stop after N epochs without dev rule_acc improvement
    assert len(train_items) >= MICRO, "fewer items than one micro-batch"
    enc_p = [p for n, p in model.named_parameters() if "encoder." in n and p.requires_grad]
    head_p = [p for n, p in model.named_parameters()
              if "encoder." not in n and p.requires_grad]  # T652: LoRA-safe
    opt = torch.optim.AdamW([{"params": enc_p, "lr": LR_FLAG or 2.5e-5},
                             {"params": head_p, "lr": (LR_FLAG or 2.5e-5) * 4}],  # head4x encoder
                            weight_decay=0.01)  # T913: --lr scales both, ratio kept
    total = (len(train_items) // (MICRO * ACCUM)) * EPOCHS
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, total), eta_min=1e-6)
    scaler = torch.amp.GradScaler("cuda", enabled=True)
    best_state, best_dev, wait, start_epoch = None, 0.0, 0, 0  # T653: early-stopping state
    if RESUME:  # T914: pick up where the crash left off — no quota burned twice
        resume_dir = os.path.join(OUT, "checkpoint_latest")
        st_path = os.path.join(OUT, "train_state.json")
        assert os.path.isdir(resume_dir) and os.path.exists(st_path), \
            "--resume needs checkpoint_latest + train_state.json in OUT (nothing to resume)"
        model.load_state_dict(load_file(os.path.join(resume_dir, "model.safetensors")),
                              strict=True)
        with open(st_path) as f:
            st = json.load(f)
        start_epoch, best_dev, wait = st["epoch"], st["best_dev"], st["wait"]
        opt_path = os.path.join(OUT, "optim.pt")
        if os.path.exists(opt_path):  # optimizer/scheduler/scaler pick up their momentum
            blob = torch.load(opt_path, map_location="cpu", weights_only=True)
            opt.load_state_dict(blob["opt"])
            sched.load_state_dict(blob["sched"])
            scaler.load_state_dict(blob["scaler"])
        print(f"RESUME from epoch {start_epoch} best_dev={best_dev:.3f} wait={wait}",
              flush=True)
        log_rec(kind="resume", epoch=start_epoch, best_dev=round(best_dev, 4), wait=wait)
    t0 = time.time()

    for epoch in range(start_epoch, EPOCHS):
        random.seed(42 + epoch)
        random.shuffle(train_items)
        sigma, eloss, nb = sigma_at(epoch, EPOCHS, 0.4, 0.1), 0.0, 0
        opt.zero_grad(set_to_none=True)
        for step, b in enumerate(range(0, len(train_items), MICRO)):
            acc = step + 1
            chunk = train_items[b:b + MICRO]
            enc = [encode_item(tok, it, cfg["max_len"], cfg["head_max_len"]) for it in chunk]
            bt = collate_items([enc], tok.pad_token_id)
            with torch.autocast("cuda", dtype=torch.float16):
                logits, _ = model(bt["input_ids"].to(device), bt["attention_mask"].to(device),
                                  bt["marker_pos"].to(device), bt["marker_mask"].to(device),
                                  bt["qtype"].to(device))
            loss = rlcd_loss(logits.float(), bt["target"].to(device), bt["marker_mask"].to(device),
                             bt["qtype"].to(device), sigma, samples=4, w_sph=0.75, w_rps=1.0)
            scaler.scale(loss / ACCUM).backward()
            eloss += float(loss)
            nb += 1
            if acc % ACCUM == 0 or (b + MICRO) >= len(train_items):
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt)
                scaler.update()
                sched.step()
                opt.zero_grad(set_to_none=True)
            if nb % 50 == 0:
                print(f"ep{epoch+1}/{EPOCHS} step{nb} loss={float(loss):.4f}", flush=True)
                log_rec(kind="step", epoch=epoch + 1, step=nb, loss=round(float(loss), 4))
        save_checkpoint(model, tok, dict(cfg), os.path.join(OUT, "checkpoint_latest"))
        print(f"EPOCH {epoch+1} done in {time.time()-t0:.0f}s avg={eloss/max(1,nb):.4f}",
              flush=True)
        dev_acc = dev_rule_acc(os.path.join(OUT, "checkpoint_latest"), dev_rows)
        print(f"EP{epoch+1} dev_rule_acc={dev_acc:.3f} best={best_dev:.3f}", flush=True)
        log_rec(kind="epoch", epoch=epoch + 1, avg_loss=round(eloss / max(1, nb), 4),
                dev_rule_acc=round(dev_acc, 4), best_dev=round(best_dev, 4))
        if dev_acc > best_dev:  # T653: remember the best epoch on CPU (VRAM is precious)
            best_dev, wait = dev_acc, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            wait += 1
        # T914: resume bookkeeping — written AFTER the patience update so a
        # resumed run continues with the exact early-stopping state; the
        # optimizer momenta land in optim.pt beside it
        with open(os.path.join(OUT, "train_state.json"), "w") as f:
            json.dump({"epoch": epoch + 1, "best_dev": round(best_dev, 4), "wait": wait}, f)
        torch.save({"opt": opt.state_dict(), "sched": sched.state_dict(),
                    "scaler": scaler.state_dict()}, os.path.join(OUT, "optim.pt"))
        if wait >= PATIENCE:
            print(f"EARLY_STOP at epoch {epoch+1}: no dev improvement in "
                  f"{PATIENCE} epoch(s); best dev={best_dev:.3f}", flush=True)
            log_rec(kind="early_stop", epoch=epoch + 1, best_dev=round(best_dev, 4))
            break

    # --- calibrate + save ---
    if best_state is not None:  # T653: ship the best epoch, not the last
        model.load_state_dict(best_state, strict=False)
    model.eval()
    try:
        recs = calibration_records(model, tok, calib_items, device, cfg["max_len"],
                                   cfg["head_max_len"], batch_size=16)
        fit = fit_temperature_map(recs)
        cfg["temperature"] = fit["temperature"]
        cfg.pop("temperature_by_options", None)
        if fit["temperature_by_options"]:
            cfg["temperature_by_options"] = fit["temperature_by_options"]
        print("TEMPS:", [round(t, 3) for t in fit["temperature"]], flush=True)
    except Exception as e:  # noqa: BLE001 — keep base temps on fit failure
        print("temp fallback:", e, flush=True)
    cfg.update({"fine_tuned": True, "model_name": "bouncer-421m"})
    save_checkpoint(model, tok, cfg, OUT)
    # T662: calibration artifact — what the engine (and a human) can inspect later
    with open(os.path.join(OUT, "temp.json"), "w") as f:
        json.dump({"temperature": cfg.get("temperature", 1.0),
                   "temperature_by_options": cfg.get("temperature_by_options"),
                   "calib_items": len(calib_items),
                   "dev_rule_acc": round(best_dev, 4)}, f, indent=2)
    log_rec(kind="calibration", temperature=cfg.get("temperature", 1.0))

    # --- quick eval on held-out 500 ---
    import laya

    agent = laya.Agent(OUT, device="cuda")
    ok = gated_ok = gated_n = 0
    for r in test_rows:
        c = to_row(r)
        a = agent.predict(c["state"], c["questions"])["answers"]
        pred, conf = a["rule"]["choice"], float(a["rule"].get("confidence", 0))
        good = pred == r["labels"]["rule"]
        ok += good
        if conf >= 0.85:
            gated_n += 1
            gated_ok += good
    print(f"TEST n={len(test_rows)} rule_acc={ok/len(test_rows):.3f} "
          f"gate@0.85={gated_ok}/{gated_n}", flush=True)
    test_acc = ok / max(1, len(test_rows))  # T661: regression gate input
    log_rec(kind="test", n=len(test_rows), rule_acc=round(test_acc, 4),
            gate85=f"{gated_ok}/{gated_n}")  # T654: final number lands in the trail too

    # --- eval-after-train (T660): CI's own metrics on the held-out 500 ---
    # Kernels can't see the repo, so the split is always written OUT and
    # eval_gatekeeper.py runs when reachable (add the repo as a kernel input, or
    # run locally): python eval/eval_gatekeeper.py $OUT/test_split.jsonl --model $OUT
    test_path = os.path.join(OUT, "test_split.jsonl")
    with open(test_path, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in test_rows)
    _here = os.path.dirname(os.path.abspath(__file__))
    ev_script = next((p for p in [_here] + glob.glob("/kaggle/input/**", recursive=True)
                      if os.path.exists(os.path.join(p, "eval_gatekeeper.py"))), None)
    gate_pass = None  # T915: None = not run — never a green light, refuses push
    if ev_script:
        env = dict(os.environ)
        src = os.path.abspath(os.path.join(ev_script, "..", "src"))
        if os.path.isdir(src):
            env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        ev = subprocess.run([sys.executable, os.path.join(ev_script, "eval_gatekeeper.py"),
                             test_path, "--limit", "500",
                             "--out", os.path.join(OUT, "eval_test.json"), "--model", OUT],
                            env=env, check=False)
        log_rec(kind="eval_gatekeeper", returncode=ev.returncode)
        print("eval_gatekeeper on test split:",
              "OK" if ev.returncode == 0 else "FAILED", flush=True)
        # --- ship gate (T915): the FULL gate.py thresholds over that report ---
        # Same thresholds CI gates with (rule_acc floor, ECE ceiling, latency
        # budget, abstention band, per-rule floor) — passed via NO threshold
        # flags, so gate.py's defaults are the single source: a threshold
        # change in gate.py moves this gate automatically, no drift copy here.
        # The old two-number gate (dev + test_acc) could ship a model CI would
        # refuse. gate.py exit 0 = every applied gate passed (T677).
        gt = os.path.join(ev_script, "gate.py")
        if ev.returncode == 0 and os.path.exists(gt):
            g = subprocess.run([sys.executable, gt, os.path.join(OUT, "eval_test.json")],
                               env=env, check=False)
            gate_pass = g.returncode == 0
            log_rec(kind="gate", returncode=g.returncode, ok=gate_pass)
            print("ship gate (gate.py):", "PASS" if gate_pass else "FAIL", flush=True)
        else:
            print("ship gate (gate.py) NOT run — eval failed or gate.py unreachable; "
                  "the push below will refuse (T915)", flush=True)
    else:
        print("eval_gatekeeper.py not reachable — run locally:", flush=True)
        print(f"  python eval/eval_gatekeeper.py {test_path} --model {OUT}", flush=True)
        print("ship gate (gate.py) NOT run — the push below will refuse (T915)", flush=True)

    # --- model card (T917): the upload folder carries a README, source-true ---
    card = write_model_card(OUT, best_dev, test_acc, gate_pass)
    log_rec(kind="model_card", path=card, full_gate=gate_pass)
    print("MODEL_CARD:", card, flush=True)

    # --- HF push (needs HF_TOKEN in Kaggle Secrets) ---
    try:
        from kaggle_secrets import UserSecretsClient
        token = UserSecretsClient().get_secret("HF_TOKEN")
    except Exception:  # noqa: BLE001 — no secrets in this env
        token = None
    # T655+T661+T915: earn the ship
    if token and best_dev >= DEV_FLOOR and test_acc >= REGEX_FLOOR and gate_pass:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        api.create_repo("bouncer-421m", exist_ok=True)
        api.upload_folder(folder_path=OUT, repo_id=api.whoami()["name"] + "/bouncer-421m")
        print("PUSHED to HF", flush=True)
        log_rec(kind="push", dev_rule_acc=round(best_dev, 4), test_acc=round(test_acc, 4),
                full_gate="pass")
    elif token:
        print(f"gate failed: dev={best_dev:.3f} (floor {DEV_FLOOR}) "
              f"test_acc={test_acc:.3f} (regex floor {REGEX_FLOOR}) "
              f"full_gate={'pass' if gate_pass else 'fail/not-run'} — no push; weights "
              "stay in /kaggle/working output", flush=True)
        log_rec(kind="no_push", dev_rule_acc=round(best_dev, 4), test_acc=round(test_acc, 4),
                dev_floor=DEV_FLOOR, regex_floor=REGEX_FLOOR, full_gate=gate_pass)
    else:
        print("no HF_TOKEN — model stays in /kaggle/working output", flush=True)
    print("TRAIN_OK")


if __name__ == "__main__":
    sys.exit(main())
