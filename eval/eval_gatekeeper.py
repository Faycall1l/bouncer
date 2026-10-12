"""Eval: accuracy(rule), MAE(harm/hype), ECE, gate precision@0.85, p50 latency."""
import json, time, sys
from gatekeeper import get_router, build_questions

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
    rows = [json.loads(l) for l in open(path)][:500]
    r = get_router()
    ok, confs, golds, lat, gated_ok, gated_n = 0, [], [], [], 0, 0
    t0 = time.time()
    for row in rows:
        s, lab = row["state"], row["labels"]
        t = time.time()
        out = r.predict(s, build_questions(s["rules"]))["answers"]
        lat.append((time.time()-t)*1000)
        pred = out["rule"]["choice"]; conf = float(out["rule"]["confidence"])
        ok += pred == lab["rule"]; confs.append(conf); golds.append(pred == lab["rule"])
        if conf >= 0.85:
            gated_n += 1; gated_ok += pred == lab["rule"]
    lat.sort()
    report = {"n": len(rows), "rule_acc": round(ok / len(rows), 3),  # T100: JSON report
              "ece": round(ece(confs, golds), 3), "p50_ms": round(lat[len(lat) // 2], 1),
              "gate": {"prec": round(gated_ok / max(1, gated_n), 3), "n": gated_n}}
    import os
    os.makedirs("eval/reports", exist_ok=True)
    with open("eval/reports/zero-shot.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
