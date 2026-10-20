"""P36 tests (T671-T690): eval gates. Weightless — thresholds over report JSONs."""
import json
import subprocess
import sys
from pathlib import Path


def _run_gate(*args):
    return subprocess.run([sys.executable, "eval/gate.py", *args], check=False,
                          capture_output=True, text=True, timeout=30)


def _report(tmp_path, obj, name="r.json"):
    p = tmp_path / name
    p.write_text(json.dumps(obj))
    return str(p)


def test_gate_pass_on_healthy_report(tmp_path):  # T671: exit 0, PASS lines
    path = _report(tmp_path, {"n": 300, "rule_acc": 0.403})
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    assert "PASS report_n" in r.stdout and "PASS report_rule_acc" in r.stdout
    assert "PASS rule_acc" in r.stdout  # 0.403 meets the floor exactly (T672)
    assert "SKIP ece" in r.stdout  # absent metric -> skipped, never passed (T673)
    assert "SKIP p95_ms" in r.stdout  # absent metric -> skipped (T674)
    assert "3 passed, 0 failed, 4 skipped -> PASS" in r.stdout


def test_gate_fails_loud_on_threshold(tmp_path):  # T671: exit 1 + stderr blame
    path = _report(tmp_path, {"n": 1, "rule_acc": 0.403})
    r = _run_gate(path, "--min-n", "10")
    assert r.returncode == 1
    assert "FAIL report_n" in r.stdout and "expected >= 10" in r.stderr
    assert "-> FAIL" in r.stdout


def test_gate_fails_on_missing_core_fields(tmp_path):  # T671: bad report != skip
    path = _report(tmp_path, {"n": 10})
    r = _run_gate(path, "--json")
    assert r.returncode == 1
    verdict = json.loads(r.stdout)
    assert verdict["ok"] is False
    by_name = {c["name"]: c for c in verdict["checks"]}
    assert by_name["report_rule_acc"]["ok"] is False  # absent core field = FAIL
    assert "FAIL report_rule_acc" in r.stderr


def test_gate_exit_2_on_unreadable_input(tmp_path):  # T671: can't even look
    r = _run_gate(str(tmp_path / "nope.json"))
    assert r.returncode == 2 and "cannot read" in r.stderr
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    r = _run_gate(str(bad))
    assert r.returncode == 2 and "not valid JSON" in r.stderr
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2]")
    r = _run_gate(str(lst))
    assert r.returncode == 2 and "JSON object" in r.stderr


def test_gate_json_verdict_shape(tmp_path):  # T671: machine-readable contract
    path = _report(tmp_path, {"n": 300, "rule_acc": 0.403})
    r = _run_gate(path, "--json")
    verdict = json.loads(r.stdout)
    assert set(verdict) == {"ok", "passed", "failed", "skipped", "checks"}
    for c in verdict["checks"]:
        assert set(c) == {"name", "expected", "value", "ok"}


def test_gate_rule_acc_floor(tmp_path):  # T672: must beat the regex bar (0.403)
    # the zero-shot base (0.305) fails the default floor loudly
    path = _report(tmp_path, {"n": 200, "rule_acc": 0.305})
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL rule_acc" in r.stderr
    # exactly the baseline passes (>=, not >)
    path = _report(tmp_path, {"n": 300, "rule_acc": 0.403})
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    # and the floor is configurable per run
    r = _run_gate(path, "--min-rule-acc", "0.5")
    assert r.returncode == 1 and "expected >= 0.5" in r.stderr


def test_gate_ece_ceiling(tmp_path):  # T673: after calibration, probs stay honest
    # a calibrated run (temp refit) passes
    path = _report(tmp_path, {"n": 500, "rule_acc": 0.51, "ece": 0.12})
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    # an uncalibrated/base-like ECE fails the ceiling
    path = _report(tmp_path, {"n": 200, "rule_acc": 0.45, "ece": 0.21})
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL ece" in r.stderr
    # configurable per run
    r = _run_gate(path, "--max-ece", "0.25")
    assert r.returncode == 0, r.stderr
    # absent ece is SKIPPED, and skipped never blocks a pass
    path = _report(tmp_path, {"n": 300, "rule_acc": 0.403})
    r = _run_gate(path, "--json")
    verdict = json.loads(r.stdout)
    assert verdict["ok"] is True and verdict["skipped"] == 4  # +per_rule_worst
    assert any(c["name"] == "ece" and c["ok"] is None for c in verdict["checks"])


def test_gate_p95_latency_budget(tmp_path):  # T674: flag-settable latency budget
    # on-target T4 latency passes
    path = _report(tmp_path, {"n": 500, "rule_acc": 0.51, "p95_ms": 41.5})
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    # CPU zero-shot latency blows the 44ms budget loudly
    path = _report(tmp_path, {"n": 200, "rule_acc": 0.45, "p95_ms": 1284.0})
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL p95_ms" in r.stderr
    # the budget is flag-settable (e.g. CPU hosts get an honest larger one)
    r = _run_gate(path, "--max-p95-ms", "2000")
    assert r.returncode == 0, r.stderr


def test_gate_abstention_band(tmp_path):  # T675: not 0, not > 0.3
    # a model that hedges sometimes passes
    path = _report(tmp_path, {"n": 500, "rule_acc": 0.51, "abstention_rate": 0.05})
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    # never abstaining fails: overconfidence is not a virtue here
    path = _report(tmp_path, {"n": 500, "rule_acc": 0.51, "abstention_rate": 0.0})
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL abstention_rate" in r.stderr
    # all-abstain fails
    path = _report(tmp_path, {"n": 500, "rule_acc": 0.51, "abstention_rate": 0.42})
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL abstention_rate" in r.stderr
    # the ceiling edge (0.3) is inside the band
    path = _report(tmp_path, {"n": 500, "rule_acc": 0.51, "abstention_rate": 0.3})
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    # band is flag-adjustable
    r = _run_gate(path, "--max-abstention", "0.2")
    assert r.returncode == 1


def test_gate_per_rule_worst_case(tmp_path):  # T676: no eligible rule below floor
    # a weak rule (1/10) fails loudly, and names itself in the blame line
    per_rule = {"ok": [180, 200], "sin-spam": [12, 20], "se-amable": [1, 10]}
    path = _report(tmp_path, {"n": 230, "rule_acc": 0.84, "per_rule": per_rule})
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL per_rule_worst" in r.stderr
    assert "se-amable" in r.stderr  # the worst rule is named, not averaged away
    # everyone above the floor -> pass
    per_rule = {"ok": [180, 200], "sin-spam": [12, 20]}
    path = _report(tmp_path, {"n": 220, "rule_acc": 0.87, "per_rule": per_rule})
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    # rules under the support floor are noise, not evidence
    per_rule = {"ok": [180, 200], "rare": [0, 2]}
    path = _report(tmp_path, {"n": 202, "rule_acc": 0.89, "per_rule": per_rule})
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    # both knobs are flag-settable
    per_rule = {"ok": [180, 200], "sin-spam": [12, 20]}
    path = _report(tmp_path, {"n": 220, "rule_acc": 0.87, "per_rule": per_rule})
    r = _run_gate(path, "--min-per-rule-acc", "0.65")
    assert r.returncode == 1
    per_rule = {"ok": [180, 200], "rare": [0, 2]}
    path = _report(tmp_path, {"n": 202, "rule_acc": 0.89, "per_rule": per_rule})
    r = _run_gate(path, "--per-rule-min-n", "1")
    assert r.returncode == 1 and "rare" in r.stderr  # support floor lowered: now judged


def test_gate_ci_mode_and_documented_exits(tmp_path):  # T677: 0/1/2 contract
    r = _run_gate("--help")
    assert r.returncode == 0
    for token in ("--ci", "exit codes", "0 =", "1 =", "2 ="):
        assert token in r.stdout  # the contract is in --help, not tribal memory
    # --ci: exactly one verdict line, same exit contract
    path = _report(tmp_path, {"n": 300, "rule_acc": 0.403})
    r = _run_gate(path, "--ci")
    assert r.returncode == 0
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["ok"] is True
    path = _report(tmp_path, {"n": 200, "rule_acc": 0.305})
    r = _run_gate(path, "--ci")
    assert r.returncode == 1
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["ok"] is False
    assert "FAIL rule_acc" in r.stderr  # blame stays on stderr in CI mode
    # exit 2 keeps its meaning in CI mode too
    r = _run_gate(str(tmp_path / "nope.json"), "--ci")
    assert r.returncode == 2 and r.stdout == ""


def _run_py(*args):
    return subprocess.run([sys.executable, *args], check=False, capture_output=True,
                          text=True, timeout=60)


def test_baseline_report_normalized_and_gateable(tmp_path):  # T678
    r = _run_py("eval/baseline_regex.py", "data/examples.jsonl", "--json")
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout.splitlines()[-1])
    assert set(doc) == {"n", "acc", "per_label"}  # the normalized shape
    assert doc["n"] == 300 and doc["acc"] == 0.403  # the measured number (T637)
    assert sum(v[0] for v in doc["per_label"].values()) > 0
    assert sum(v[1] for v in doc["per_label"].values()) == doc["n"]
    # gate.py consumes the normalized baseline report directly (acc alias)
    b = tmp_path / "baseline.json"
    b.write_text(json.dumps(doc))
    r = _run_gate(str(b), "--json")
    checks = {c["name"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["rule_acc"]["ok"] is True  # acc (0.403) fed the rule_acc gate
    assert checks["per_rule_worst"]["ok"] is False  # per_label fed worst-case...
    assert "be-kind" in checks["per_rule_worst"]["expected"]  # ...and named it
    # with the per-rule floor zeroed, the baseline clears its own acc bar
    r = _run_gate(str(b), "--min-rule-acc", "0.4", "--min-per-rule-acc", "0")
    assert r.returncode == 0, r.stderr
    # below its own accuracy the baseline fails its own bar (sanity of direction)
    r = _run_gate(str(b), "--min-rule-acc", "0.5", "--min-per-rule-acc", "0")
    assert r.returncode == 1 and "FAIL rule_acc" in r.stderr


def test_gate_against_prints_deltas(tmp_path):  # T679: informational ref diff
    ref = _report(tmp_path, {"model": "base-router", "n": 500, "rule_acc": 0.305,
                             "ece": 0.21, "p50_ms": 1004.0}, name="ref.json")
    cur = _report(tmp_path, {"model": "bouncer-421m", "n": 500, "rule_acc": 0.512,
                             "ece": 0.12, "p50_ms": 40.0}, name="cur.json")
    r = _run_gate(cur, "--against", ref, "--min-rule-acc", "0.4")
    assert r.returncode == 0, r.stderr
    assert "rule_acc" in r.stdout and "+0.207" in r.stdout  # human delta table
    assert "vs" in r.stdout
    # --json carries the deltas inline, same compare semantics as T668
    r = _run_gate(cur, "--against", ref, "--json", "--min-rule-acc", "0.4")
    verdict = json.loads(r.stdout)
    assert verdict["deltas"]["metrics"]["rule_acc"]["delta"] == 0.207
    assert verdict["deltas"]["ft_better"] is True
    # deltas never change the exit code: failing gates still fail
    r = _run_gate(cur, "--against", ref, "--min-rule-acc", "0.9")
    assert r.returncode == 1
    # an unreadable reference is unusable input -> exit 2
    r = _run_gate(cur, "--against", str(tmp_path / "nope.json"))
    assert r.returncode == 2 and "--against" in r.stderr


def test_gate_changelog_appends_delta(tmp_path):  # T680: re-run -> diff in CHANGELOG
    ref = _report(tmp_path, {"model": "base-router", "n": 500, "rule_acc": 0.305},
                  name="ref.json")
    cur = _report(tmp_path, {"model": "bouncer-421m", "n": 500, "rule_acc": 0.512},
                  name="cur.json")
    log = tmp_path / "CHANGELOG.md"
    log.write_text("# Changelog\n\n## 0.3.0 — 2026-10-17\n* old entry\n")
    r = _run_gate(cur, "--against", ref, "--changelog", str(log),
                  "--min-rule-acc", "0.4")
    assert r.returncode == 0, r.stderr
    text = log.read_text()
    assert "## Unreleased" in text  # section created above the first release
    assert text.index("## Unreleased") < text.index("## 0.3.0")
    assert "verdict: PASS" in text
    assert "rule_acc: 0.305 -> 0.512 (+0.207)" in text
    # re-running appends a second block without duplicating the heading
    r = _run_gate(cur, "--against", ref, "--changelog", str(log),
                  "--min-rule-acc", "0.4")
    assert r.returncode == 0
    text = log.read_text()
    assert text.count("## Unreleased") == 1 and text.count("verdict: PASS") == 2
    # a failing run is still changelog history (verdict FAIL recorded)
    r = _run_gate(cur, "--against", ref, "--changelog", str(log),
                  "--min-rule-acc", "0.9")
    assert r.returncode == 1 and "verdict: FAIL" in log.read_text()
    # --changelog without --against is a usage error -> exit 2, no output noise
    r = _run_gate(cur, "--changelog", str(log))
    assert r.returncode == 2 and "--changelog requires --against" in r.stderr
    assert r.stdout == ""


def test_gate_i18n_zero_errors(tmp_path):  # T681: wiring eval must stay 0 errors
    # generate a real i18n report through the weightless wiring eval (T498)
    r = _run_py("eval/eval_i18n.py", "--json", "--out", str(tmp_path / "i18n.json"))
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report["errors"] == []  # precondition: current fixtures are clean
    path = _report(tmp_path, report, name="i18n-real.json")
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    r = _run_gate(path, "--json")
    checks = {c["name"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["i18n_errors"]["ok"] is True and checks["i18n_errors"]["value"] == 0
    assert "rule_acc" not in checks  # eval-family gates don't apply here
    # one error fails loudly, and names its count
    bad = dict(report, errors=["es: E_PRESET missing"])
    path = _report(tmp_path, bad, name="i18n-bad.json")
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL i18n_errors: value=1" in r.stderr
    # missing errors list = bad shape = FAIL, never a silent pass
    path = _report(tmp_path, {"n": 12, "per_lang": {}}, name="i18n-noshape.json")
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL i18n_errors" in r.stderr


def test_gate_breaker_trips_and_closes(tmp_path):  # T682: both true or it's broken
    # a real weightless sim (T580) through the gate
    r = _run_py("eval/breaker_sim.py", "--storm", "3", "--cool", "0.2",
                "--out", str(tmp_path / "breaker.json"), "--json")
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report["tripped"] is True and report["closed"] is True  # precondition
    path = _report(tmp_path, report, name="breaker-real.json")
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    r = _run_gate(path, "--json")
    checks = {c["name"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["breaker_tripped"]["ok"] is True
    assert checks["breaker_closed"]["ok"] is True
    # tripped but never closed = a stuck breaker, fails loudly
    path = _report(tmp_path, {"tripped": True, "closed": False}, name="b-stuck.json")
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL breaker_closed" in r.stderr
    # missing field = bad shape = FAIL, not skip
    path = _report(tmp_path, {"tripped": True}, name="b-short.json")
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL breaker_closed" in r.stderr


def test_gate_pool_speedup_hits_scenario(tmp_path):  # T683: >= 2x where it counts
    # a real weightless bench (T580) through the gate
    r = _run_py("eval/bench_pool.py", "--out", str(tmp_path / "pool.json"), "--json")
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report["speedup"] >= 2.0  # precondition: hits scenario shows the point
    path = _report(tmp_path, report, name="pool-real.json")
    r = _run_gate(path)
    assert r.returncode == 0, r.stderr
    r = _run_gate(path, "--json")
    checks = {c["name"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["pool_speedup"]["ok"] is True
    # a pool that barely beats naive (1.2x) fails
    path = _report(tmp_path, {"speedup": 1.2, "thrash": {"hits": 0}},
                   name="pool-slow.json")
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL pool_speedup" in r.stderr
    # thrash-only report without the hits number = bad shape, FAIL not skip
    path = _report(tmp_path, {"thrash": {"hits": 0}}, name="pool-noshape.json")
    r = _run_gate(path)
    assert r.returncode == 1 and "FAIL pool_speedup" in r.stderr
    # the floor is flag-settable
    path = _report(tmp_path, {"speedup": 5.4}, name="pool-54.json")
    r = _run_gate(path, "--min-speedup", "6")
    assert r.returncode == 1


def test_gate_check_docs_reads_benchmarks(tmp_path):  # T684: no docs/default drift
    path = _report(tmp_path, {"n": 300, "rule_acc": 0.403})
    # against the real BENCHMARKS.md: documented numbers == enforced defaults
    r = _run_gate(path, "--check-docs")
    assert r.returncode == 0, r.stderr
    r = _run_gate(path, "--check-docs", "--json")
    checks = {c["name"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["docs_regex_floor"]["ok"] is True
    assert checks["docs_max_ece"]["value"] == 0.15
    assert checks["docs_max_p95_ms_t4"]["value"] == 44.0
    assert checks["docs_pool_speedup_floor"]["value"] == 2.0
    # a drifted table fails loudly, even when every report gate passes
    bench = tmp_path / "BENCHMARKS.md"
    bench.write_text(
        "# Bench\n\n## Known numbers (test)\n\n| metric | value |\n|---|---|\n"
        "| regex_floor | 0.480 |\n| max_ece | 0.15 |\n| max_p95_ms_t4 | 44 |\n"
        "| pool_speedup_floor | 2.0 |\n")
    r = _run_gate(path, "--check-docs", str(bench))
    assert r.returncode == 1 and "docs_regex_floor" in r.stderr
    # a table missing an enforced row fails too (drift by omission, not skip)
    bench.write_text(
        "# Bench\n\n## Known numbers\n\n| metric | value |\n|---|---|\n"
        "| max_ece | 0.15 |\n")
    r = _run_gate(path, "--check-docs", str(bench))
    assert r.returncode == 1 and "docs_regex_floor" in r.stderr
    # an unreadable doc is unusable input -> exit 2
    r = _run_gate(path, "--check-docs", str(tmp_path / "nope.md"))
    assert r.returncode == 2 and "cannot read docs" in r.stderr


def test_known_numbers_table_status_column():  # T815: refreshed or explicitly stale
    import re
    text = Path("BENCHMARKS.md").read_text()
    i = text.index("## Known numbers")
    section = text[i:i + 1400]
    # the status column exists and every row carries a verdict
    assert "| status (T815" in section
    # the two _acc reference rows are honestly labelled: the regex baseline
    # re-measured green, the zero-shot number marked STALE (weightless envs
    # have neither laya nor the 12k dataset — it cannot be refreshed here)
    for needle in ("| zero_shot_rule_acc | 0.305 | **STALE**", "T108 CPU kernel",
                   "| regex_baseline_acc | 0.403 | refreshed 2026-10-19"):
        assert needle in section, needle
    # the threshold rows name the flag that enforces them
    for needle in ("`--min-rule-acc`", "`--max-ece`", "`--max-p95-ms`",
                   "`--min-speedup`", "`--max-import-p50-ms`"):
        assert needle in section, needle
    # the gate's parser only reads the first two columns — the extra column
    # cannot cause docs/default drift (verified live: --check-docs rc=0)
    assert re.search(r"\|\s*regex_floor\s*\|\s*0\.403\s*\|", section)


def test_gate_stale_report_warning(tmp_path):  # T685: warn, never re-verdict
    import os
    import time
    path = _report(tmp_path, {"n": 300, "rule_acc": 0.403})
    r = _run_gate(path)
    assert r.returncode == 0 and "warning" not in r.stderr  # fresh: no noise
    old = time.time() - 30 * 86400
    os.utime(path, (old, old))
    r = _run_gate(path)
    assert r.returncode == 0  # a stale report warns, it does not fail
    assert "warning" in r.stderr and "30d" in r.stderr
    # the window is flag-settable; wide enough -> no warning
    r = _run_gate(path, "--max-report-age-days", "365")
    assert r.returncode == 0 and "warning" not in r.stderr
    # 0 disables the check entirely
    r = _run_gate(path, "--max-report-age-days", "0")
    assert r.returncode == 0 and "warning" not in r.stderr
    # --ci stdout stays one clean line; the warning lives on stderr
    r = _run_gate(path, "--ci")
    assert len(r.stdout.strip().splitlines()) == 1 and "warning" in r.stderr


def test_latest_report_pointer(tmp_path):  # T686
    sys.path.insert(0, "src")
    sys.path.insert(0, "eval")
    from eval_gatekeeper import write_latest
    report = {"n": 300, "rule_acc": 0.403, "ece": 0.12}
    out_dir = str(tmp_path / "reports")
    write_latest(report, "eval/reports/zero-shot-2026-10-17.json", out_dir=out_dir)
    import os
    latest = os.path.join(out_dir, "latest.json")
    doc = json.loads((tmp_path / "reports" / "latest.json").read_text())
    assert doc["n"] == 300 and doc["rule_acc"] == 0.403  # the report itself...
    assert doc["_source"].endswith("zero-shot-2026-10-17.json")  # ...plus provenance
    assert doc["_generated_at"]
    # a second run overwrites — latest is always the newest
    write_latest({"n": 9, "rule_acc": 0.5}, "second.json", out_dir=out_dir)
    doc = json.loads((tmp_path / "reports" / "latest.json").read_text())
    assert doc["n"] == 9
    # gate.py consumes it directly: underscore provenance keys are ignored
    r = _run_gate(latest)
    assert r.returncode == 0, r.stderr
    # and eval_gatekeeper's __main__ actually calls it after writing a report
    # — with the pointer beside --out (T815), so tmp runs never touch the
    # real eval/reports/latest.json
    src = Path("eval/eval_gatekeeper.py").read_text()
    assert "write_latest(report, a.out, out_dir=out_dir)" in src


def test_gate_fails_loudly_on_bad_reports(tmp_path):  # T687: the battery
    bad = {
        "empty": {},  # nothing to gate on
        "n_only": {"n": 300},  # missing rule_acc
        "acc_only": {"rule_acc": 0.9},  # missing n
        "n_is_string": {"n": "300", "rule_acc": 0.9},  # wrong types
        "acc_is_bool": {"n": 300, "rule_acc": True},  # bool is not a number
        "acc_is_nan": {"n": 300, "rule_acc": float("nan")},  # never a pass
        "acc_is_inf": {"n": 300, "rule_acc": float("inf")},  # never a pass
        "acc_out_of_range": {"n": 300, "rule_acc": 4.2},  # >1 accuracy is fiction
        "n_negative": {"n": -5, "rule_acc": 0.9},  # nonsense row count
        "ece_out_of_range": {"n": 300, "rule_acc": 0.9, "ece": 7.5},
    }
    for name, report in bad.items():
        path = _report(tmp_path, report, name=f"{name}.json")
        r = _run_gate(path, "--json")
        assert r.returncode == 1, f"{name}: bad report must fail, got 0"
        assert "FAIL" in r.stderr, f"{name}: failures must be loud on stderr"
        checks = {c["name"]: c for c in json.loads(r.stdout)["checks"]}
        assert any(c["ok"] is False for c in checks.values()), name
    # NaN/inf in a *metric* gate: never satisfied by the comparison, so the
    # gate skips (ok=None) — and a skip never turns a failing report green.
    path = _report(tmp_path, {"n": 300, "rule_acc": 0.9, "ece": float("nan")},
                   name="nan-metric.json")
    r = _run_gate(path, "--json")
    checks = {c["name"]: c for c in json.loads(r.stdout)["checks"]}
    assert checks["ece"]["ok"] is None  # skipped, not passed (T687: NaN-proof)
    # and the whole run still exits 0 only because nothing else failed — the
    # structural gates, not the NaN metric, carry that verdict
    assert r.returncode == 0 and checks["report_rule_acc"]["ok"] is True


def test_benchmarks_documents_running_the_gates():  # T688: the how-to is real
    text = Path("BENCHMARKS.md").read_text()
    assert "## Running the gates" in text
    for token in ("eval/gate.py", "--ci", "--against", "--check-docs",
                  "--changelog", "exit", "0", "1", "2"):
        assert token in text
    # the four families gate.py dispatches to are all documented
    for family in ("rule_acc", "per_lang", "tripped", "speedup"):
        assert family in text
    # defaults named in the docs match the flags in the runner (no doc drift)
    assert "--min-rule-acc" in text and "--max-ece" in text
    assert "--max-p95-ms" in text and "--min-speedup" in text


def test_gate_all_make_style_command(tmp_path):  # T689: one command, whole dir
    rd = tmp_path / "reports"
    rd.mkdir()
    # nothing to gate yet -> exit 2, told to run the producers first
    r = _run_gate("--all", "--reports-dir", str(rd))
    assert r.returncode == 2 and "no reports" in r.stderr
    # one healthy report per family
    (rd / "latest.json").write_text(json.dumps({"n": 300, "rule_acc": 0.403}))
    (rd / "i18n.json").write_text(json.dumps({"n": 12, "errors": [], "per_lang": {}}))
    (rd / "breaker.json").write_text(json.dumps({"tripped": True, "closed": True}))
    (rd / "pool.json").write_text(json.dumps({"speedup": 5.4}))
    r = _run_gate("--all", "--reports-dir", str(rd))
    assert r.returncode == 0, r.stderr
    for name in ("latest.json", "i18n.json", "breaker.json", "pool.json"):
        assert f"== {name}: PASS" in r.stdout
    assert "GATE all: PASS (4 reports gated)" in r.stdout
    # one rotten report fails the whole run, naming file and gate
    (rd / "breaker.json").write_text(json.dumps({"tripped": True, "closed": False}))
    r = _run_gate("--all", "--reports-dir", str(rd))
    assert r.returncode == 1
    assert "== breaker.json: FAIL" in r.stdout
    assert "FAIL breaker.json/breaker_closed" in r.stderr
    assert "GATE all: FAIL" in r.stdout
    # a corrupt report file in the dir -> exit 2 (unusable input)
    (rd / "i18n.json").write_text("{broken")
    r = _run_gate("--all", "--reports-dir", str(rd))
    assert r.returncode == 2 and "unreadable" in r.stderr
    # --all + single-report-only flags is a usage error (exit 2 from argparse)
    r = _run_gate("--all", "--against", "x.json", "--reports-dir", str(rd))
    assert r.returncode == 2
    # and a bare invocation is a usage error too — never a silent 0
    r = _run_gate()
    assert r.returncode == 2


def test_p36_sweep_gate_invariants():  # T690: cross-cutting consistency
    sys.path.insert(0, "eval")
    import argparse

    import gate
    samples = [{"rule_acc": 0.5}, {"per_lang": {}}, {"tripped": True},
               {"closed": False}, {"speedup": 3.0}, {"thrash": {}},
               {"bench": "bench_stub", "p50_ms": 0.1},  # T766: perf family
               {"bench": "bench_metrics", "p50_ms": 1.0,  # T948: metrics family
                "format_ok": True, "help_complete": True}]
    # every detectable report shape maps to a registered collector...
    for rep in samples:
        assert gate.detect_kind(rep) in gate.COLLECTORS, rep
    assert set(gate.COLLECTORS) == {"eval", "i18n", "breaker", "pool", "perf",
                                    "metrics"}
    # ...and every collector emits >= 1 check with the shared {name, expected,
    # value, ok} shape — a family that emits nothing could never fail.
    args = argparse.Namespace(min_n=1, min_rule_acc=0.403, max_ece=0.15,
                              max_p95_ms=44.0, min_abstention=0.0,
                              max_abstention=0.3, min_per_rule_acc=0.3,
                              per_rule_min_n=5, min_speedup=2.0,
                              max_stub_p50_ms=5.0, max_import_p50_ms=200.0,  # T766
                              max_stats_p95_ms=250.0, max_warm_p50_ms=50.0,
                              max_questions_p50_ms=20.0, max_batch_row_ms=50.0,
                              max_metrics_p50_ms=100.0)  # T948
    for rep in samples:
        checks = gate.COLLECTORS[gate.detect_kind(rep)](rep, args)
        assert checks, rep
        assert all(set(c) == {"name", "expected", "value", "ok"} for c in checks)
    # the rule_acc gate carries the report accuracy even when per-rule data is
    # iterated — no loop variable may leak into report-level results (T690)
    checks = gate.collect({"rule_acc": 0.403, "n": 100,
                           "per_rule": {"ok": [90, 100]}}, args)
    by_name = {c["name"]: c for c in checks}
    assert by_name["rule_acc"]["ok"] is True and by_name["rule_acc"]["value"] == 0.403
    # every threshold flag appears in both --help and the BENCHMARKS gates
    # section — the how-to and the runner cannot drift apart
    text = Path("BENCHMARKS.md").read_text()
    help_out = _run_gate("--help").stdout
    for flag in ("--min-rule-acc", "--max-ece", "--max-p95-ms",
                 "--min-abstention", "--max-abstention", "--min-per-rule-acc",
                 "--per-rule-min-n", "--min-speedup",
                 "--max-stub-p50-ms", "--max-import-p50-ms",  # T766
                 "--max-stats-p95-ms", "--max-warm-p50-ms",
                 "--max-questions-p50-ms", "--max-batch-row-ms"):
        assert flag in help_out, flag
        assert flag in text, flag
