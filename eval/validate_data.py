"""T381: schema checker for eval JSONL rows (state/rules/labels). No weights."""
import argparse
import json
import sys


def check_row(row: dict, i: int) -> list:
    errs = []
    if not isinstance(row, dict):
        return [f"row {i}: not an object"]
    s, lab = row.get("state"), row.get("labels")
    if not isinstance(s, dict):
        errs.append(f"row {i}: missing state object")
    else:
        if not isinstance(s.get("message"), str):
            errs.append(f"row {i}: state.message must be str")
        if not isinstance(s.get("rules"), dict) or not s["rules"]:
            errs.append(f"row {i}: state.rules must be a non-empty mapping")
    if not isinstance(lab, dict) or "rule" not in lab:
        errs.append(f"row {i}: labels.rule missing")
    return errs


def check_file(path: str, limit: int = 0) -> list:
    errs = []
    with open(path) as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                errs.append(f"row {i}: bad JSON ({e})")
                continue
            errs.extend(check_row(row, i))
    return errs


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="validate_data")
    ap.add_argument("path", nargs="?", default="data/examples.jsonl")
    ap.add_argument("--limit", type=int, default=0)  # T573: check first N rows only
    ap.add_argument("--out", default=None)  # T573: optional JSON report
    ap.add_argument("--json", action="store_true")  # T573: one-line output
    a = ap.parse_args()
    errs = check_file(a.path, a.limit)
    for e in errs[:20]:
        print(e)
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"path": a.path, "limit": a.limit, "errors": errs}, f, indent=2)
    print(json.dumps({"path": a.path, "errors": len(errs)},
                     indent=None if a.json else 2))
    sys.exit(1 if errs else 0)
