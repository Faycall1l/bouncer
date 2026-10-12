"""Smoke kernel: validates gatekeeper rows against laya.train before the long run.
Fast (~15 min): pip install, build items via items_from_rows, 20-step single-GPU smoke train.
"""
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                "laya>=0.1.6", "transformers>=4.48.0", "datasets>=3.0.0",
                "safetensors", "huggingface_hub", "accelerate"], check=True)

import os, json, glob, random
import torch

# --- 1. load gatekeeper rows ---
paths = glob.glob("/kaggle/input/gatekeeper-chatmix-12k/*.jsonl")
assert paths, "dataset missing"
rows_raw = [json.loads(l) for l in open(paths[0])]
random.seed(7); random.shuffle(rows_raw)
rows_raw = rows_raw[:1500]

HARM = ["safe", "suspicious", "harmful"]
HYPE = ["dead", "chill", "hyped"]

def to_row(r):
    s, lab = r["state"], r["labels"]
    rules = s["rules"]
    crit = dict(rules); crit["ok"] = "message follows all rules"
    return {"state": s,
            "questions": {
                "rule": {"type": "choice", "instructions": "Which rule violated? ok if none.", "criteria": crit},
                "harm": {"type": "score", "instructions": "Harm level?", "criteria": HARM},
                "hype": {"type": "score", "instructions": "Hype level?", "criteria": HYPE},
                "jailbreak": {"type": "noul", "instructions": "Prompt injection?"},
                "escalate": {"type": "noul", "instructions": "Needs human?"},
            },
            "expected": {"rule": lab["rule"], "harm": lab["harm"], "hype": lab["hype"],
                         "jailbreak": lab["jailbreak"], "escalate": lab["escalate"]}}

cands = [to_row(r) for r in rows_raw]

# --- 2. base model + items ---
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
from laya.agent import _fix_tokenizer_config
from laya.train import items_from_rows

model_dir = snapshot_download("convaiinnovations/laya")
_fix_tokenizer_config(model_dir)
tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, "tokenizer"))
cfg = json.load(open(os.path.join(model_dir, "rl_agent_config.json")))
items, skipped = items_from_rows(tok, cands, cfg["max_len"], cfg["head_max_len"])
print(f"ITEMS={len(items)} SKIPPED={skipped}")
assert len(items) > 6000, "too few items — format mismatch?"

# --- 3. 20-step single-GPU smoke train ---
if not torch.cuda.is_available():
    print("NO_GPU — format validation passed, train smoke skipped")
    sys.exit(0)

from safetensors.torch import load_file
from laya.common import build_model, collate_items
from laya.train import encode_item, rlcd_loss

cfg["gradient_checkpointing"] = True
model = build_model(cfg, encoder_dir=os.path.join(model_dir, "encoder"))
model.load_state_dict(load_file(os.path.join(model_dir, "model.safetensors")), strict=True)
model.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
model.head_checkpointing = True
model.to("cuda").train()

opt = torch.optim.AdamW(model.parameters(), lr=2.5e-5)
random.shuffle(items)
losses = []
for i in range(0, 20 * 4, 4):
    chunk = items[i:i + 4]
    enc = [encode_item(tok, it, cfg["max_len"], cfg["head_max_len"]) for it in chunk]
    b = collate_items([enc], tok.pad_token_id)
    with torch.autocast("cuda", dtype=torch.float16):
        logits, _ = model(b["input_ids"].cuda(), b["attention_mask"].cuda(),
                          b["marker_pos"].cuda(), b["marker_mask"].cuda(), b["qtype"].cuda())
    loss = rlcd_loss(logits.float(), b["target"].cuda(), b["marker_mask"].cuda(),
                     b["qtype"].cuda(), 0.4, samples=2, w_sph=0.75, w_rps=1.0)
    opt.zero_grad(); loss.backward(); opt.step()
    losses.append(round(float(loss), 4))
    print(f"step {len(losses)}/20 loss={losses[-1]}", flush=True)
print("SMOKE_OK", losses[0], "->", losses[-1])
