"""Eval: accuracy(rule), MAE(harm/hype), ECE, gate precision@0.85, p50 latency."""
import json
import sys
import time

from gatekeeper import build_questions, get_router


def ece(probs, golds, n=10):
    import numpy as np
    probs, golds = np.array(probs), np.array(golds)
    e = 0.0
    for i in range(n):
        m = (probs >= i/n) & (probs < (i+1)/n)
        if m.sum(): e += abs(probs[m].mean() - golds[m].mean()) * m.mean()
    return float(e)

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/gatekeeper-12k.jsonl"
    with open(path) as f:
        rows = [json.loads(line) for line in f][:500]
    r = get_router()
    ok, confs, golds, lat, gated_ok, gated_n = 0, [], [], [], 0, 0
    from collections import Counter
    conf_pairs, overconf = Counter(), 0  # T104+T105
    per_rule, per_rule_ok = Counter(), Counter()  # T098
    t0 = time.time()
    for row in rows:
        s, lab = row["state"], row["labels"]
        t = time.time()
        out = r.predict(s, build_questions(s["rules"]))["answers"]
        lat.append((time.time()-t)*1000)
        pred = out["rule"]["choice"]; conf = float(out["rule"]["confidence"])
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
              "ece": round(ece(confs, golds), 3), "p50_ms": round(lat[len(lat) // 2], 1),
              "gate": {"prec": round(gated_ok / max(1, gated_n), 3), "n": gated_n},
              "top_confusions": [[list(k), v] for k, v in conf_pairs.most_common(5)],
              "overconfident_errors": overconf,
              "per_rule": {k: [per_rule_ok[k], per_rule[k]] for k in per_rule}}
    import os
    os.makedirs("eval/reports", exist_ok=True)
    with open("eval/reports/zero-shot.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
