"""T631: dataset build orchestrator — synth -> validate -> server-disjoint split.

One command produces the full file plus train/dev/test splits whose rule-sets
never cross splits (a row's "server" = its rule-set ids, see T632). Weightless
by default (template rows); with OPENAI_BASE_URL + OPENAI_API_KEY set, ~2/3 of
rows come from the teacher (synth_rules.llm_rows).
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "eval"))

from synth_rules import llm_rows, template_rows
from validate_data import check_row

NAMES = ("train", "dev", "test")


def server_key(row: dict) -> tuple:
    """A row's server identity: the rule-set it belongs to (ids only)."""
    return tuple(sorted(row["state"]["rules"]))


def split_rows(rows: list, ratios=(0.8, 0.1, 0.1), seed: int = 0) -> dict:
    """Server-disjoint split: every rule-set lands in exactly one split.

    Ratios are relative weights (need not sum to 1) — 2/1/0 gives a 2:1
    train/test split and skips dev. The two smallest rule-sets are reserved for
    dev/test (when there are enough to leave train at least one), then the rest
    fill largest-first into whichever split is furthest below its row target.
    Tiny template sets (3 rule-sets) get a usable dev/test; larger teacher sets
    converge on the weights.
    """
    if len(ratios) != 3 or any(x < 0 for x in ratios) or sum(ratios) <= 0:
        raise ValueError("ratios must be 3 non-negative numbers summing > 0")
    groups: dict = {}
    for r in rows:
        groups.setdefault(server_key(r), []).append(r)
    targets = {n: ratios[i] * len(rows) for i, n in enumerate(NAMES)}
    counts = dict.fromkeys(NAMES, 0)
    assign: dict = {}

    keys = sorted(groups, key=lambda k: (len(groups[k]), k))  # ascending, stable
    reserve = [n for n in NAMES[1:] if targets[n] > 0]
    if len(groups) > len(reserve):  # train keeps at least one rule-set
        for n in reserve:
            key = keys.pop(0)  # smallest remaining -> n
            assign[key] = n
            counts[n] += len(groups[key])
    for key in sorted(keys, key=lambda k: -len(groups[k])):  # largest first
        best = max(NAMES, key=lambda n: targets[n] - counts[n])
        assign[key] = best
        counts[best] += len(groups[key])

    out = {n: [] for n in NAMES}
    for key, part in groups.items():
        out[assign[key]].extend(part)
    return out


def normalized_hash(msg: str) -> str:
    """T634: near-duplicate key — case/punctuation/whitespace insensitive."""
    norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", msg.casefold())).strip()
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def dedupe_rows(rows: list) -> tuple:
    """Keep the first row per normalized message; returns (kept, n_dropped).

    Targets teacher rows that drift into near-copies ("GG all!" vs "gg all").
    In template mode this collapses the six templates to six rows — pass
    --dedupe only where repeats are unwanted.
    """
    seen = set()
    kept = []
    for r in rows:
        h = normalized_hash(r["state"]["message"])
        if h in seen:
            continue
        seen.add(h)
        kept.append(r)
    return kept, len(rows) - len(kept)


def balance_report(splits: dict, min_share: float) -> dict:
    """Per-split label distribution + which rule labels fall under min_share."""
    below = []
    out = {}
    for name, part in splits.items():
        n = len(part) or 1
        rule = Counter(r["labels"]["rule"] for r in part)
        harm = Counter(r["labels"].get("harm", "?") for r in part)
        shares = {k: v / n for k, v in rule.items()}
        out[name] = {"n": len(part), "rule": dict(rule.most_common()),
                     "harm": dict(harm.most_common()),
                     "jailbreak": sum(1 for r in part if r["labels"].get("jailbreak")),
                     "escalate": sum(1 for r in part if r["labels"].get("escalate")),
                     "min_rule_share": round(min(shares.values(), default=0.0), 4)}
        below += [f"{name}: rule {k!r} share {s:.3f} < {min_share}"
                  for k, s in sorted(shares.items()) if s < min_share]
    return {"splits": out, "below_threshold": below, "balanced": not below}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="build_dataset",
                                 description="synth -> validate -> split (T631)")
    ap.add_argument("--n", type=int, default=12000)
    ap.add_argument("--out", default="data/gatekeeper-12k.jsonl")
    ap.add_argument("--template-only", action="store_true")
    ap.add_argument("--seed", type=int, default=None)  # reproducible builds (T382)
    ap.add_argument("--ratios", type=float, nargs=3, default=[0.8, 0.1, 0.1],
                    metavar=("TRAIN", "DEV", "TEST"))
    ap.add_argument("--no-split", action="store_true",
                    help="write the full file only, skip the split files")
    ap.add_argument("--report", action="store_true",  # T633: balance, no write
                    help="print per-split label balance instead of writing rows")
    ap.add_argument("--min-share", type=float, default=0.02,  # T633 threshold
                    help="rule-label share below this is flagged in --report")
    ap.add_argument("--strict", action="store_true",  # T633: CI gate
                    help="with --report: exit 1 when any label is below threshold")
    ap.add_argument("--dedupe", action="store_true",  # T634: drop near-identical rows
                    help="keep first row per normalized message (see dedupe_rows)")
    a = ap.parse_args(argv)

    if a.seed is not None:
        random.seed(a.seed)
    if a.template_only or not os.environ.get("OPENAI_API_KEY"):
        rows = template_rows(a.n)
    else:
        rows = template_rows(a.n // 3) + llm_rows(2 * a.n // 3)
    random.shuffle(rows)
    deduped = None
    if a.dedupe:  # T634: before validation, so dropped rows never get checked
        rows, dropped = dedupe_rows(rows)
        deduped = {"kept": len(rows), "dropped": dropped}

    # validate in memory BEFORE writing anything (T645: fail loud, write nothing)
    errs = []
    for i, r in enumerate(rows):
        errs.extend(check_row(r, i))
    if errs:
        print(f"build_dataset: {len(errs)} invalid row(s), nothing written",
              file=sys.stderr)
        for e in errs[:5]:
            print(f"  {e}", file=sys.stderr)
        return 1

    if a.report:  # T633: balance check without generating any dataset file
        splits = split_rows(rows, tuple(a.ratios), a.seed or 0)
        rep = {"n": len(rows),
               "servers": len({server_key(r) for r in rows}),
               **balance_report(splits, a.min_share)}
        if deduped is not None:
            rep["deduped"] = deduped
        print(json.dumps(rep, indent=2))
        return 1 if a.strict and not rep["balanced"] else 0

    parent = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(parent, exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    os.replace(tmp, a.out)  # readers never see a half-written dataset

    report = {"n": len(rows), "out": a.out, "errors": 0,
              "servers": len({server_key(r) for r in rows})}
    if deduped is not None:
        report["deduped"] = deduped
    if not a.no_split:
        splits = split_rows(rows, tuple(a.ratios), a.seed or 0)
        base = a.out.removesuffix(".jsonl")
        files = {}
        for name, part in splits.items():
            path = f"{base}.{name}.jsonl"
            with open(path, "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in part)
            files[name] = path
        report["splits"] = {k: len(v) for k, v in splits.items()}
        report["files"] = files
        report["disjoint"] = True  # by construction; verified by T632
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
