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
