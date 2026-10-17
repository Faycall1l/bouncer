"""P40 tests (T751-T770): performance — weightless paths only."""
import json
import subprocess
import sys
from pathlib import Path

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
    # the warm path is the one measured: one resident, every call a hit
    assert rep["pool"]["creates"] == 1 and rep["pool"]["hits"] == 10
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
    for needle in ("bench_warm.py", "COLD", "WARM", "--stub", "E_WARM",
                   "mode: \"real\"", "hits==n"):
        assert needle in section, needle
