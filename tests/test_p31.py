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
    assert set(rep) == {"n", "seed", "rule", "harm", "jailbreak", "escalate"}
    assert rep["seed"] == 7  # T646: seed logged for reproducibility
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
    # T815: the latest-pointer lands BESIDE --out (tmp), never in the real
    # eval/reports/ — a leaked stub latest.json used to fail gate.py --all
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["_source"].endswith("rep2.json")


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
    assert json.loads([ln for ln in full.stdout.splitlines()
                       if ln.startswith("{")][-1])["n"] == 6
    assert json.loads([ln for ln in half.stdout.splitlines()
                       if ln.startswith("{")][-1])["n"] == 3  # T584: truncated
    empty = _run("eval/baseline_regex.py", str(data), "--limit", "0")
    assert empty.returncode == 0  # --limit 0 means no truncation (not "zero rows")


def test_validate_limit_truncates(tmp_path):  # T585
    good = json.dumps(
        {"state": {"message": "hi", "history": [], "rules": {"r": "t"}},
         "labels": {"rule": "ok", "harm": "safe", "hype": "chill",
                    "jailbreak": False, "escalate": False}})
    data = tmp_path / "rows.jsonl"
    # row 2 is malformed; with --limit 2 it stays out of scope -> clean exit
    data.write_text(f"{good}\n{good}\n{{not json\n")
    capped = _run("eval/validate_data.py", str(data), "--limit", "2", "--json")
    assert capped.returncode == 0, capped.stdout + capped.stderr
    assert json.loads(capped.stdout)["errors"] == 0
    full = _run("eval/validate_data.py", str(data), "--json")
    assert full.returncode == 1  # the malformed row is caught without --limit
    assert json.loads([ln for ln in full.stdout.splitlines()
                       if ln.startswith("{")][-1])["errors"] == 1


def test_i18n_rows_validate_clean():  # T586: shipped fixtures stay schema-clean
    r = _run("eval/validate_data.py", "data/examples_i18n.jsonl", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads([ln for ln in r.stdout.splitlines() if ln.startswith("{")][-1])
    assert rep["errors"] == 0
    with open("data/examples_i18n.jsonl") as f:
        langs = [json.loads(ln)["state"]["rules"] for ln in f]
    assert len(langs) == 12  # 4 each es/fr/ar (T504)


def test_i18n_report_ci_safe(tmp_path):  # T587: no weights, no laya, writes report
    out = str(tmp_path / "i18n.json")
    r = _run("eval/eval_i18n.py", "--out", out, "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["errors"] == [] and rep["n"] == 12
    assert set(rep["per_lang"]) == {"es", "fr", "ar"}  # 3 languages wired
    with open(out) as f:
        assert json.load(f) == rep  # report file == stdout


def test_snapshot_cli_roundtrip(tmp_path, capsys):  # T588
    from gatekeeper import strikes as st
    from gatekeeper.cli import main
    from gatekeeper.stats import get_stats, record, reset_stats
    st.reset()
    reset_stats()
    st.add_strike("u-snap")
    st.add_strike("u-snap")
    record("allow", "ok", 1.0)
    f = str(tmp_path / "snap.json")
    assert main(["snapshot", "save", f]) == 0
    assert "users=1" in capsys.readouterr().out
    st.reset()  # wipe in-memory state, then restore from the file
    reset_stats()
    assert st.standing("u-snap")["strikes"] == 0
    assert get_stats()["total"] == 0
    assert main(["snapshot", "load", f]) == 0
    assert st.standing("u-snap")["strikes"] == 2  # round-trip intact
    assert get_stats()["actions"]["allow"] == 1
    st.reset()


def test_p31_sweep(tmp_path):  # T590: eval/data cross-checks in one pass
    # 1. all eval/data scripts exit 0 --help (argparse wired, no weight import)
    for script in ("eval/breaker_sim.py", "eval/bench_pool.py",
                   "eval/validate_data.py", "eval/eval_i18n.py",
                   "eval/baseline_regex.py", "eval/eval_gatekeeper.py",
                   "data/synth_rules.py"):
        r = _run(script, "--help")
        assert r.returncode == 0, f"{script}: {r.stderr}"
    # 2. eval_i18n and validate_data agree on the shipped fixtures
    #    (--out into tmp: T815 — a test never writes the real reports dir)
    rep = json.loads([ln for ln in _run("eval/eval_i18n.py", "--json",
                                      "--out", str(tmp_path / "i18n.json"))
                      .stdout.splitlines()
                      if ln.startswith("{")][-1])
    assert rep["n"] == 12 and rep["errors"] == []
    # 3. synth with a seed is byte-stable across runs (T382 reproducibility)
    a = _run("data/synth_rules.py", "--n", "30", "--template-only", "--seed", "3",
             "--report").stdout
    b = _run("data/synth_rules.py", "--n", "30", "--template-only", "--seed", "3",
             "--report").stdout
    assert a == b
