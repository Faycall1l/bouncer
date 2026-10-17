"""Eval: accuracy(rule), MAE(harm/hype), ECE, gate precision@0.85, p50 latency."""
import datetime
import json
import time

from gatekeeper import GateConfig, get_router, moderate  # T209: dogfood moderate()


def write_latest(report, source, out_dir="eval/reports"):
    """T686: stable pointer to the newest report — `eval/reports/latest.json`
    (gitignored). A copy with provenance, not a symlink: rotated-away files
    can't break `gate.py eval/reports/latest.json`."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    doc = dict(report)
    doc["_source"] = source
    doc["_generated_at"] = datetime.datetime.now().astimezone().isoformat()
    with open(os.path.join(out_dir, "latest.json"), "w") as f:
        json.dump(doc, f, indent=2)


def ece(probs, golds, n=10):
    import numpy as np
    probs, golds = np.array(probs), np.array(golds)
    e = 0.0
    for i in range(n):
        m = (probs >= i/n) & (probs < (i+1)/n)
        if m.sum(): e += abs(probs[m].mean() - golds[m].mean()) * m.mean()
    return float(e)


def brier(probs, golds):  # T375
    import numpy as np
    probs, golds = np.array(probs), np.array(golds)
    return float(((probs - golds) ** 2).mean()) if len(probs) else 0.0

if __name__ == "__main__":
    import argparse  # T371
    ap = argparse.ArgumentParser(prog="eval_gatekeeper")
    ap.add_argument("path", nargs="?", default="data/gatekeeper-12k.jsonl")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--out", default="eval/reports/zero-shot.json")
    ap.add_argument("--model", default=None,  # T576: pin a checkpoint for the run
                    help="english | multilingual | typed-decisions (default: base router)")
    a = ap.parse_args()
    path = a.path
    with open(path) as f:
        rows = [json.loads(line) for line in f][:a.limit]
    r = get_router()
    cfg = GateConfig()
    ok, confs, golds, lat, gated_ok, gated_n = 0, [], [], [], 0, 0
    from collections import Counter
    actions = Counter()  # T373
    abstained_n = 0  # T374
    skipped = 0  # T378
    conf_pairs, overconf = Counter(), 0  # T104+T105
    conf_sums: dict = {}  # T376: pair -> sum of confs (for the mean)
    per_rule, per_rule_ok = Counter(), Counter()  # T098
    t0 = time.time()
    for row in rows:
        try:  # T378: malformed rows skew nothing; they get counted
            s, lab = row["state"], row["labels"]
            _msg, _rules = s["message"], s["rules"]
        except (KeyError, TypeError):
            skipped += 1
            continue
        res = moderate(s["message"], s["rules"], s.get("history"), config=cfg, router=r,
                       model=a.model)  # T576: None = base router, else pinned checkpoint
        lat.append(res.get("latency_ms", 0))
        actions[res["action"]] += 1  # T373
        abstained_n += bool(res.get("abstained"))  # T374
        pred = res["rule"]; conf = res["confidence"]
        good = pred == lab["rule"]
        ok += good; confs.append(conf); golds.append(good)
        per_rule[lab["rule"]] += 1; per_rule_ok[lab["rule"]] += good  # T098
        if not good:
            conf_pairs[(lab["rule"], pred)] += 1
            conf_sums[(lab["rule"], pred)] = conf_sums.get((lab["rule"], pred), 0) + conf  # T376
        if conf >= 0.9 and not good:
            overconf += 1
        if conf >= 0.85:
            gated_n += 1; gated_ok += good
    lat.sort()
    report = {"n": len(rows), "rule_acc": round(ok / len(rows), 3),  # T100: JSON report
              "model": a.model or "base-router",  # T576+T583: which checkpoint ran
              "thresholds": {"allow": cfg.allow_threshold,  # T372
                             "delete": cfg.delete_threshold},
              "ece": round(ece(confs, golds), 3), "p50_ms": round(lat[len(lat) // 2], 1),
              "p95_ms": round(lat[int(len(lat) * 0.95)], 1),  # T377
              "brier": round(brier(confs, golds), 3),  # T375
              "gate": {"prec": round(gated_ok / max(1, gated_n), 3), "n": gated_n},
              "actions": dict(sorted(actions.items())),  # T373
              "abstention_rate": round(abstained_n / len(rows), 3),  # T374
              "skipped": skipped,  # T378
              "top_confusions": [[list(k), v,  # T376: + mean conf
                                    round(conf_sums[k] / v, 2)] for k, v in
                                   conf_pairs.most_common(5)],
              "overconfident_errors": overconf,
              "per_rule": {k: [per_rule_ok[k], per_rule[k]] for k in per_rule}}
    import os
    os.makedirs("eval/reports", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(report, f, indent=2)
    write_latest(report, a.out)  # T686: eval/reports/latest.json pointer
    print(json.dumps(report, indent=2))
