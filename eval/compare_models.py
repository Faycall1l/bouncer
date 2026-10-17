"""T668: base-vs-finetune comparison over two eval_gatekeeper reports.

Weights optional: this script never loads a model — it diffs two report JSONs
(from `eval_gatekeeper.py --out`). Produce one report per checkpoint and diff:
  python eval/eval_gatekeeper.py data/examples.jsonl --out reports/base.json
  python eval/eval_gatekeeper.py data/examples.jsonl --model $OUT \
      --out reports/ft.json
  python eval/compare_models.py reports/base.json reports/ft.json
"""
import argparse
import json
import sys

# (metric path, lower_is_better) — gate.n compares coverage, not quality
METRICS = [("rule_acc", False), ("ece", True), ("brier", True),
           ("p50_ms", True), ("p95_ms", True), ("abstention_rate", False),
           ("overconfident_errors", True), ("gate.prec", False), ("gate.n", False)]


def dig(d: dict, path: str):
    for part in path.split("."):
        if not isinstance(d, dict) or part not in d:
            return None
        d = d[part]
    return d


def compare(base: dict, ft: dict) -> dict:
    """Metric-by-metric delta with a per-metric verdict; weights never involved."""
    rows = {}
    for key, lower_better in METRICS:
        b, f = dig(base, key), dig(ft, key)
        if not isinstance(b, (int, float)) or not isinstance(f, (int, float)):
            continue
        delta = round(f - b, 4)
        better = (f < b) if lower_better else (f > b)
        rows[key] = {"base": b, "finetuned": f, "delta": delta,
                     "verdict": "same" if delta == 0 else ("ft" if better else "base")}
    wins = sum(1 for r in rows.values() if r["verdict"] == "ft")
    losses = sum(1 for r in rows.values() if r["verdict"] == "base")
    return {"base_model": base.get("model"), "finetuned_model": ft.get("model"),
            "n": {"base": base.get("n"), "finetuned": ft.get("n")},
            "metrics": rows, "ft_wins": wins, "base_wins": losses,
            "ft_better": wins > losses}


def render(rep: dict) -> str:
    lines = [(f"base: {rep['base_model']} (n={rep['n']['base']})  vs  "
              f"finetuned: {rep['finetuned_model']} (n={rep['n']['finetuned']})"),
             f"{'metric':<22}{'base':>10}{'finetuned':>12}{'delta':>10}  better"]
    for key, m in rep["metrics"].items():
        lines.append(f"{key:<22}{m['base']:>10}{m['finetuned']:>12}"
                     f"{m['delta']:>+10}{m['verdict']:>8}")
    lines.append(f"ft wins {rep['ft_wins']} / base wins {rep['base_wins']} "
                 f"-> finetuned better: {rep['ft_better']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="compare_models",
                                 description="diff two eval_gatekeeper reports (T668)")
    ap.add_argument("base", help="report JSON from the base checkpoint")
    ap.add_argument("finetuned", help="report JSON from the fine-tuned checkpoint")
    ap.add_argument("--json", action="store_true", help="one-line output")
    a = ap.parse_args(argv)
    try:
        with open(a.base) as f:
            base = json.load(f)
        with open(a.finetuned) as f:
            ft = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"compare_models: cannot read reports ({e})", file=sys.stderr)
        return 2
    rep = compare(base, ft)
    if not rep["metrics"]:
        print("compare_models: no comparable metrics in the reports", file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=None if a.json else 2) if a.json else render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
