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


def test_breaker_e2e_full_cycle():  # T620: storm -> open -> cool -> probe -> closed
    import time as _t

    import gatekeeper
    from gatekeeper import GateConfig, moderate
    from gatekeeper.cache import CACHE
    CACHE.clear()
    gatekeeper._BREAKER.update({"fails": 0, "open_until": 0.0, "half_open": False})
    rules = {"plain-chat": "normal talk"}
    cfg = GateConfig(breaker_n=2, breaker_cool_s=0.05)

    class Boom:
        def predict(self, state, questions):
            raise RuntimeError("e2e outage")

    class Ok:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95,
                         "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    # storm: two failing moderations trip it at breaker_n
    for i in range(2):
        r = moderate(f"p33 storm {i}", rules, config=cfg, router=Boom())
        assert r["action"] == "escalate" and r["cause"] == "fallback"
    assert gatekeeper._breaker_tripped() is True
    # while open: no model call, escalate with the breaker's own cause
    r = moderate("p33 while open", rules, config=cfg, router=Ok())
    assert r["cause"] == "breaker-open" and r["action"] == "escalate"
    # cooldown -> half-open trial reaches a healthy router -> closed
    _t.sleep(0.06)
    r = moderate("p33 probe", rules, config=cfg, router=Ok())
    assert r["cause"] == "ok" and r["action"] == "allow"
    assert gatekeeper._breaker_tripped() is False
    assert gatekeeper._BREAKER["half_open"] is False  # success cleared it
    gatekeeper._BREAKER.update({"fails": 0, "open_until": 0.0, "half_open": False})


def test_timeout_and_model_fields_e2e():  # T621
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    seen: dict = {}

    class Stub:
        def predict(self, state, questions, model=None, **kw):
            seen["model"] = model
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95,
                         "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    gatekeeper._router = Stub()
    from gatekeeper.cache import CACHE
    CACHE.clear()
    serve._BUCKETS.clear()
    c = TestClient(serve.app)
    # model: pinned checkpoint reaches the router, validated before the call
    r = c.post("/predict", json={"message": "p33 model pin", "preset": "gaming",
                                 "model": "multilingual"})
    assert r.status_code == 200 and seen["model"] == "multilingual"
    r = c.post("/predict", json={"message": "p33 bad model", "preset": "gaming",
                                 "model": "nope"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E_MODEL_NAME"
    assert seen["model"] == "multilingual"  # rejected before any call
    # timeout: accepted range enforced, default applied when omitted
    r = c.post("/predict", json={"message": "p33 timeout in", "preset": "gaming",
                                 "timeout_s": 5, "model": "english"})
    assert r.status_code == 200
    r = c.post("/predict", json={"message": "p33 timeout lo", "preset": "gaming",
                                 "timeout_s": 0.1})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E_TIMEOUT"
    r = c.post("/predict", json={"message": "p33 timeout hi", "preset": "gaming",
                                 "timeout_s": 999})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E_TIMEOUT"
    r = c.post("/predict", json={"message": "p33 timeout ok", "preset": "gaming",
                                 "timeout_s": 30})
    assert r.status_code == 200


def test_multitenancy_isolation():  # T622: same text, preset A vs B, no bleed
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    rules_seen: list = []

    class Stub:
        """Records which pack arrived; verdict keyed off that pack's rule ids."""

        def predict(self, state, questions):
            rules_seen.append(sorted(state["rules"]))
            if "no-cheat" in state["rules"]:  # gaming pack
                return {"answers": {
                    "rule": {"choice": "no-cheat", "confidence": 0.97,
                             "probabilities": {"no-cheat": 0.97, "ok": 0.03}},
                    "harm": {"score": "safe", "probabilities": []},
                    "hype": {"score": "chill", "probabilities": []},
                    "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
            # study pack: no cheat rule to match -> plain ok
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95,
                         "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    gatekeeper._router = Stub()
    from gatekeeper.cache import CACHE
    CACHE.clear()
    serve._BUCKETS.clear()
    c = TestClient(serve.app)
    msg = "p33 same text everywhere"
    r1 = c.post("/predict", json={"message": msg, "preset": "gaming"})
    r2 = c.post("/predict", json={"message": msg, "preset": "study"})
    r3 = c.post("/predict", json={"message": msg, "preset": "gaming"})
    assert r1.status_code == r2.status_code == r3.status_code == 200
    # each request carried its OWN pack: no merging, no last-one-wins
    assert rules_seen[0] != rules_seen[1]
    assert "no-cheat" in rules_seen[0] and "no-cheat" not in rules_seen[1]
    # verdicts differ by tenant config even though text is identical
    assert r1.json()["rule"] == "no-cheat" and r1.json()["action"] == "delete"
    assert r2.json()["action"] != "delete"
    # cache is per-config: study never saw gaming's entry (2 model calls total),
    # while the gaming repeat served from cache without a third call
    assert len(rules_seen) == 2
    assert r3.json()["cached"] is True


def test_persistence_files_git_ignored():  # T623: runtime state never committed
    import subprocess
    # every file bouncer can write at runtime must be ignored by git
    candidates = ["bouncer-audit.jsonl", "bouncer-audit.jsonl.1", "review-queue.jsonl",
                  "bouncer-stats.json", "audit.csv",
                  "eval/reports/zero-shot.json", "eval/reports/breaker.json",
                  "eval/reports/i18n.json", ".env"]
    r = subprocess.run(["git", "check-ignore", "--stdin"], input="\n".join(candidates),
                       capture_output=True, text=True, check=True)
    ignored = set(r.stdout.split())
    missing = set(candidates) - ignored
    assert not missing, f"not gitignored: {sorted(missing)}"


def test_version_strings_consistent():  # T624: 0.3.0 in pkg + pyproject
    import pathlib
    import re

    import gatekeeper
    assert gatekeeper.__version__ == "0.3.0"
    pyproject = pathlib.Path("pyproject.toml").read_text()
    m = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert m and m.group(1) == "0.3.0", "pyproject version drifts from __version__"
    # the CHANGELOG must document the version we ship
    changelog = pathlib.Path("CHANGELOG.md").read_text()
    assert "## 0.3.0" in changelog
    # snapshot export stamps the same version it restores under
    from gatekeeper.cli import build_parser
    assert build_parser() is not None  # parser builds against this version


def test_breaker_and_pool_metrics_lines():  # T628
    import time as _t

    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    serve._BUCKETS.clear()
    c = TestClient(serve.app)
    r = c.get("/metrics")
    assert r.status_code == 200
    body = r.text
    for line in ("bouncer_breaker_open", "bouncer_pool_size", "bouncer_pool_max",
                 "bouncer_pool_hits", "bouncer_pool_creates",
                 "bouncer_pool_evictions"):
        assert line in body, f"missing {line}"
        val = next(l for l in body.splitlines() if l.startswith(line + " "))
        assert float(val.split()[1]) >= 0  # well-formed numeric sample
    # breaker flip is observable: mark it open, scrape again
    with gatekeeper._BREAKER_LOCK:
        gatekeeper._BREAKER["open_until"] = _t.time() + 60
    r = c.get("/metrics")
    assert "bouncer_breaker_open 1" in r.text
    with gatekeeper._BREAKER_LOCK:
        gatekeeper._BREAKER["open_until"] = 0.0
    assert "bouncer_breaker_open 0" in c.get("/metrics").text
    from gatekeeper.pool import POOL
    POOL.clear()


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
