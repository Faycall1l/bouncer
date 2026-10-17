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
