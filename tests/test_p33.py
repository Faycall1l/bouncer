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


def test_preset_as_rules_e2e_and_default(monkeypatch):  # T618
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    class Stub:
        """Answers by rule id present in the pack: link -> delete-grade conf."""

        def predict(self, state, questions):
            has_no_spam = any("no-spam" in r or "sin-spam" in r
                              for r in state["rules"])
            conf = 0.96 if has_no_spam else 0.5
            return {"answers": {
                "rule": {"choice": "ok" if not has_no_spam else "no-spam",
                         "confidence": conf,
                         "probabilities": {"ok": 1 - conf, "no-spam": conf}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    gatekeeper._router = Stub()
    from gatekeeper.cache import CACHE
    CACHE.clear()
    serve._BUCKETS.clear()
    c = TestClient(serve.app)
    msg = "buy crypto http://free-coins.example"
    # preset pack drives the decision end-to-end (rules reach the router)
    r = c.post("/predict", json={"message": msg, "preset": "gaming"})
    assert r.status_code == 200
    assert r.json()["action"] == "delete" and r.json()["rule"] == "no-spam"
    # same text with a pack that has no no-spam rule: no violation to match
    r = c.post("/predict", json={"message": msg, "preset": "study"})
    assert r.status_code == 200 and r.json()["action"] != "delete"
    # neither rules nor preset -> env default kicks in (T475)
    monkeypatch.setenv("BOUNCER_DEFAULT_PRESET", "gaming")
    r = c.post("/predict", json={"message": msg})
    assert r.status_code == 200 and r.json()["rule"] == "no-spam"
    monkeypatch.delenv("BOUNCER_DEFAULT_PRESET")
    r = c.post("/predict", json={"message": msg})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E_PRESET"


def test_pool_eviction_under_max():  # T616
    from gatekeeper.pool import RouterPool
    built = []

    def factory(**kw):
        built.append(kw)
        return kw

    p = RouterPool(max_n=2, factory=factory)
    p.get(model="english")
    p.get(model="multilingual")
    assert p.stats() == {"size": 2, "max_n": 2, "hits": 0, "creates": 2,
                         "evictions": 0}
    p.get(model="typed-decisions")  # third key, no free slot -> evict LRU
    s = p.stats()
    assert s["size"] == 2 and s["evictions"] == 1 and s["creates"] == 3
    # the evicted one (english, least recent) is rebuilt on next use
    p.get(model="english")
    s = p.stats()
    assert s["creates"] == 4 and s["evictions"] == 2
    # same kwargs hit the cache: no new build
    p.get(model="english")
    assert len(built) == 4 and p.stats()["hits"] == 1
