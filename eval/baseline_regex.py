"""T210: regex baseline vs labels on data/examples.jsonl. No weights needed."""
import json
import sys

sys.path.insert(0, "src")
from gatekeeper.normalize import caps_flood, emoji_flood, extract_links


def baseline(msg):
    if extract_links(msg):
        return "no-spam"
    if caps_flood(msg) or emoji_flood(msg):
        return "chill-violation"
    return "ok"


if __name__ == "__main__":
    import argparse  # T380
    ap = argparse.ArgumentParser(prog="baseline_regex")
    ap.add_argument("path", nargs="?", default="data/examples.jsonl")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=0)  # T577: first N rows only
    a = ap.parse_args()
    path = a.path
    with open(path) as f:
        rows = [json.loads(line) for line in f]
    if a.limit:  # T577
        rows = rows[:a.limit]
    if not rows:  # T577: empty slice shouldn't divide by zero
        print("n=0 regex_acc=nan (no rows)")
        raise SystemExit(0)
    from collections import Counter
    per_label, per_hit = Counter(), Counter()  # T379
    hit, n_violation = 0, 0
    for r in rows:
        lab = r["labels"]["rule"]
        pred = baseline(r["state"]["message"])
        per_label[lab] += 1
        good = (pred == "ok") if lab == "ok" else (pred != "ok")
        per_hit[lab] += good
        if lab == "ok":
            hit += pred == "ok"
        else:
            n_violation += 1
            hit += pred != "ok"
    print(f"n={len(rows)} regex_acc={hit / len(rows):.3f} (violations={n_violation})")
    for lab in sorted(per_label):  # T379
        print(f"  {lab}: {per_hit[lab]}/{per_label[lab]}")
    if a.json:  # T380
        print(json.dumps({"n": len(rows), "regex_acc": round(hit / len(rows), 3),
                          "per_label": {k: [per_hit[k], per_label[k]]
                                        for k in sorted(per_label)}}))
