"""eval/gate.py (T671): pass/fail thresholds over a report JSON.

Contract (T677): exit 0 = every applied gate passed, exit 1 = at least one
gate failed (or the report is structurally unusable), exit 2 = the file could
not be read/parsed at all.

  python eval/gate.py eval/reports/zero-shot.json
  python eval/gate.py REPORT --json          # machine-readable verdict
  python eval/gate.py REPORT --ci            # exactly one line of verdict JSON
  python eval/gate.py REPORT --against REF   # + informational metric delta table
  python eval/gate.py REPORT --against REF --changelog   # diff also lands in CHANGELOG
  python eval/gate.py REPORT --check-docs  # + drift check vs BENCHMARKS Known numbers
  python eval/gate.py --all                # every known report in eval/reports/

Reports older than --max-report-age-days (default 14) get a stderr warning —
a warning, never a verdict change (T685).

Each gate reads its value from the report and compares against a flag-settable
threshold (T672-T676 register theirs here). A metric absent from the report is
SKIPPED — a missing number never counts as a green light.
"""
import argparse
import json
import math
import os
import sys
import time

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
    """Nested numeric lookup; None when absent, non-numeric, or non-finite
    (=> SKIP/FAIL downstream — NaN and inf from a corrupt report must never
    satisfy a `>=` threshold; T687)."""
    v = _get(report, *keys)
    if v is MISSING or not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    if not math.isfinite(v):
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
    # T687: an accuracy outside [0,1] is a corrupt report, not a green light.
    add("report_rule_acc", "present, 0..1", acc,
        acc is not None and 0.0 <= acc <= 1.0)

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
                    and not isinstance(pair[0], bool)  # T690: bools aren't counts
                    and not isinstance(pair[1], bool)
                    and pair[1] >= args.per_rule_min_n):
                rule_acc = pair[0] / pair[1]  # T690: don't shadow report acc
                if worst is None or rule_acc < worst:
                    worst, worst_name = rule_acc, rule
    if worst is None:
        add("per_rule_worst", f">= {args.min_per_rule_acc}", None, None)  # SKIP
    else:
        add("per_rule_worst", f">= {args.min_per_rule_acc} (worst: {worst_name})",
            round(worst, 3), worst >= args.min_per_rule_acc)
    return checks


def collect_i18n(report: dict, args) -> list:
    """T681: the i18n wiring eval must stay 0 errors — that's the whole gate.
    T898: routing misfires fail it too (script picked the wrong checkpoint);
    the quality section is a skip-with-receipt and never gates."""
    checks = []
    n = _num(report, "n")
    _add(checks, "report_n", f">= {args.min_n}", n,
         False if n is None else n >= args.min_n)
    errors = _get(report, "errors")
    if isinstance(errors, list):
        _add(checks, "i18n_errors", "== 0", len(errors), len(errors) == 0)
    else:
        _add(checks, "i18n_errors", "== 0", None, False)  # absent = bad shape, FAIL
    routing = _get(report, "routing")  # T898: absent in pre-T898 reports
    if isinstance(routing, dict):
        wrong = routing.get("wrong")
        if isinstance(wrong, list):
            _add(checks, "i18n_routing_wrong", "== 0", len(wrong),
                 len(wrong) == 0)
    return checks


def collect_breaker(report: dict, args) -> list:
    """T682: the sim must show the breaker tripping under a storm AND closing
    again — a breaker that trips but never closes is a worse outage."""
    checks = []
    for key in ("tripped", "closed"):
        v = _get(report, key)
        _add(checks, f"breaker_{key}", "is true", None if v is MISSING else v,
             (v is True) if v is not MISSING else False)
    return checks


def collect_pool(report: dict, args) -> list:
    """T683: the hits scenario must show the pool's point — >= 2x vs naive."""
    checks = []
    v = _num(report, "speedup")
    _add(checks, "pool_speedup", f">= {args.min_speedup}", v,
         False if v is None else v >= args.min_speedup)
    return checks


PERF_BUDGETS = {  # T766: bench id -> [(check name, value keys, threshold attr)]
    # budgets are ~10x the local measurements (BENCHMARKS) — they catch
    # order-of-magnitude regressions without flaking on slower CI runners
    "bench_stub": [("stub_p50_ms", ("p50_ms",), "max_stub_p50_ms")],
    "bench_import": [("import_p50_ms", ("p50_ms",), "max_import_p50_ms")],
    "bench_stats": [("stats_p95_ms", ("p95_ms",), "max_stats_p95_ms")],
    "bench_warm": [("warm_p50_ms", ("p50_ms",), "max_warm_p50_ms")],
    "bench_questions": [("questions_p50_ms", ("p50_knob_5q_ms",),
                         "max_questions_p50_ms")],
    "bench_batch": [("batch_max_row_ms", ("__max_rows__",), "max_batch_row_ms")],
}


def collect_perf(report: dict, args) -> list:
    """T766: perf reports carry the T765 envelope and stay in budget.

    Structural checks (known bench id, schema, mode) FAIL loudly — a
    report without the envelope is unusable, not a skip. Each budget
    SKIPs when its metric is absent; every registered bench maps to at
    least one budget, so a healthy producer always has something to gate.
    """
    checks = []
    bench = _get(report, "bench")
    known = isinstance(bench, str)
    _add(checks, "bench_id", f"one of {sorted(PERF_BUDGETS)}",
         None if bench is MISSING else bench,
         (bench in PERF_BUDGETS) if known else False)
    schema = _num(report, "schema")
    _add(checks, "bench_schema", "== 1", schema,
         schema == 1 if schema is not None else False)
    mode = _get(report, "mode")
    _add(checks, "bench_mode", "in stub/real/n/a", None if mode is MISSING else mode,
         (mode in ("stub", "real", "n/a")) if mode is not MISSING else False)
    for name, keys, attr in PERF_BUDGETS.get(bench, ()) if known else ():
        thr = getattr(args, attr, None)
        if keys == ("__max_rows__",):  # bench_batch: worst combo of the sweep
            rows = _get(report, "rows")
            vals = [v for v in (rows.values() if isinstance(rows, dict) else ())
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v)]
            v = max(vals) if vals else None
        else:
            v = _num(report, *keys)
        _add(checks, name, f"<= {thr}", v, None if v is None else v <= thr)
    return checks


def collect_metrics(report: dict, args) -> list:
    """T948: the /metrics scrape report gates on TWO axes.

    Format is structural and machine-independent (T943's contract): every
    family needs exactly one HELP + one TYPE and every sample must parse —
    a broken exposition fails loudly even on slow CI. Budget is the
    p95-of-one-scrape cost (T766's ~10x rule), SKIPped when the producer
    never measured it, like every other budget.
    """
    checks = []
    bench = _get(report, "bench")
    _add(checks, "bench_id", "== bench_metrics", bench,
         None if bench is MISSING else bench == "bench_metrics")
    schema = _num(report, "schema")
    _add(checks, "bench_schema", "== 1", schema,
         schema == 1 if schema is not None else False)
    fmt = _get(report, "format_ok")
    _add(checks, "metrics_format", "every sample parses", fmt,
         None if fmt is MISSING else bool(fmt))
    complete = _get(report, "help_complete")
    _add(checks, "metrics_help_type", "one HELP+TYPE per family", complete,
         None if complete is MISSING else bool(complete))
    p50 = _num(report, "p50_ms")
    thr = getattr(args, "max_metrics_p50_ms", None)
    _add(checks, "metrics_p50_ms", f"<= {thr}", p50,
         None if p50 is None else p50 <= thr)
    return checks


def known_numbers(path: str) -> dict:
    """T684: the Known-numbers table in BENCHMARKS.md, as data."""
    import re

    nums = {}
    in_table = False
    with open(path) as f:
        for line in f:
            if line.startswith("## "):
                in_table = "Known numbers" in line
                continue
            if not in_table:
                continue
            m = re.match(r"\|\s*([a-z0-9_]+)\s*\|\s*\**(-?[0-9.]+)", line)
            if m:
                nums[m.group(1)] = float(m.group(2))
    return nums


def collect_docs(args, path: str) -> list:
    """T684: documented numbers and enforced defaults may not drift apart.
    A table row that vanished is drift by omission — FAIL, not SKIP."""
    checks = []
    known = known_numbers(path)
    pairs = [("regex_floor", args.min_rule_acc), ("max_ece", args.max_ece),
             ("max_p95_ms_t4", args.max_p95_ms),
             ("pool_speedup_floor", args.min_speedup),
             ("import_budget_ms", args.max_import_p50_ms)]  # T766: = T764's 200
    for key, enforced in pairs:
        documented = known.get(key)
        _add(checks, f"docs_{key}", f"== default {enforced}", documented,
             False if documented is None else abs(documented - enforced) < 1e-9)
    return checks


def detect_kind(report: dict) -> str:
    """Gate family by report shape (T681-T683+T766; more families may follow)."""
    if "per_lang" in report:
        return "i18n"  # only eval_i18n.py produces per_lang
    if "routing" in report:
        # T908: a routing-shaped i18n report (T898's section on its own, e.g.
        # a trimmed fixture run) is still an i18n family report — it must
        # gate on routing misfires, not fall through to the generic eval
        # collector and skip them silently
        return "i18n"
    if "tripped" in report or "closed" in report:
        return "breaker"  # only breaker_sim.py produces these
    if "speedup" in report or "thrash" in report:
        return "pool"  # bench_pool has both pool keys AND the T765 envelope —
        # pool wins so T683's speedup floor never silently stops applying
    if report.get("bench") == "bench_metrics":
        # T948: the metrics report carries the T765 envelope AND exposition
        # format fields — it gates on format + scrape cost, so it must not
        # fall through to the generic perf collector (which would skip both)
        return "metrics"
    if "bench" in report:
        return "perf"  # T765 envelope: every other bench_*.py report
    return "eval"


COLLECTORS = {"eval": collect, "i18n": collect_i18n,  # T681
              "breaker": collect_breaker,  # T682
              "pool": collect_pool,  # T683: dispatch table
              "perf": collect_perf,  # T766
              "metrics": collect_metrics}  # T948


def gate_report(report: dict, args) -> dict:
    verdict = {"checks": COLLECTORS[detect_kind(report)](report, args)}
    _tally(verdict)
    return verdict


def _tally(verdict: dict):
    """(Re)count a verdict after its check list changed (T684: docs checks)."""
    checks = verdict["checks"]
    verdict["passed"] = sum(1 for c in checks if c["ok"] is True)
    verdict["failed"] = sum(1 for c in checks if c["ok"] is False)
    verdict["skipped"] = sum(1 for c in checks if c["ok"] is None)
    verdict["ok"] = verdict["failed"] == 0 and verdict["passed"] > 0


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


def run_all(args) -> int:
    """T689: make-style single command — gate every known report that exists
    in the reports dir, one summary line per file. Nothing present -> exit 2
    (there is nothing to gate; that is not a green run)."""
    known = ["latest.json", "i18n.json", "breaker.json", "pool.json",
             "stub-latency.json", "warm.json", "stats-load.json",  # T766
             "import.json", "import-version.json", "questions.json",
             "batch-sweep.json", "metrics.json"]  # T948
    paths = [os.path.join(args.reports_dir, n) for n in known]
    found = [(n, p) for n, p in zip(known, paths) if os.path.exists(p)]
    if not found:
        print(f"gate: no reports in {args.reports_dir} — run eval/*.py first",
              file=sys.stderr)
        return 2
    any_fail = False
    for name, path in found:
        try:
            with open(path) as f:
                rep = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"gate: {path} unreadable: {e}", file=sys.stderr)
            return 2
        verdict = gate_report(rep, args)
        if args.check_docs:
            verdict["checks"].extend(collect_docs(args, args.check_docs))
            _tally(verdict)
        print(f"== {name}: {'PASS' if verdict['ok'] else 'FAIL'} "
              f"({verdict['passed']} passed, {verdict['failed']} failed, "
              f"{verdict['skipped']} skipped)")
        for c in verdict["checks"]:
            if c["ok"] is False:
                print(f"   FAIL {name}/{c['name']}: value={c['value']} "
                      f"expected {c['expected']}", file=sys.stderr)
                any_fail = True
    print(f"GATE all: {'FAIL' if any_fail else 'PASS'} "
          f"({len(found)} reports gated)")
    return 1 if any_fail else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gate", description="pass/fail thresholds over a report (T671)",
        epilog="exit codes (T677): 0 = every applied gate passed; 1 = a gate "
               "failed (or the report is structurally unusable); 2 = the input "
               "could not be read/parsed. Skipped gates (metric absent) never "
               "block a pass. --ci prints exactly one line of verdict JSON.")
    ap.add_argument("report", nargs="?",  # T689: optional when --all is used
                    help="report JSON (e.g. eval/reports/zero-shot.json)")
    ap.add_argument("--all", action="store_true",  # T689: make-style one command
                    help="gate every known report in --reports-dir "
                         "(latest/i18n/breaker/pool); human output only")
    ap.add_argument("--reports-dir", default="eval/reports",  # T689
                    help="where --all looks for the known reports")
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
    ap.add_argument("--check-docs", default=None, nargs="?", const="BENCHMARKS.md",  # T684
                    help="also check the Known-numbers table in this doc against "
                         "the threshold defaults being enforced (default BENCHMARKS.md)")
    ap.add_argument("--max-report-age-days", type=float, default=14.0,  # T685
                    help="warn (stderr, never a verdict change) when the report "
                         "file is older than N days; 0 disables")
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
    ap.add_argument("--min-speedup", type=float, default=2.0,  # T683
                    help="pool hits-scenario speedup floor vs naive rebuilds")
    ap.add_argument("--max-stub-p50-ms", type=float, default=5.0,  # T766
                    help="bench_stub p50 budget in ms (local ~0.1ms; the "
                         "budget is ~10x headroom for slower runners)")
    ap.add_argument("--max-import-p50-ms", type=float, default=200.0,  # T766
                    help="import-time p50 budget in ms (200 = T764's wheel "
                         "budget; local p50 is ~30ms)")
    ap.add_argument("--max-stats-p95-ms", type=float, default=250.0,  # T766; widened 100->250: tiny-sample p95 flake
                    help="GET /stats p95 budget in ms under threaded load "
                         "(local ~11ms in-process; the P40 sweep samples p95 "
                         "over ~10 requests, so the budget is an "
                         "order-of-magnitude alarm, not a machine mirror; T760)")
    ap.add_argument("--max-warm-p50-ms", type=float, default=50.0,  # T766
                    help="warm-pool p50 budget in ms (stub path; T751)")
    ap.add_argument("--max-questions-p50-ms", type=float, default=20.0,  # T766
                    help="end-to-end moderate() p50 budget for the 5q knob "
                         "leg in ms (local ~1.4ms stub; T755)")
    ap.add_argument("--max-batch-row-ms", type=float, default=50.0,  # T766
                    help="worst single cell of the batch/chunk sweep in ms "
                         "(local max ~3ms stub; T753)")
    ap.add_argument("--max-metrics-p50-ms", type=float, default=100.0,  # T948
                    help="one /metrics scrape in ms (in-process; local ~5ms, "
                         "budget ~10x per T766)")
    a = ap.parse_args(argv)
    if a.all:  # T689: single command over the whole reports dir
        if a.against or a.changelog:
            ap.error("--all gates each report on its own; "
                     "--against/--changelog need a single report")
        return run_all(a)
    if not a.report:
        ap.error("a report path (or --all) is required")  # argparse exits 2
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

    if a.max_report_age_days > 0:  # T685: a stale report is a stale verdict
        age_d = (time.time() - os.path.getmtime(a.report)) / 86400.0
        if age_d > a.max_report_age_days:
            print(f"gate: warning: report is {age_d:.0f}d old "
                  f"(limit {a.max_report_age_days:.0f}d) — re-run the eval",
                  file=sys.stderr)

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
    if a.check_docs:  # T684: docs-vs-defaults drift, appended to any verdict
        try:
            verdict["checks"].extend(collect_docs(a, a.check_docs))
        except OSError as e:
            print(f"gate: cannot read docs {a.check_docs}: {e}", file=sys.stderr)
            return 2
        _tally(verdict)
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
