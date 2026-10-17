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


_STUB_LAYA = '''
class Router:
    def __init__(self, **kw):
        pass

    def predict(self, state, questions, model=None, **kw):
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.9, "probabilities": {"ok": 0.9}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
'''


def test_eval_model_flag_in_report(tmp_path):  # T583
    (tmp_path / "laya.py").write_text(_STUB_LAYA)  # weightless stand-in for checkpoints
    data = tmp_path / "rows.jsonl"
    row = {"state": {"message": "hello there", "history": [],
                     "rules": {"be-kind": "be nice"}},
           "labels": {"rule": "ok", "harm": "safe", "hype": "chill",
                      "jailbreak": False, "escalate": False}}
    data.write_text(json.dumps(row) + "\n")
    env = {**ENV, "PYTHONPATH": f"src:{tmp_path}"}
    out = str(tmp_path / "rep.json")
    r = subprocess.run([sys.executable, "eval/eval_gatekeeper.py", str(data),
                        "--limit", "1", "--model", "english", "--out", out],
                       check=False, capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["model"] == "english"  # T583: flag reaches the report
    # default: no --model -> report says base-router
    r = subprocess.run([sys.executable, "eval/eval_gatekeeper.py", str(data),
                        "--limit", "1", "--out", str(tmp_path / "rep2.json")],
                       check=False, capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["model"] == "base-router"


def test_baseline_limit_truncates(tmp_path):  # T584
    rows = []
    for i in range(6):
        rows.append(json.dumps(
            {"state": {"message": f"msg {i}", "history": [], "rules": {"r": "t"}},
             "labels": {"rule": "ok", "harm": "safe", "hype": "chill",
                        "jailbreak": False, "escalate": False}}))
    data = tmp_path / "rows.jsonl"
    data.write_text("\n".join(rows) + "\n")
    full = _run("eval/baseline_regex.py", str(data), "--json")
    half = _run("eval/baseline_regex.py", str(data), "--limit", "3", "--json")
    assert full.returncode == half.returncode == 0, full.stderr + half.stderr
    assert json.loads([l for l in full.stdout.splitlines()
                       if l.startswith("{")][-1])["n"] == 6
    assert json.loads([l for l in half.stdout.splitlines()
                       if l.startswith("{")][-1])["n"] == 3  # T584: truncated
    empty = _run("eval/baseline_regex.py", str(data), "--limit", "0")
    assert empty.returncode == 0  # --limit 0 means no truncation (not "zero rows")
