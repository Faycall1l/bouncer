"""P29 tests (T531-T550): CLI. No weights."""
import subprocess
import sys

sys.path.insert(0, "src")


def test_models_and_presets_commands():  # T538+T539
    r = subprocess.run([sys.executable, "-m", "gatekeeper.cli", "models"],
                       check=False, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"})
    assert r.returncode == 0 and "multilingual" in r.stdout and "pool:" in r.stdout
    r = subprocess.run([sys.executable, "-m", "gatekeeper.cli", "presets"],
                       check=False, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"})
    assert r.returncode == 0 and "gaming" in r.stdout and "study" in r.stdout


def test_review_prune_and_filters(monkeypatch):  # T537+T540+T543
    import importlib

    import gatekeeper.review as _rv
    from gatekeeper.cli import main
    q = "/tmp/p29-review-test.jsonl"
    monkeypatch.setenv("BOUNCER_REVIEW", q)
    importlib.reload(_rv)
    _rv.clear_queue()
    _rv.add("p29 row one", {"action": "flag", "rule": "no-spam", "confidence": 0.9})
    _rv.add("p29 row two", {"action": "delete", "rule": "no-scams", "confidence": 0.95})
    assert main(["review", "--rule", "no-spam"]) == 0
    assert main(["review", "--prune", "--older-than", "-1"]) == 0  # everything aged out
    assert _rv.list_queue() == []
    _rv.clear_queue()


def test_export_action_filter(monkeypatch, tmp_path):  # T544
    import importlib

    import gatekeeper.audit as _au
    from gatekeeper.cli import main
    pa = str(tmp_path / "a.jsonl")
    monkeypatch.setenv("BOUNCER_AUDIT", pa)
    importlib.reload(_au)
    _au.log_decision("p29 allow msg", "ok", 0.9, "allow", 1.0)
    _au.log_decision("p29 bad msg", "no-spam", 0.95, "delete", 2.0)
    out = tmp_path / "only.csv"
    assert main(["export", "--out", str(out), "--action", "delete"]) == 0
    body = out.read_text().splitlines()
    assert len(body) == 2 and "delete" in body[1] and "allow" not in body[1]


def test_pack_init(tmp_path):  # T545
    import json as _json

    from gatekeeper.cli import main
    f = str(tmp_path / "pack.json")
    assert main(["pack", "init", f, "--preset", "study"]) == 0
    rules = _json.loads((tmp_path / "pack.json").read_text())
    assert isinstance(rules, dict) and len(rules) >= 3
    assert main(["pack", "init", f, "--preset", "study"]) == 4  # refuses overwrite
    assert main(["pack", "init", f, "--preset", "study", "--force"]) == 0


def test_serve_key_file(tmp_path, monkeypatch):  # T547
    import os
    import sys as _sys
    import types as _types

    from gatekeeper.cli import _cmd_serve

    class Args:
        host, port, workers, key_file = "127.0.0.1", 8000, 1, None
    fake = _types.ModuleType("uvicorn")
    fake.run = lambda *x, **k: None
    monkeypatch.setitem(_sys.modules, "uvicorn", fake)
    monkeypatch.delenv("BOUNCER_API_KEY", raising=False)
    a = Args()
    a.key_file = str(tmp_path / "missing")
    assert _cmd_serve(a) == 4  # unreadable file, refuses to serve
    keyf = tmp_path / "key"
    keyf.write_text("  s3cret-key \n")
    a.key_file = str(keyf)
    assert _cmd_serve(a) == 0 and os.environ["BOUNCER_API_KEY"] == "s3cret-key"
    empty = tmp_path / "empty"
    empty.write_text("")
    a.key_file = str(empty)
    assert _cmd_serve(a) == 4
