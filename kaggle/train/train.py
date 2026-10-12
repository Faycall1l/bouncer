"""Full bouncer fine-tune, single-GPU adaptation of Laya's 2xT4 DDP script.
Needs GPU quota (30h/week). Rolling checkpoint per epoch + HF push via HF_TOKEN secret.
Smoke-validated: 7500/7500 items build clean (bouncer-smoke-cpu v6).
"""
import subprocess
import sys

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                "laya>=0.1.6", "transformers>=4.48.0", "datasets>=3.0.0",
                "safetensors", "huggingface_hub", "accelerate"], check=True)

import glob
import json
import os
import random
import time

import torch

assert torch.cuda.is_available(), "needs GPU — wait for quota reset"
device = torch.device("cuda")

# --- rows: gatekeeper jsonl -> {state, questions, expected} ---
HARM = ["safe", "suspicious", "harmful"]
HYPE = ["dead", "chill", "hyped"]
paths = glob.glob("/kaggle/input/**/*.jsonl", recursive=True)
with open(paths[0]) as f:
    rows_raw = [json.loads(line) for line in f]
random.seed(7); random.shuffle(rows_raw)
train_rows, test_rows = rows_raw[:1500], rows_raw[1500:2000]

def to_row(r):
    s, lab = r["state"], r["labels"]
    crit = dict(s["rules"]); crit["ok"] = "message follows all rules"
    return {"state": s,
            "questions": {
                "rule": {"type": "choice", "instructions": "Which rule violated? ok if none.", "criteria": crit},
                "harm": {"type": "score", "instructions": "Harm level?", "criteria": HARM},
                "hype": {"type": "score", "instructions": "Hype level?", "criteria": HYPE},
                "jailbreak": {"type": "noul", "instructions": "Prompt injection?"},
                "escalate": {"type": "noul", "instructions": "Needs human?"},
            },
            "expected": {"rule": lab["rule"], "harm": HARM.index(lab["harm"]), "hype": HYPE.index(lab["hype"]),
                         "jailbreak": lab["jailbreak"], "escalate": lab["escalate"]}}

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
OUT = "/kaggle/working/bouncer-421m"

items, skipped = items_from_rows(tok, [to_row(r) for r in train_rows],
                                 cfg["max_len"], cfg["head_max_len"])
print(f"ITEMS={len(items)} SKIPPED={skipped}", flush=True)

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
model.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
model.head_checkpointing = True
model.to(device).train()

train_items, calib_items = split_calibration(items, calib_max=400, calib_frac=0.1, seed=20260922)
EPOCHS, MICRO, ACCUM = 3, 8, 8  # eff batch 64, same as 2xT4 recipe
enc_p = [p for n, p in model.named_parameters() if "encoder." in n]
head_p = [p for n, p in model.named_parameters() if "encoder." not in n]
opt = torch.optim.AdamW([{"params": enc_p, "lr": 2.5e-5}, {"params": head_p, "lr": 1e-4}], weight_decay=0.01)
total = (len(train_items) // (MICRO * ACCUM)) * EPOCHS
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, total), eta_min=1e-6)
scaler = torch.amp.GradScaler("cuda", enabled=True)
t0 = time.time()

for epoch in range(EPOCHS):
    random.seed(42 + epoch); random.shuffle(train_items)
    sigma, eloss, nb = sigma_at(epoch, EPOCHS, 0.4, 0.1), 0.0, 0
    opt.zero_grad(set_to_none=True)
    for step, b in enumerate(range(0, len(train_items), MICRO)):
        acc = step + 1
        chunk = train_items[b:b + MICRO]
        enc = [encode_item(tok, it, cfg["max_len"], cfg["head_max_len"]) for it in chunk]
        bt = collate_items([enc], tok.pad_token_id)
        with torch.autocast("cuda", dtype=torch.float16):
            logits, _ = model(bt["input_ids"].to(device), bt["attention_mask"].to(device),
                              bt["marker_pos"].to(device), bt["marker_mask"].to(device), bt["qtype"].to(device))
        loss = rlcd_loss(logits.float(), bt["target"].to(device), bt["marker_mask"].to(device),
                         bt["qtype"].to(device), sigma, samples=4, w_sph=0.75, w_rps=1.0)
        scaler.scale(loss / ACCUM).backward()
        eloss += float(loss); nb += 1
        if acc % ACCUM == 0 or (b + MICRO) >= len(train_items):
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt); scaler.update(); sched.step()
            opt.zero_grad(set_to_none=True)
        if nb % 50 == 0:
            print(f"ep{epoch+1}/{EPOCHS} step{nb} loss={float(loss):.4f}", flush=True)
    save_checkpoint(model, tok, dict(cfg), os.path.join(OUT, "checkpoint_latest"))
    print(f"EPOCH {epoch+1} done in {time.time()-t0:.0f}s avg={eloss/max(1,nb):.4f}", flush=True)

# --- calibrate + save ---
model.eval()
try:
    recs = calibration_records(model, tok, calib_items, device, cfg["max_len"], cfg["head_max_len"], batch_size=16)
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
        gated_n += 1; gated_ok += good
print(f"TEST n={len(test_rows)} rule_acc={ok/len(test_rows):.3f} gate@0.85={gated_ok}/{gated_n}", flush=True)

# --- HF push (needs HF_TOKEN in Kaggle Secrets) ---
try:
    from kaggle_secrets import UserSecretsClient
    token = UserSecretsClient().get_secret("HF_TOKEN")
except Exception:  # noqa: BLE001 — no secrets in this env
    token = None
if token:
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    api.create_repo("bouncer-421m", exist_ok=True)
    api.upload_folder(folder_path=OUT, repo_id=api.whoami()["name"] + "/bouncer-421m")
    print("PUSHED to HF", flush=True)
else:
    print("no HF_TOKEN — model stays in /kaggle/working output", flush=True)
print("TRAIN_OK")
