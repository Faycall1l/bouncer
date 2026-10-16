"""Eval: accuracy(rule), MAE(harm/hype), ECE, gate precision@0.85, p50 latency."""
import json
import sys
import time

from gatekeeper import GateConfig, get_router, moderate  # T209: dogfood moderate()


def ece(probs, golds, n=10):
    import numpy as np
    probs, golds = np.array(probs), np.array(golds)
    e = 0.0
    for i in range(n):
        m = (probs >= i/n) & (probs < (i+1)/n)
        if m.sum(): e += abs(probs[m].mean() - golds[m].mean()) * m.mean()
    return float(e)

if __name__ == "__main__":
    import argparse  # T371
    ap = argparse.ArgumentParser(prog="eval_gatekeeper")
    ap.add_argument("path", nargs="?", default="data/gatekeeper-12k.jsonl")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--out", default="eval/reports/zero-shot.json")
    a = ap.parse_args()
    path = a.path
    with open(path) as f:
        rows = [json.loads(line) for line in f][:a.limit]
    r = get_router()
    cfg = GateConfig()
    ok, confs, golds, lat, gated_ok, gated_n = 0, [], [], [], 0, 0
    from collections import Counter
    conf_pairs, overconf = Counter(), 0  # T104+T105
    per_rule, per_rule_ok = Counter(), Counter()  # T098
    t0 = time.time()
    for row in rows:
        s, lab = row["state"], row["labels"]
        res = moderate(s["message"], s["rules"], s.get("history"), config=cfg, router=r)
        lat.append(res.get("latency_ms", 0))
        pred = res["rule"]; conf = res["confidence"]
        good = pred == lab["rule"]
        ok += good; confs.append(conf); golds.append(good)
        per_rule[lab["rule"]] += 1; per_rule_ok[lab["rule"]] += good  # T098
        if not good:
            conf_pairs[(lab["rule"], pred)] += 1
        if conf >= 0.9 and not good:
            overconf += 1
        if conf >= 0.85:
            gated_n += 1; gated_ok += good
    lat.sort()
    report = {"n": len(rows), "rule_acc": round(ok / len(rows), 3),  # T100: JSON report
              "thresholds": {"allow": cfg.allow_threshold,  # T372
                             "delete": cfg.delete_threshold},
              "ece": round(ece(confs, golds), 3), "p50_ms": round(lat[len(lat) // 2], 1),
              "gate": {"prec": round(gated_ok / max(1, gated_n), 3), "n": gated_n},
              "top_confusions": [[list(k), v] for k, v in conf_pairs.most_common(5)],
              "overconfident_errors": overconf,
              "per_rule": {k: [per_rule_ok[k], per_rule[k]] for k in per_rule}}
    import os
    os.makedirs("eval/reports", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
