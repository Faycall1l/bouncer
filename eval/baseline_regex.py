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
    path = sys.argv[1] if len(sys.argv) > 1 else "data/examples.jsonl"
    with open(path) as f:
        rows = [json.loads(line) for line in f]
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
