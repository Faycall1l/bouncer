"""T102: zero-shot base-Laya eval on gatekeeper data, CPU. Prints JSON report."""
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                "laya>=0.1.6", "transformers>=4.48.0", "huggingface_hub"], check=True)

import json, glob, random, time
from collections import Counter
from laya import Router

paths = glob.glob("/kaggle/input/**/*.jsonl", recursive=True)
rows = [json.loads(l) for l in open(paths[0])]
random.seed(11); random.shuffle(rows)
rows = rows[:200]

router = Router()
ok = gated_ok = gated_n = over = 0
confs, golds, lats, pairs = [], [], [], Counter()
for row in rows:
    s, lab = row["state"], row["labels"]
    crit = dict(s["rules"]); crit["ok"] = "message follows all rules"
    qs = {"rule": {"type": "choice", "instructions": "Which rule violated? ok if none.",
                   "criteria": crit}}
    t = time.time()
    a = router.predict({"message": s["message"], "rules": s["rules"]}, qs)["answers"]
    lats.append((time.time() - t) * 1000)
    pred, conf = a["rule"]["choice"], float(a["rule"].get("confidence", 0))
    good = pred == lab["rule"]
    ok += good; confs.append(conf); golds.append(good)
    if not good:
        pairs[(lab["rule"], pred)] += 1
    if conf >= 0.9 and not good:
        over += 1
    if conf >= 0.85:
        gated_n += 1; gated_ok += good
lats.sort()
print(json.dumps({"n": len(rows), "rule_acc": round(ok / len(rows), 3),
                  "p50_ms": round(lats[len(lats)//2], 1),
                  "gate_prec": round(gated_ok / max(1, gated_n), 3), "gate_n": gated_n,
                  "overconf": over, "top_confusions": pairs.most_common(5)}, indent=2))
print("EVAL_OK")
