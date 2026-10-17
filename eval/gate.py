"""eval/gate.py (T671): pass/fail thresholds over a report JSON.

Contract (T677): exit 0 = every applied gate passed, exit 1 = at least one
gate failed (or the report is structurally unusable), exit 2 = the file could
not be read/parsed at all.

  python eval/gate.py eval/reports/zero-shot.json
  python eval/gate.py REPORT --json          # machine-readable verdict
  python eval/gate.py REPORT --ci            # exactly one line of verdict JSON
  python eval/gate.py REPORT --against REF   # + informational metric delta table
  python eval/gate.py REPORT --against REF --changelog   # diff also lands in CHANGELOG

Each gate reads its value from the report and compares against a flag-settable
threshold (T672-T676 register theirs here). A metric absent from the report is
SKIPPED — a missing number never counts as a green light.
"""
import argparse
import json
import sys

MISSING = object()


def _add(checks, name, expected, value, ok):
    checks.append({"name": name, "expected": expected, "value": value, "ok": ok})


def _get(report: dict, *keys):
    cur = report
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return MISSING
        cur = cur[k]
    return cur


def _num(report: dict, *keys):
    """Nested numeric lookup; None when absent or not a number (=> SKIP)."""
    v = _get(report, *keys)
    if v is MISSING or not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    return v


def collect(report: dict, args) -> list:
    """Registered gates over one report.

    Each check: {name, expected, value, ok}; ok is True/False, or None when
    the metric is missing from this report (SKIPPED, never a pass).
    """
    checks = []

    def add(name, expected, value, ok):
        _add(checks, name, expected, value, ok)

    def le(name, keys, threshold):
        v = _num(report, *keys)
        add(name, f"<= {threshold}", v, None if v is None else v <= threshold)

    def band(name, keys, lo, hi):  # T675: abstention must neither vanish nor dominate
        v = _num(report, *keys)
        expected = f"> {lo} and <= {hi}"
        add(name, expected, v, None if v is None else lo < v <= hi)

    # --- T671: structural gates: this must be a usable eval report ---
    # Absent core fields FAIL loudly (a bad report is a failed gate, not a skip).
    n = _num(report, "n")
    add("report_n", f">= {args.min_n}", n, False if n is None else n >= args.min_n)
    acc = _num(report, "rule_acc")
    if acc is None:
        acc = _num(report, "acc")  # T678: normalized baseline report key
    add("report_rule_acc", "present", acc, acc is not None)

    # --- T672-T676 register their threshold gates here ---
    if acc is None:  # T672: must beat the regex bar (acc covers baselines too)
        add("rule_acc", f">= {args.min_rule_acc}", None, None)
    else:
        add("rule_acc", f">= {args.min_rule_acc}", acc, acc >= args.min_rule_acc)
    le("ece", ("ece",), args.max_ece)  # T673: after calibration, probs stay honest
    le("p95_ms", ("p95_ms",), args.max_p95_ms)  # T674: latency budget (T4 target)
    band("abstention_rate", ("abstention_rate",),  # T675: honest band
         args.min_abstention, args.max_abstention)
    # --- T676: per-rule worst-case — no eligible rule may sit below the floor ---
    # per_rule is {label: [ok, n]}; rules below the support floor are noise.
    pr = _get(report, "per_rule")
    if pr is MISSING:
        pr = _get(report, "per_label")  # T678: normalized baseline report key
    worst, worst_name = None, None
    if isinstance(pr, dict):
        for rule, pair in pr.items():
            if (isinstance(pair, (list, tuple)) and len(pair) == 2
                    and isinstance(pair[0], (int, float))
                    and isinstance(pair[1], (int, float))
                    and pair[1] >= args.per_rule_min_n):
                acc = pair[0] / pair[1]
                if worst is None or acc < worst:
                    worst, worst_name = acc, rule
    if worst is None:
        add("per_rule_worst", f">= {args.min_per_rule_acc}", None, None)  # SKIP
    else:
        add("per_rule_worst", f">= {args.min_per_rule_acc} (worst: {worst_name})",
            round(worst, 3), worst >= args.min_per_rule_acc)
    return checks


def collect_i18n(report: dict, args) -> list:
    """T681: the i18n wiring eval must stay 0 errors — that's the whole gate."""
    checks = []
    n = _num(report, "n")
    _add(checks, "report_n", f">= {args.min_n}", n,
         False if n is None else n >= args.min_n)
    errors = _get(report, "errors")
    if isinstance(errors, list):
        _add(checks, "i18n_errors", "== 0", len(errors), len(errors) == 0)
    else:
        _add(checks, "i18n_errors", "== 0", None, False)  # absent = bad shape, FAIL
    return checks


def detect_kind(report: dict) -> str:
    """Gate family by report shape (T681: i18n; more families follow)."""
    if "per_lang" in report:
        return "i18n"  # only eval_i18n.py produces per_lang
    return "eval"


COLLECTORS = {"eval": collect, "i18n": collect_i18n}  # T681: dispatch table


def gate_report(report: dict, args) -> dict:
    checks = COLLECTORS[detect_kind(report)](report, args)
    passed = sum(1 for c in checks if c["ok"] is True)
    failed = sum(1 for c in checks if c["ok"] is False)
    skipped = sum(1 for c in checks if c["ok"] is None)
    return {"ok": failed == 0 and passed > 0, "passed": passed, "failed": failed,
            "skipped": skipped, "checks": checks}


def append_changelog(path: str, report: str, ref: str, delta: dict, verdict: dict):
    """T680: when gates re-run, the report diff lands in the CHANGELOG — dated
    and fenced under an Unreleased section (created if missing)."""
    import datetime as _dt

    lines = [(f"### Eval gates re-run — {report} vs {ref} "
              f"({_dt.date.today().isoformat()})"), "",
             (f"verdict: {'PASS' if verdict['ok'] else 'FAIL'} "
              f"({verdict['passed']} passed, {verdict['failed']} failed, "
              f"{verdict['skipped']} skipped)")]
    for key, m in delta["metrics"].items():
        lines.append(f"* {key}: {m['base']} -> {m['finetuned']} "
                     f"({m['delta']:+g}) [{m['verdict']}]")
    block = "\n".join(lines)
    with open(path) as f:
        text = f.read()
    if "\n## Unreleased\n" in text:
        text = text.replace("\n## Unreleased\n", f"\n## Unreleased\n\n{block}\n", 1)
    else:
        head, sep, rest = text.partition("\n## ")  # insert above first release
        text = f"{head}\n## Unreleased\n\n{block}\n{sep}{rest}"
    with open(path, "w") as f:
        f.write(text)


def render(verdict: dict) -> str:
    lines = []
    for c in verdict["checks"]:
        tag = {True: "PASS", False: "FAIL", None: "SKIP"}[c["ok"]]
        val = "missing" if c["value"] is None else c["value"]
        lines.append(f"{tag} {c['name']}: {val} (expected {c['expected']})")
    verdict_line = (f"GATE {verdict['passed']} passed, {verdict['failed']} failed, "
                    f"{verdict['skipped']} skipped -> "
                    f"{'PASS' if verdict['ok'] else 'FAIL'}")
    lines.append(verdict_line)
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gate", description="pass/fail thresholds over a report (T671)",
        epilog="exit codes (T677): 0 = every applied gate passed; 1 = a gate "
               "failed (or the report is structurally unusable); 2 = the input "
               "could not be read/parsed. Skipped gates (metric absent) never "
               "block a pass. --ci prints exactly one line of verdict JSON.")
    ap.add_argument("report", help="report JSON (e.g. eval/reports/zero-shot.json)")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict")
    ap.add_argument("--ci", action="store_true",  # T677: one line, stable exits
                    help="CI mode: exactly one line of verdict JSON on stdout; "
                         "failures still blame on stderr; exits 0/1/2 as above")
    ap.add_argument("--against", default=None,  # T679: informational delta table
                    help="reference report to diff against: prints metric deltas "
                         "(informational — never changes the exit code)")
    ap.add_argument("--changelog", default=None, nargs="?", const="CHANGELOG.md",  # T680
                    help="also append the --against delta block to this CHANGELOG "
                         "(default CHANGELOG.md); requires --against")
    ap.add_argument("--min-n", type=int, default=1,
                    help="report must cover at least N rows")
    ap.add_argument("--min-rule-acc", type=float, default=0.403,  # T672
                    help="rule_acc floor: the regex baseline on examples.jsonl "
                         "(0.403 post-T637; older notes say 0.480, pre-hard-negatives)")
    ap.add_argument("--max-ece", type=float, default=0.15,  # T673
                    help="ECE ceiling after calibration (uncalibrated reports will fail)")
    ap.add_argument("--max-p95-ms", type=float, default=44.0,  # T674
                    help="p95 latency budget in ms (44 = T4 product target; "
                         "CPU zero-shot reports will fail)")
    ap.add_argument("--min-abstention", type=float, default=0.0,  # T675
                    help="abstention_rate floor, exclusive: 0 abstentions means "
                         "the model never hedges — suspicious, not laudable")
    ap.add_argument("--max-abstention", type=float, default=0.3,  # T675
                    help="abstention_rate ceiling: past this the gate is all abstain")
    ap.add_argument("--min-per-rule-acc", type=float, default=0.3,  # T676
                    help="floor for the worst per-rule accuracy")
    ap.add_argument("--per-rule-min-n", type=int, default=5,  # T676
                    help="ignore rules with fewer than N samples (noise floor)")
    a = ap.parse_args(argv)
    if a.changelog and not a.against:  # T680: usage error, before any output
        print("gate: --changelog requires --against (nothing to diff)",
              file=sys.stderr)
        return 2

    try:
        with open(a.report) as f:
            rep = json.load(f)
    except OSError as e:
        print(f"gate: cannot read {a.report}: {e}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"gate: {a.report} is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(rep, dict):
        print(f"gate: {a.report} must contain a JSON object, got "
              f"{type(rep).__name__}", file=sys.stderr)
        return 2

    delta = None
    render_delta = None
    if a.against:  # T679: diff vs a reference report, informational only
        try:
            with open(a.against) as f:
                ref = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"gate: cannot read --against {a.against}: {e}", file=sys.stderr)
            return 2
        if not isinstance(ref, dict):
            print(f"gate: --against {a.against} must be a JSON object",
                  file=sys.stderr)
            return 2
        from compare_models import compare
        from compare_models import render as render_delta
        delta = compare(ref, rep)  # ref = the "base" side, report = the new one

    verdict = gate_report(rep, a)
    if delta is not None:
        verdict["deltas"] = delta  # --json/--ci consumers get it inline
    payload = (json.dumps(verdict, indent=2) if a.json
               else json.dumps(verdict) if a.ci else render(verdict))
    if not verdict["ok"]:
        # failures are loud on stderr too, not just in the report body
        for c in verdict["checks"]:
            if c["ok"] is False:
                print(f"gate: FAIL {c['name']}: value={c['value']} "
                      f"expected {c['expected']}", file=sys.stderr)
    print(payload)
    if delta is not None and not (a.json or a.ci):
        print(render_delta(delta))
    if a.changelog:  # T680: re-run gates -> the diff becomes changelog history
        try:
            append_changelog(a.changelog, a.report, a.against, delta, verdict)
        except OSError as e:
            print(f"gate: cannot write {a.changelog}: {e}", file=sys.stderr)
            return 1
        print(f"gate: delta appended to {a.changelog}", file=sys.stderr)
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
