"""P36 tests (T671-T690): eval gates. Weightless — thresholds over report JSONs."""
import json
import subprocess
import sys


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
