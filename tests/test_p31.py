"""P31 tests (T571-T590): eval/data scripts run weightless. No laya, no weights."""
import json
import os
import subprocess
import sys

sys.path.insert(0, "src")

ENV = {**os.environ, "PATH": "/usr/bin:/bin", "PYTHONPATH": "src"}


def _run(*args):
    return subprocess.run([sys.executable, *args], check=False, capture_output=True,
                          text=True, env=ENV, timeout=60)


def test_breaker_sim_weightless(tmp_path):  # T580+T589
    out = str(tmp_path / "breaker.json")
    r = _run("eval/breaker_sim.py", "--storm", "3", "--cool", "0.2",
             "--out", out, "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)  # --json prints one line
    assert rep["tripped"] is True and rep["closed"] is True  # opens, then half-open recovers
    keys = {"storm_n", "cool_s", "tripped", "closed", "last_cause", "events"}
    assert keys <= set(rep)  # T589: report keys pinned
    assert os.path.exists(out)
    with open(out) as f:
        assert json.load(f)["events"] == rep["events"]  # report file matches stdout


def test_pool_bench_weightless(tmp_path):  # T581
    out = str(tmp_path / "pool.json")
    r = _run("eval/bench_pool.py", "--max-n", "2", "--requests", "6",
             "--out", out, "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["stats"]["size"] == 2 and rep["pooled_s"] < rep["naive_s"] * 2
    assert rep["thrash"]["stats"]["evictions"] > 0  # eviction demo always fires
    with open(out) as f:
        assert json.load(f)["stats"] == rep["stats"]


def test_synth_report_shape():  # T582
    r = _run("data/synth_rules.py", "--n", "20", "--template-only",
             "--seed", "7", "--report")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["n"] == 20
    assert set(rep) == {"n", "rule", "harm", "jailbreak", "escalate"}
    assert sum(rep["rule"].values()) == 20  # rule labels partition the rows
    assert sum(rep["harm"].values()) == 20
    # seed pins the distribution: same flags -> same counts (T382 reproducibility)
    again = json.loads(_run("data/synth_rules.py", "--n", "20", "--template-only",
                            "--seed", "7", "--report").stdout)
    assert again == rep
