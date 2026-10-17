"""P33 tests (T611-T630): release gates. No weights."""
import os
import subprocess
import sys

sys.path.insert(0, "src")

ENV = {**os.environ, "PATH": "/usr/bin:/bin", "PYTHONPATH": "src"}


def _run(*args):
    return subprocess.run([sys.executable, "-m", "gatekeeper.cli", *args],
                          check=False, capture_output=True, text=True, env=ENV,
                          timeout=60)


def test_new_cli_commands_help():  # T614
    for cmd in ("snapshot", "models", "presets", "export", "review", "pack"):
        r = _run(cmd, "--help")
        assert r.returncode == 0, f"{cmd}: {r.stderr}"
        assert "usage: bouncer" in r.stdout
    r = _run("snapshot", "--help")
    assert "save" in r.stdout and "load" in r.stdout  # actions listed
    r = _run("pack", "--help")
    assert "init" in r.stdout
    r = _run("--version")
    assert r.returncode == 0 and "0.3.0" in r.stdout  # T611+T624: via --version


def test_ready_and_preset_shapes():  # T615
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    class Stub:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95,
                         "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    gatekeeper._router = Stub()
    c = TestClient(serve.app)
    r = c.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True and body["model"] == "loaded"
    assert {"size", "max_n", "hits", "creates", "evictions"} <= set(body["pool"])
    r = c.get("/presets/gaming")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "gaming"
    pack = body["rules"]
    assert isinstance(pack, dict) and all(isinstance(v, str) for v in pack.values())
    assert "be-kind" in pack  # the gaming pack's core rule
    r = c.get("/presets/nope")
    assert r.status_code == 404
