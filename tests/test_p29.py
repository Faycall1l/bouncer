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
