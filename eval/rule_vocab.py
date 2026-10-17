"""T642: rule-set vocabulary + unseen-K measurement across splits. No weights.

Given two JSONL files (e.g. train and test), reports:
  - rule ids seen in the second file but never the first (unseen rules)
  - rule-sets (servers) unseen in the first (unseen servers)
  - K (rules-per-row) values unseen in the first (unseen-K)
With one file, prints the file's own vocabulary.
"""
import argparse
import json
import sys
from collections import Counter


def vocab(rows: list) -> dict:
    rules, servers, k = Counter(), Counter(), Counter()
    for r in rows:
        ids = sorted(r["state"]["rules"])
        rules.update(ids)
        servers[tuple(ids)] += 1
        k[len(ids)] += 1
    return {"rows": len(rows), "rules": rules, "servers": servers, "k": k}


def compare(train_rows: list, test_rows: list) -> dict:
    a, b = vocab(train_rows), vocab(test_rows)
    unseen_servers = set(b["servers"]) - set(a["servers"])
    unseen_rows = sum(b["servers"][s] for s in unseen_servers)
    return {
        "train_rows": a["rows"], "test_rows": b["rows"],
        "n_rules": {"train": len(a["rules"]), "test": len(b["rules"])},
        "n_servers": {"train": len(a["servers"]), "test": len(b["servers"])},
        "unseen_servers": len(unseen_servers),
        "unseen_server_row_share": round(unseen_rows / (b["rows"] or 1), 3),
        "unseen_rules": sorted(set(b["rules"]) - set(a["rules"])),
        "k_train": {str(k): v for k, v in sorted(a["k"].items())},
        "k_test": {str(k): v for k, v in sorted(b["k"].items())},
        "unseen_k": sorted(set(b["k"]) - set(a["k"])),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rule_vocab")
    ap.add_argument("files", nargs="+", help="one file: own vocab; two: compare")
    ap.add_argument("--json", action="store_true", help="one-line output")
    a = ap.parse_args(argv)

    def load(path):
        with open(path) as f:
            return [json.loads(line) for line in f]

    if len(a.files) == 1:
        v = vocab(load(a.files[0]))
        rep = {"file": a.files[0], "rows": v["rows"],
               "rules": dict(v["rules"].most_common()),
               "servers": len(v["servers"]),
               "k": {str(k): n for k, n in sorted(v["k"].items())}}
    else:
        rep = compare(load(a.files[0]), load(a.files[1]))
    print(json.dumps(rep, indent=None if a.json else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
