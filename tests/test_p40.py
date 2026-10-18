"""P40 tests (T751-T770): performance — weightless paths only."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "src")

ROOT = Path.cwd()


def _run(*args, timeout=120, cwd=None, env=None):
    return subprocess.run([sys.executable, *args], check=False,
                          capture_output=True, text=True, timeout=timeout,
                          cwd=str(cwd or ROOT), env=env)


def test_bench_warm_stub_mechanics_and_refusal(tmp_path):  # T751
    import re
    # stub mode runs anywhere and labels itself: a bench that can't see
    # the model must never pass its overhead off as model latency
    out = tmp_path / "warm.json"
    r = _run("eval/bench_warm.py", "--stub", "--n", "10", "--json",
             "--out", str(out))
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    assert rep["mode"] == "stub"
    assert rep["n"] == 10
    for k in ("cold_ms", "p50_ms", "p95_ms", "pool"):
        assert k in rep, k
    # the warm path is the one measured: one resident, every loop call a
    # hit (10) plus the cache-replay call (1) — T752 rides along here too
    assert rep["pool"]["creates"] == 1 and rep["pool"]["hits"] == 11
    # real mode without weights refuses loudly and writes nothing —
    # E_WARM, no invented report (this env has no laya at all)
    out2 = tmp_path / "warm-real.json"
    r = _run("eval/bench_warm.py", "--n", "5", "--out", str(out2))
    assert r.returncode == 1, r.stdout
    assert "E_WARM" in r.stderr
    assert not out2.exists(), "a refusing bench must write no report"
    # the method is documented where every other number lives
    doc = Path("BENCHMARKS.md").read_text()
    m = re.search(r"## Warm-pool latency \(T751\)\n(.*?)(?=\n## )", doc,
                  re.DOTALL)
    assert m, "no Warm-pool section in BENCHMARKS.md"
    section = m.group(1)
    for needle in ("bench_warm.py", "COLD", "WARM", "CACHE", "--stub",
                   "E_WARM", "mode: \"real\"", "hits==n+1", "cache_hit_ms"):
        assert needle in section, needle


def test_bench_warm_reports_cache_hit_latency(tmp_path):  # T752
    out = tmp_path / "warm.json"
    r = _run("eval/bench_warm.py", "--stub", "--n", "5", "--json",
             "--out", str(out))
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    # the cache-hit number is in the report — and the receipt says it was
    # a genuine cache hit (message 0 replayed with identical rules),
    # never a model call in disguise
    assert isinstance(rep["cache_hit_ms"], (int, float))
    assert rep["cache_hit"] is True
    # the replay also went through the warm pool: one more hit, still one
    # resident — the cache number isn't a cold-path number either
    assert rep["pool"]["hits"] == 6 and rep["pool"]["creates"] == 1


def test_batch_sweep_table_matches_the_sweep(tmp_path):  # T753
    import os
    import re
    # re-run the sweep itself (stub — weightless by design): its combos are
    # the source of truth the docs table must track. The machine-dependent
    # numbers are NOT pinned — only the shape can drift silently.
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = _run(str(ROOT / "eval/bench_batch.py"), cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)["rows"]
    combos = {tuple(int(x) for x in k.replace("batch", "").split("/chunk"))
              for k in rows}
    # the table in BENCHMARKS.md has exactly the sweep's combos, refreshed
    doc = Path("BENCHMARKS.md").read_text()
    m = re.search(r"\| batch \|(.*?)~0\.\d+ms/message", doc, re.DOTALL)
    assert m, "no batch table under Stub overhead"
    table = m.group(1)
    assert "table refreshed T753" in doc[:m.end()], "table not marked as re-run"
    cells = re.findall(r"^\| (\d+) \|(.+)\|$", table, re.MULTILINE)
    assert cells, "no table rows"
    shown = set()
    for batch, rest in cells:
        nums = re.findall(r"(\d+\.\d+)", rest)
        assert len(nums) == 4, f"batch {batch}: {rest}"  # 4 chunk columns
        for chunk in (1, 4, 8, 16):
            shown.add((int(batch), chunk))
    assert shown == combos, f"table {sorted(shown)} != sweep {sorted(combos)}"


def test_coalescing_effectiveness_metric_in_stats():  # T754
    import os
    import threading
    import time

    from gatekeeper import coalesce_stats, moderate

    class Slow:
        def predict(self, state, questions):
            time.sleep(0.3)
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95,
                         "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    before = coalesce_stats()
    msg = f"p754 coalesce {os.getpid()}-{time.time_ns()}"  # cache-unique
    rules = {"plain-chat": "normal talk"}
    outs = []
    gate = threading.Barrier(2)  # both calls enter together: the join is
    # guaranteed (the 0.3s predict dwarfs any thread-start jitter)

    def one():
        gate.wait()
        outs.append(moderate(msg, rules, router=Slow()))

    ts = [threading.Thread(target=one) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    after = coalesce_stats()
    # two model-path calls, one actual computation: total +2, joined +1,
    # and the ratio is exactly joined/total (0.0 at total==0 is the floor)
    assert after["total"] == before["total"] + 2
    assert after["joined"] == before["joined"] + 1
    assert after["ratio"] == round(after["joined"] / after["total"], 3)
    assert len(outs) == 2 and any(o.get("coalesced") for o in outs)
    # /stats carries the metric to operators
    from fastapi.testclient import TestClient

    from gatekeeper.serve import app
    coal = TestClient(app).get("/stats").json()["coalesce"]
    assert set(coal) == {"joined", "total", "ratio"}
    assert coal["total"] >= after["total"]


def test_question_count_knob(tmp_path, monkeypatch):  # T755
    import os

    import pytest

    from gatekeeper import GateConfig, moderate
    from gatekeeper.config import ConfigError

    def ans(qid):
        if qid == "rule":
            return {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}}
        if qid in ("jailbreak", "escalate"):
            return {"noul": 0.0}
        return {"score": "safe", "probabilities": []}

    class S:
        def __init__(self):
            self.seen = []

        def predict(self, state, questions):
            self.seen.append(set(questions))
            return {"answers": {qid: ans(qid) for qid in questions}}

    # light mode sends exactly the decision trio and the result still
    # decodes — dropped harm/hype default neutral (documented, not hidden)
    s3 = S()
    r3 = moderate("p755 light", {"a": "rule a"},
                  config=GateConfig(questions=3), router=s3)
    assert s3.seen == [{"rule", "jailbreak", "escalate"}]
    assert r3["action"] == "allow"
    assert (r3["harm"], r3["hype"]) == ("safe", "chill")
    # 5 is the untouched full set
    s5 = S()
    moderate("p755 full", {"a": "rule a"},
             config=GateConfig(questions=5), router=s5)
    assert len(s5.seen[0]) == 5
    # no silent 4: only the two supported sets, config and env alike
    with pytest.raises(ConfigError):
        GateConfig(questions=4)
    monkeypatch.setenv("BOUNCER_QUESTIONS", "3")
    s6 = S()
    moderate("p755 env", {"a": "rule a"}, router=s6)
    assert len(s6.seen[0]) == 3
    monkeypatch.setenv("BOUNCER_QUESTIONS", "banana")
    with pytest.raises(ConfigError):
        moderate("p755 env bad", {"a": "rule a"}, router=S())
    monkeypatch.delenv("BOUNCER_QUESTIONS")
    # 3q and 5q never share a cache entry: same message+rules asked twice
    # comes back as two real model calls (pre-T755 the second was a hit)
    s7 = S()
    moderate("p755 cache iso", {"a": "rule a"},
             config=GateConfig(questions=3), router=s7)
    moderate("p755 cache iso", {"a": "rule a"},
             config=GateConfig(questions=5), router=s7)
    assert [len(x) for x in s7.seen] == [3, 5]
    # the bench reports both knob legs (stub: our overhead only, and the
    # BENCHMARKS entry says so — real-model savings stay unclaimed)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = _run(str(ROOT / "eval/bench_questions.py"), "20", cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["p50_knob_3q_ms"] >= 0 and rep["p50_knob_5q_ms"] >= 0
    doc = Path("BENCHMARKS.md").read_text()
    for needle in ("T755", "BOUNCER_QUESTIONS", "not\nclaimed", "require_calm"):
        assert needle in doc, needle


def test_context_token_budget_truncates_and_reports():  # T756
    import pytest

    from gatekeeper import GateConfig, moderate
    from gatekeeper.config import ConfigError

    def ans(qid):
        if qid == "rule":
            return {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}}
        if qid in ("jailbreak", "escalate"):
            return {"noul": 0.0}
        return {"score": "safe", "probabilities": []}

    class S:
        def __init__(self):
            self.hist = None

        def predict(self, state, questions):
            self.hist = list(state["history"])
            return {"answers": {qid: ans(qid) for qid in questions}}

    ctx = [f"u: line {i} " + "x" * 360 for i in range(20)]  # ~92 est tokens each
    # the default budget keeps the whole history_n window: nothing drops
    s1 = S()
    r1 = moderate("p756 default", {"a": "r"}, context=ctx,
                  config=GateConfig(), router=s1)
    assert r1["context"] == {"items": 4, "tokens_est": 368, "cap": 1000,
                             "dropped": 0}
    assert len(s1.hist) == 4  # the report matches what the model received
    # a tight budget keeps the NEWEST line and drops the rest — and the
    # decision reports the drop instead of hiding it
    s2 = S()
    r2 = moderate("p756 tight", {"a": "r"}, context=ctx,
                  config=GateConfig(max_context_tokens=150), router=s2)
    assert r2["context"] == {"items": 1, "tokens_est": 92, "cap": 150,
                             "dropped": 3}
    assert s2.hist == [ctx[19][:500]]  # newest kept, oldest gone
    # 0 = unlimited (documented), negative is a config error
    r3 = moderate("p756 off", {"a": "r"}, context=ctx,
                  config=GateConfig(max_context_tokens=0), router=S())
    assert r3["context"]["dropped"] == 0 and r3["context"]["items"] == 4
    with pytest.raises(ConfigError):
        GateConfig(max_context_tokens=-1)
    # docs carry the auditable-guard description
    doc = Path("docs/thresholds.md").read_text()
    for needle in ("max_context_tokens", "tokens_est", "chars/4"):
        assert needle in doc, needle


def test_watch_throughput_summary(monkeypatch, capsys):  # T757
    import io
    import re

    import gatekeeper
    from gatekeeper.cache import CACHE
    from gatekeeper.cli import main

    class Stub:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95,
                         "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe"}, "hype": {"score": "chill"},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    monkeypatch.setattr(gatekeeper, "_router", Stub())  # no weights in CI
    CACHE.clear()
    # 100 lines: one heartbeat (every 100th line, T326) + the EOF summary
    monkeypatch.setattr("sys.stdin", io.StringIO(
        "".join(f"p757 line {i}\n" for i in range(100))))
    assert main(["watch", "--preset", "gaming"]) == 0
    out, err = capsys.readouterr()
    rate = r"(\d+) lines in (\d+\.\d{2})s = (\d+\.\d) lines/sec"
    hits = re.findall(rate, err)
    assert len(hits) == 2, err  # heartbeat + EOF, both with the rate
    assert int(hits[0][0]) == 100 and int(hits[1][0]) == 100
    assert float(hits[1][2]) >= 0.0
    # the rate is a summary, never pipe noise: stdout stays clean (T286)
    assert "lines/sec" not in out and "throughput:" not in out


def test_audit_fsync_batching(tmp_path, monkeypatch):  # T758
    import json

    import gatekeeper.audit as au
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(au, "_PATH", str(path))
    monkeypatch.setattr(au, "_F", None)
    monkeypatch.setattr(au, "_SINCE", 0)
    fsyncs = []
    monkeypatch.setattr(au.os, "fsync", lambda fd: fsyncs.append(fd))
    # legacy default (N=0): no handle kept, no fsync — exact T029 behavior
    monkeypatch.setattr(au, "_FSYNC_N", 0)
    au.log_decision("legacy", "ok", 1.0, "allow", 1.0)
    assert au._F is None and fsyncs == []
    # batching N=3: the handle stays open; only the 3rd line syncs to disk
    monkeypatch.setattr(au, "_FSYNC_N", 3)
    for i in range(5):
        au.log_decision(f"m{i}", "ok", 1.0, "allow", 1.0)
    assert au._F is not None, "batching must keep one handle open"
    assert len(fsyncs) == 1
    # flush() drains the pending tail — the shutdown-hook contract
    au.flush()
    assert len(fsyncs) == 2 and au._SINCE == 0
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert len(rows) == 6 and all(r["rule"] == "ok" for r in rows)
    # rotation drops the stale handle: the next line lands in the fresh
    # file, never silently inside the rotated-away one
    monkeypatch.setattr(au, "_MAX_BYTES", 200)
    au.log_decision("big" * 100, "ok", 1.0, "allow", 1.0)
    assert (tmp_path / "audit.jsonl.1").exists()
    assert au._F is not None
    au._close_handle()
    # the flag ships with its durability contract in the README
    readme = Path("README.md").read_text()
    for needle in ("BOUNCER_AUDIT_FSYNC", "process-crash", "power-loss"):
        assert needle in readme, needle


def test_review_append_never_reads_the_file(tmp_path, monkeypatch):  # T759
    import builtins
    import json
    import os

    import gatekeeper.review as rv
    path = tmp_path / "queue.jsonl"
    monkeypatch.setattr(rv, "_PATH", str(path))
    # a queue that already has history: a full-file read would be visible
    old = json.dumps({"t": 1, "message": "old", "action": "flag", "rule": "r",
                      "conf": 0.9, "cause": "x", "ms": 1.0}) + "\n"
    path.write_text(old * 2000)
    real_open = builtins.open

    def spy(file, mode="r", *a, **kw):
        if os.fspath(file) == os.fspath(path) and mode != "a":
            raise AssertionError(f"append opened the queue for {mode!r}")
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy)
    rv.add("p759 new", {"action": "escalate", "rule": "r", "confidence": 0.9,
                        "latency_ms": 1.0})
    rows = real_open(path).read().splitlines()  # verification reads, add must not
    assert len(rows) == 2001
    row = json.loads(rows[-1])
    assert row["message"] == "p759 new" and row["action"] == "escalate"
    assert row["cause"] == "" and row["t"] >= 1  # T441/T448 shape intact


def test_stats_load_bench(tmp_path):  # T760
    import os
    src = Path("eval/bench_stats.py").read_text()
    # the box's constraint: no locust (a mention in prose is fine, an import is not)
    assert "import locust" not in src and "from locust" not in src
    out = tmp_path / "stats-load.json"
    r = _run(str(ROOT / "eval/bench_stats.py"), "--threads", "4", "--requests",
             "25", "--json", "--out", str(out), cwd=tmp_path,
             env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    assert r.returncode == 0, r.stderr  # nonzero when any request failed
    rep = json.loads(out.read_text())  # the report file is the contract
    assert rep["n"] == 100 and rep["ok"] == 100 and rep["errors"] == []
    assert rep["p50_ms"] >= 0 and rep["rps"] > 0
    # stdout's last line is the same report (access-log noise comes first)
    assert json.loads(r.stdout.splitlines()[-1])["n"] == 100
    # BENCHMARKS carries the measured numbers WITH their honest scope
    doc = Path("BENCHMARKS.md").read_text()
    for needle in ("T760", "940 rps", "TestClient", "NOT uvicorn"):
        assert needle in doc, needle


def test_release_memory_pool_hook(monkeypatch):  # T761
    import gatekeeper.pool as pl
    from gatekeeper import release_memory

    assert release_memory is pl.release_memory  # discoverable at top level
    fake = pl.RouterPool(max_n=2, factory=lambda **kw: object())
    monkeypatch.setattr(pl, "POOL", fake)  # the hook clears the module's POOL
    fake.get(device="cpu")
    fake.get(device="gpu")
    assert fake.stats()["size"] == 2
    stats = release_memory()
    # every resident is gone — and the lifetime record survives for logging
    assert stats == {"size": 0, "max_n": 2, "hits": 0, "creates": 2,
                     "evictions": 0}
    # the pool still works after the drop: the next get rebuilds (COLD again)
    assert fake.get(device="cpu") is not None
    assert fake.stats() == {"size": 1, "max_n": 2, "hits": 0, "creates": 3,
                            "evictions": 0}
    # the hook ships documented: README tells embedders when to call it
    readme = Path("README.md").read_text()
    for needle in ("release_memory()", "memory-pressure hook", "pays COLD"):
        assert needle in readme, needle


def test_lazy_gradio_import_and_import_bench(tmp_path):  # T762
    import os
    import re
    # no gatekeeper module imports gradio at top level — the demo extra is
    # paid for only by the demo command itself
    for f in (ROOT / "src" / "gatekeeper").glob("*.py"):
        top = re.findall(r"^(?:import gradio|from gradio)", f.read_text(),
                         re.MULTILINE)
        assert not top, f"{f.name} imports gradio eagerly"
    # proof in this gradio-less env: the demo module itself imports clean
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = _run("-c", "import gatekeeper.demo_app", env=env)
    assert r.returncode == 0, r.stderr
    # the import-time bench runs cold subprocesses and reports the receipt
    out = tmp_path / "import.json"
    r = _run(str(ROOT / "eval/bench_import.py"), "--n", "3", "--json",
             "--out", str(out), cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    assert rep["n"] == 3 and rep["p50_ms"] >= 0 and rep["budget_ms"] is None
    # the budget flag is a real gate: an impossible budget fails loudly
    r = _run(str(ROOT / "eval/bench_import.py"), "--n", "1",
             "--budget-ms", "0.001", cwd=tmp_path, env=env)
    assert r.returncode == 1 and "E_BUDGET" in r.stderr
    # BENCHMARKS carries the measured number and the lazy-demo receipt
    doc = Path("BENCHMARKS.md").read_text()
    for needle in ("T762", "30.4ms", "demo_app.build_app"):
        assert needle in doc, needle


def test_cli_version_cold_start_measured(tmp_path):  # T763
    import os
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    # the command itself: version prints and exits 0, no subcommand needed
    r = _run("-c", "from gatekeeper.cli import main; "
              "raise SystemExit(main(['--version']))", env=env)
    assert r.returncode == 0 and "bouncer" in r.stdout, r.stderr
    # the bench times exactly that command and self-labels the receipt
    out = tmp_path / "ver.json"
    r = _run(str(ROOT / "eval/bench_import.py"), "--version", "--n", "3",
             "--json", "--out", str(out), cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    assert rep["cmd"] == "version" and rep["n"] == 3
    assert rep["p50_ms"] >= 0 and rep["budget_ms"] is None
    # and the plain-import receipt stays distinguishable from it
    out2 = tmp_path / "imp.json"
    r = _run(str(ROOT / "eval/bench_import.py"), "--n", "3", "--out",
             str(out2), cwd=tmp_path, env=env)
    assert r.returncode == 0 and json.loads(out2.read_text())["cmd"] == "import"
    # docs carry the measured cold-start number with its honest scope
    doc = Path("BENCHMARKS.md").read_text()
    for needle in ("T763", "57.4ms", "console-script shim"):
        assert needle in doc, needle


def test_wheel_import_time_budget_200ms(tmp_path):  # T764
    import os
    # the wheel is a pure copy of these sources: no binary extension can
    # hide import cost that the src-layout measurement doesn't see
    binaries = [p for p in (ROOT / "src" / "gatekeeper").rglob("*")
                if p.suffix in (".so", ".pyd", ".dll", ".dylib")]
    assert not binaries, f"binary extensions: {binaries}"
    # enforce the budget through the bench's own gate: exit 1 + E_BUDGET
    # when p50 crosses 200ms (the negative case is pinned in T762)
    out = tmp_path / "import.json"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = _run(str(ROOT / "eval/bench_import.py"), "--n", "3",
             "--budget-ms", "200", "--json", "--out", str(out),
             cwd=tmp_path, env=env)
    assert r.returncode == 0, f"import budget blown: {r.stderr}"
    rep = json.loads(out.read_text())
    assert rep["budget_ms"] == 200.0 and rep["p50_ms"] <= 200.0
    # CI runs this on every push across the 3.10-3.13 matrix (test job)
    ci = Path(".github/workflows/ci.yml").read_text()
    assert "matrix" in ci and "3.10" in ci and "3.13" in ci
    # the budget is documented where the number lives
    doc = Path("BENCHMARKS.md").read_text()
    assert "T764" in doc and "200ms" in doc


def test_bench_report_schema_fixed_keys(tmp_path):  # T765
    import os
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    # static: every bench_*.py that WRITES a JSON report declares the
    # envelope (print-only scripts like bench_latency emit no receipt)
    for f in sorted((ROOT / "eval").glob("bench_*.py")):
        src = f.read_text()
        if "eval/reports" not in src:
            continue
        for key in ('"bench":', '"schema":', '"mode":'):
            assert key in src, f"{f.name}: report lacks {key}"
    # live: cheap benches emit it end-to-end with their documented mode
    cases = [
        ("bench_warm", ("--stub", "--n", "3"), "stub"),
        ("bench_stats", ("--threads", "2", "--requests", "5"), "n/a"),
        ("bench_import", ("--n", "1"), "n/a"),
    ]
    for name, args, mode in cases:
        out = tmp_path / f"{name}.json"
        r = _run(str(ROOT / "eval" / f"{name}.py"), *args, "--json",
                 "--out", str(out), cwd=tmp_path, env=env)
        assert r.returncode == 0, f"{name}: {r.stderr}"
        rep = json.loads(out.read_text())
        assert rep["bench"] == name and rep["schema"] == 1, rep
        assert rep["mode"] == mode, f"{name}: {rep['mode']}"
    # the contract itself is documented
    doc = Path("BENCHMARKS.md").read_text()
    for needle in ("Bench report schema (T765)", "schema", "mode"):
        assert needle in doc, needle


def test_perf_regression_gate_wired_to_reports(tmp_path):  # T766
    import os
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    gate_py = str(ROOT / "eval" / "gate.py")
    # a REAL report passes: envelope + budget, exit 0
    out = tmp_path / "import.json"
    r = _run(str(ROOT / "eval" / "bench_import.py"), "--n", "1",
             "--out", str(out), cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    r = _run(gate_py, str(out), "--json", cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    v = json.loads(r.stdout)
    names = {c["name"]: c for c in v["checks"]}
    assert names["bench_schema"]["ok"] is True
    assert names["import_p50_ms"]["ok"] is True
    assert v["skipped"] == 0
    # over budget -> exit 1 and the check names itself on stderr
    rep = json.loads(out.read_text())
    rep["p50_ms"] = 99999.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(rep))
    r = _run(gate_py, str(bad), "--json", cwd=tmp_path, env=env)
    assert r.returncode == 1 and "FAIL import_p50_ms" in r.stderr
    # an unknown bench id is drift, not a skip: a new producer must register
    rep["p50_ms"], rep["bench"] = 1.0, "bench_newthing"
    bad.write_text(json.dumps(rep))
    r = _run(gate_py, str(bad), "--json", cwd=tmp_path, env=env)
    assert r.returncode == 1 and "FAIL bench_id" in r.stderr
    # a missing envelope key FAILs (unusable report), never skips
    del rep["mode"]
    bad.write_text(json.dumps(rep))
    r = _run(gate_py, str(bad), "--json", cwd=tmp_path, env=env)
    assert r.returncode == 1 and "FAIL bench_mode" in r.stderr
    # a missing METRIC skips (documented contract) without failing
    rep2 = json.loads(out.read_text())
    del rep2["p50_ms"]
    bad.write_text(json.dumps(rep2))
    r = _run(gate_py, str(bad), "--json", cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    v = json.loads(r.stdout)
    assert v["skipped"] == 1 and v["failed"] == 0
    # CI generates the perf reports and gates them in the same job
    ci = Path(".github/workflows/ci.yml").read_text()
    for needle in ("bench_stub.py", "bench_warm.py", "bench_import.py",
                   "gate.py --all --ci"):
        assert needle in ci, needle
    # docs carry the perf family row, its flags, and the import budget row
    doc = Path("BENCHMARKS.md").read_text()
    for needle in ("import_budget_ms | 200", "--max-stub-p50-ms",
                   "--max-batch-row-ms", "| perf |"):
        assert needle in doc, needle


def test_readme_perf_section_measured_dated():  # T767
    readme = Path("README.md").read_text()
    assert "## Performance (measured, dated" in readme
    section = readme.split("## Performance (measured, dated", 1)[1]
    bench = Path("BENCHMARKS.md").read_text()
    # every figure the README cites also lives in the method doc — the
    # README cannot show a number BENCHMARKS doesn't carry
    for needle in ("30.4ms", "57.4ms", "8.2ms", "11.3ms", "940 rps",
                   "1.4ms", "1.3ms", "0.2ms", "5.4"):
        assert needle in section, f"README perf section missing {needle}"
        assert needle in bench, f"BENCHMARKS missing {needle}"
    # dated on both bench days + the honest scope label
    assert "2026-10-18" in section and "2026-10-17" in section
    assert "stub" in section and "not claimed" in section
    # and the section says where enforcement lives (gates, not vibes)
    assert "eval/gate.py" in section and "200ms" in section


def test_before_after_finetune_columns_honest():  # T768
    bench = Path("BENCHMARKS.md").read_text()
    assert "## Before vs after finetune (T768)" in bench
    section = bench.split("## Before vs after finetune (T768)", 1)[1]
    section = section.split("\n## ", 1)[0]
    # one two-column table (three pipes per row incl. both borders)
    assert section.count("|---|---|---|") == 1
    # the after column is explicitly empty of numbers — "awaits" not values
    assert "empty on" in section and "awaits" in section
    # and the emptiness is a receipt rule, not forgetfulness
    for needle in ('mode:"real"', "T751 rule", "never from expectation",
                   "NOT a prediction", "T665"):
        assert needle in section, needle
    # every BEFORE figure cited is a number the rest of the file carries
    for needle in ("0.08ms", "0.2ms", "30.4ms", "57.4ms",
                   "1.4ms", "1.3ms", "0.305", "0.403"):
        assert needle in section, f"missing {needle}"
        assert bench.count(needle) >= 2, f"{needle} only appears here"
