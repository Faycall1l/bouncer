"""P21 tests (T371-T390): eval helpers, no weights (subprocess for scripts)."""
import json
import os
import subprocess
import sys

sys.path.insert(0, "src")

PY = sys.executable
ENV = dict(os.environ, PYTHONPATH="src")


def test_ece_brier_goldens():  # T390
    sys.path.insert(0, "eval")
    from eval_gatekeeper import brier, ece
    assert ece([1.0, 1.0, 0.0, 0.0], [True, True, False, False]) == 0.0
    assert brier([1.0, 0.0], [True, False]) == 0.0
    assert brier([0.5, 0.5], [True, False]) == 0.25


def test_eval_help_weightless():  # T371
    r = subprocess.run([PY, "eval/eval_gatekeeper.py", "--help"], capture_output=True,
                       text=True, env=ENV, check=False)
    assert r.returncode == 0 and "--limit" in r.stdout and "--out" in r.stdout


def test_baseline_json():  # T379+T380
    r = subprocess.run([PY, "eval/baseline_regex.py", "--json"], capture_output=True,
                       text=True, env=ENV, check=False)
    assert r.returncode == 0
    doc = json.loads(r.stdout.splitlines()[-1])
    assert doc["n"] == 300 and "per_label" in doc and "regex_acc" in doc


def test_validate_data():  # T381
    sys.path.insert(0, "eval")
    from validate_data import check_file, check_row
    assert check_file("data/examples.jsonl") == []
    assert check_row({"state": {"message": 5, "rules": {}}, "labels": {}}, 0) != []
    assert check_row("nope", 3) != []


def test_synth_seed_reproducible(tmp_path):  # T382
    sys.path.insert(0, "data")
    import random

    import synth_rules
    random.seed(7)
    a = synth_rules.template_rows(20)
    random.seed(7)
    b = synth_rules.template_rows(20)
    assert a == b
    r = subprocess.run([PY, "data/synth_rules.py", "--help"], capture_output=True,
                       text=True, env=ENV, check=False)
    assert "--seed" in r.stdout
