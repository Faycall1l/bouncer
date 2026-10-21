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

# T959: inlined (was _HERE) — a plain assignment before the sibling imports is
# an E402; sys.path manipulation itself is exempt.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "eval"))

from synth_rules import hard_rows, i18n_rows, llm_rows, template_rows
from validate_data import check_row

NAMES = ("train", "dev", "test")


def server_key(row: dict) -> tuple:
    """A row's server identity: the rule-set it belongs to (ids only)."""
    return tuple(sorted(row["state"]["rules"]))


def split_rows(rows: list, ratios=(0.8, 0.1, 0.1), seed: int = 0,
               stratify: bool = False) -> dict:
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
    lab_counts = {n: Counter() for n in NAMES}
    if len(groups) > len(reserve):  # train keeps at least one rule-set
        for n in reserve:
            key = keys.pop(0)  # smallest remaining -> n
            assign[key] = n
            counts[n] += len(groups[key])
            lab_counts[n].update(r["labels"]["rule"] for r in groups[key])
    global_share = Counter(r["labels"]["rule"] for r in rows)
    gtotal = len(rows) or 1

    def penalty(n: str, labs: Counter) -> float:
        """T643: squared distance of the split's label mix from the global mix."""
        after = lab_counts[n] + labs
        na = sum(after.values()) or 1
        return sum((c - na * global_share[ln] / gtotal) ** 2 for ln, c in after.items()) / na

    for key in sorted(keys, key=lambda k: -len(groups[k])):  # largest first
        if stratify:  # T643: keep label shares close to the global mix
            labs = Counter(r["labels"]["rule"] for r in groups[key])
            best = min(NAMES, key=lambda n: (penalty(n, labs), -counts[n]))
        else:
            best = max(NAMES, key=lambda n: targets[n] - counts[n])
        assign[key] = best
        counts[best] += len(groups[key])
        lab_counts[best].update(r["labels"]["rule"] for r in groups[key])

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


def quarantine_rows(rows: list) -> tuple:
    """T645: split rows into (good, quarantined-with-reason) — never a silent skip.

    A row that fails schema validation is kept whole with its errors attached,
    so nothing disappears from the build without a trace.
    """
    good, bad = [], []
    for i, r in enumerate(rows):
        errs = check_row(r, i)
        if errs:
            bad.append({"error": "; ".join(errs), "row": r})
        else:
            good.append(r)
    return good, bad


def class_weights(rows: list) -> dict:
    """T648: inverse-frequency weight hints for the finetune notebook — w = n/(K*n_c).

    Binary heads get their own n/(2*count) pair. These are hints, not magic:
    the trainer applies them however its API wants (class_weight, focal loss...).
    """
    out = {}
    for field in ("rule", "harm"):
        c = Counter(r["labels"].get(field, "?") for r in rows)
        n, k = sum(c.values()), len(c)
        out[field] = {lab: round(n / (k * cnt), 3) for lab, cnt in c.most_common()}
    for field in ("jailbreak", "escalate"):
        pos = sum(1 for r in rows if r["labels"].get(field))
        n, neg = len(rows) or 1, len(rows) - pos
        out[field] = {"false": round(n / (2 * (neg or 1)), 3),
                      "true": round(n / (2 * (pos or 1)), 3)}
    return out


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
    ap.add_argument("--hard-n", type=int, default=None,  # T636: hard negatives
                    help="hard-negative rows to inject (default: n//10, 0 disables)")
    ap.add_argument("--stratify", action="store_true",  # T643: label-preserving
                    help="place servers to keep label shares close to the global mix")
    ap.add_argument("--i18n", action="store_true",  # T649: translated fixtures
                    help="build the i18n fixture set through the pipeline instead")
    a = ap.parse_args(argv)

    if a.seed is not None:
        random.seed(a.seed)
    teacher_bad = []  # T645: llm_rows failures quarantined, never dropped
    if a.i18n:  # T649: fixtures flow through the pipeline like every other row
        if a.out == "data/gatekeeper-12k.jsonl":
            a.out = "data/examples_i18n.jsonl"
        rows = i18n_rows()
        a.no_split = True  # one flat fixture file, no server-disjoint split
    elif a.template_only or not os.environ.get("OPENAI_API_KEY"):
        rows = template_rows(a.n)
    else:
        rows = template_rows(a.n // 3) + llm_rows(2 * a.n // 3, quarantine=teacher_bad)
    if not a.i18n:
        hard = a.hard_n if a.hard_n is not None else a.n // 10  # T636
        if hard > 0:
            rows += hard_rows(hard)
    random.shuffle(rows)
    deduped = None
    if a.dedupe:  # T634: before validation, so dropped rows never get checked
        rows, dropped = dedupe_rows(rows)
        deduped = {"kept": len(rows), "dropped": dropped}

    # T645: corrupted rows are quarantined to a file — loud, never a silent skip
    good, bad = quarantine_rows(rows)
    quarantined = teacher_bad + bad
    if quarantined:
        qpath = a.out.removesuffix(".jsonl") + ".quarantine.jsonl"
        with open(qpath, "w") as f:
            f.writelines(json.dumps(e) + "\n" for e in quarantined)
        print(f"build_dataset: {len(quarantined)} corrupted row(s) quarantined "
              f"-> {qpath}", file=sys.stderr)
        for e in quarantined[:5]:
            print(f"  {e.get('error')}", file=sys.stderr)
        if not good:
            print("build_dataset: no valid rows left, nothing written", file=sys.stderr)
            return 1
        rows = good

    if a.report:  # T633: balance check without generating any dataset file
        splits = split_rows(rows, tuple(a.ratios), a.seed or 0, stratify=a.stratify)
        rep = {"n": len(rows), "seed": a.seed,
               "servers": len({server_key(r) for r in rows}),
               "class_weights": class_weights(rows),
               **balance_report(splits, a.min_share)}
        if quarantined:
            rep["quarantined"] = len(quarantined)
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

    report = {"n": len(rows), "out": a.out, "errors": 0, "seed": a.seed,
              "servers": len({server_key(r) for r in rows}),
              "class_weights": class_weights(rows)}
    if quarantined:
        report["quarantined"] = len(quarantined)
    if deduped is not None:
        report["deduped"] = deduped
    if not a.no_split:
        splits = split_rows(rows, tuple(a.ratios), a.seed or 0, stratify=a.stratify)
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
