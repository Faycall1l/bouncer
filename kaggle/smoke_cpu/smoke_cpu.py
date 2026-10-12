"""CPU smoke: validates gatekeeper rows via items_from_rows (tokenizer only, no weights)."""
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                "laya>=0.1.6", "transformers>=4.48.0",
                "huggingface_hub"], check=True)

import json, glob, random
from huggingface_hub import hf_hub_download
from transformers import AutoTokenizer
from laya.train import items_from_rows

paths = glob.glob("/kaggle/input/gatekeeper-chatmix-12k/*.jsonl")
assert paths, "dataset missing"
rows_raw = [json.loads(l) for l in open(paths[0])]
random.seed(7); random.shuffle(rows_raw)
rows_raw = rows_raw[:1500]

HARM = ["safe", "suspicious", "harmful"]
HYPE = ["dead", "chill", "hyped"]

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
            "expected": {"rule": lab["rule"], "harm": lab["harm"], "hype": lab["hype"],
                         "jailbreak": lab["jailbreak"], "escalate": lab["escalate"]}}

cands = [to_row(r) for r in rows_raw]
tok_dir = hf_hub_download("convaiinnovations/laya", "tokenizer/tokenizer.json")
import os
tok = AutoTokenizer.from_pretrained(os.path.dirname(tok_dir))
cfg = json.loads(open(hf_hub_download("convaiinnovations/laya", "rl_agent_config.json")).read())
items, skipped = items_from_rows(tok, cands, cfg["max_len"], cfg["head_max_len"])
print(f"ITEMS={len(items)} SKIPPED={skipped}")
assert len(items) >= 7000, "too few items — format mismatch?"
print("CPU_SMOKE_OK")
