"""T381: schema checker for eval JSONL rows (state/rules/labels). No weights."""
import argparse
import json
import sys


def check_row(row: dict, i: int, warn: list | None = None) -> list:
    errs = []
    if not isinstance(row, dict):
        return [f"row {i}: not an object"]
    if "v" in row and row["v"] != 1:  # T640: stamped rows must be current schema
        errs.append(f"row {i}: unsupported schema version {row['v']!r} (want 1)")
    s, lab = row.get("state"), row.get("labels")
    if not isinstance(s, dict):
        errs.append(f"row {i}: missing state object")
    else:
        if not isinstance(s.get("message"), str):
            errs.append(f"row {i}: state.message must be str")
        if not isinstance(s.get("rules"), dict) or not s["rules"]:
            errs.append(f"row {i}: state.rules must be a non-empty mapping")
        if warn is not None and not s.get("history"):  # T644: pre-T635 rows
            warn.append(f"row {i}: empty history (pre-T635 shape)")
    if not isinstance(lab, dict) or "rule" not in lab:
        errs.append(f"row {i}: labels.rule missing")
    return errs


def check_file(path: str, limit: int = 0, warn: list | None = None) -> list:
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
            errs.extend(check_row(row, i, warn))
    return errs


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="validate_data")
    ap.add_argument("path", nargs="?", default="data/examples.jsonl")
    ap.add_argument("--limit", type=int, default=0)  # T573: check first N rows only
    ap.add_argument("--out", default=None)  # T573: optional JSON report
    ap.add_argument("--json", action="store_true")  # T573: one-line output
    a = ap.parse_args()
    warn: list = []  # T644: advisory, never fails the run
    errs = check_file(a.path, a.limit, warn)
    for e in errs[:20]:
        print(e)
    for w in warn[:10]:
        print(f"warn: {w}", file=sys.stderr)
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"path": a.path, "limit": a.limit, "errors": errs,
                       "warnings": warn}, f, indent=2)
    print(json.dumps({"path": a.path, "errors": len(errs), "warnings": len(warn)},
                     indent=None if a.json else 2))
    sys.exit(1 if errs else 0)
