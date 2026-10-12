"""CPU smoke: validates gatekeeper rows via items_from_rows (tokenizer only, no weights)."""
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                "laya>=0.1.6", "transformers>=4.48.0",
                "huggingface_hub"], check=True)

import json, glob, random, os
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
from laya.agent import _fix_tokenizer_config
from laya.train import items_from_rows

print("INPUT_TREE:", os.listdir("/kaggle/input") if os.path.exists("/kaggle/input") else "NO_INPUT_DIR")
paths = glob.glob("/kaggle/input/**/*.jsonl", recursive=True)
print("FOUND:", paths)
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
            "expected": {"rule": lab["rule"], "harm": HARM.index(lab["harm"]), "hype": HYPE.index(lab["hype"]),
                         "jailbreak": lab["jailbreak"], "escalate": lab["escalate"]}}  # score = level index (laya list-criteria)

cands = [to_row(r) for r in rows_raw]
model_dir = snapshot_download("convaiinnovations/laya")
_fix_tokenizer_config(model_dir)
tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, "tokenizer"))
cfg = json.load(open(os.path.join(model_dir, "rl_agent_config.json")))
items, skipped = items_from_rows(tok, cands, cfg["max_len"], cfg["head_max_len"])
print(f"ITEMS={len(items)} SKIPPED={skipped}")
assert len(items) >= 7000, "too few items — format mismatch?"
print("CPU_SMOKE_OK")
