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
    assert "3 passed, 0 failed, 1 skipped -> PASS" in r.stdout


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
    assert verdict["ok"] is True and verdict["skipped"] == 1
    assert any(c["name"] == "ece" and c["ok"] is None for c in verdict["checks"])
