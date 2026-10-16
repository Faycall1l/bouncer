"""P23 tests (T411-T430): release gates. No weights."""
import sys

sys.path.insert(0, "src")

import pytest

from gatekeeper.cli import main


def test_all_subcommand_helps():  # T414
    for cmd in (["check", "--help"], ["serve", "--help"], ["demo", "--help"],
                ["watch", "--help"], ["review", "--help"], ["stats", "--help"],
                ["export", "--help"], ["pack", "--help"]):
        with pytest.raises(SystemExit) as ei:
            main(cmd)
        assert ei.value.code == 0, cmd


def test_all_get_routes():  # T415
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    class S:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    gatekeeper._router = S()
    serve._BUCKETS.clear()
    client = TestClient(serve.app)
    for path in ("/health", "/version", "/models", "/stats", "/presets", "/metrics"):
        r = client.get(path)
        assert r.status_code == 200, path


def test_demo_import_without_gradio():  # T416
    import sys as _sys
    assert "gradio" not in _sys.modules, "import gradio only inside launch()"
    import gatekeeper.demo_app as _da
    assert callable(_da.launch) and callable(_da.parse_rules)
    import inspect
    assert "port" in inspect.signature(_da.launch).parameters


def test_eval_ece_golden():  # T417: import-safe (no router built) + golden value
    sys.path.insert(0, "eval")
    from eval_gatekeeper import ece
    assert ece([0.9, 0.9, 0.1, 0.1], [True, False, False, False]) == pytest.approx(0.25)


def test_audit_rotation(tmp_path):  # T418
    import os as _os

    import gatekeeper.audit as _au
    p = str(tmp_path / "audit.jsonl")
    old_path, old_max = _au._PATH, _au._MAX_BYTES
    _au._PATH, _au._MAX_BYTES = p, 50
    try:
        _au.log_decision("one", "ok", 0.9, "allow", 1.0)
        _au.log_decision("two", "ok", 0.9, "allow", 1.0)
        assert _os.path.exists(p + ".1")
    finally:
        _au._PATH, _au._MAX_BYTES = old_path, old_max


def test_review_round_trip(tmp_path, monkeypatch):  # T419
    import importlib

    import gatekeeper.review as _rv
    monkeypatch.setenv("BOUNCER_REVIEW", str(tmp_path / "sub" / "q.jsonl"))
    importlib.reload(_rv)
    _rv.add("spam msg", {"action": "flag", "rule": "no-spam", "confidence": 0.8})
    _rv.add("hmm msg", {"action": "escalate", "rule": "ok", "confidence": 0.4})
    assert len(_rv.list_queue()) == 2
    assert [r["action"] for r in _rv.list_queue(action="escalate")] == ["escalate"]
    assert _rv.clear_queue() == 2 and _rv.list_queue() == []


def test_strikes_lifecycle():  # T420
    from gatekeeper import strikes
    strikes.reset()
    assert strikes.add_strike("u1")["strikes"] == 1
    assert strikes.add_strike("u1", 2)["suggest_ban"] is True
    assert strikes.standing("u1") == {"user": "u1", "strikes": 3, "suggest_ban": True}
    strikes._last_decay[0] -= 7200  # 2h idle
    strikes.add_strike("u2")
    assert strikes.standing("u1")["strikes"] == 1  # decayed by 2
    assert strikes.standing("u2")["strikes"] == 1  # fresh clock, not wiped
    strikes.reset()
    assert strikes.standing("u1")["strikes"] == 0


def test_cache_ttl_expiry():  # T421
    import time as _t

    from gatekeeper.cache import TTLCache
    c = TTLCache(ttl=0.05)
    c.set("k", {"a": 1})
    assert c.get("k") == {"a": 1}
    _t.sleep(0.06)
    assert c.get("k") is None


def test_request_coalescing():  # T422
    import threading
    import time as _t

    from gatekeeper import moderate
    from gatekeeper.cache import CACHE
    CACHE.clear()
    calls = []

    class Slow:
        def predict(self, state, questions):
            calls.append(1)
            _t.sleep(0.3)
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    rules = {"plain-chat": "normal talk"}
    outs = []
    ts = [threading.Thread(target=lambda: outs.append(moderate("p23 coal msg", rules,
                                                               router=Slow())))
          for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(calls) == 1 and len(outs) == 2
    assert outs[1].get("coalesced") is True or outs[1].get("cached") is True


def test_inference_timeout_fallback():  # T423
    import time as _t

    from gatekeeper import GateConfig, moderate
    from gatekeeper.cache import CACHE
    CACHE.clear()

    class Slow:
        def predict(self, state, questions):
            _t.sleep(0.5)
            return {"answers": {}}
    r = moderate("p23 timeout msg", {"plain-chat": "normal talk"},
                 config=GateConfig(timeout_s=0.1), router=Slow())
    assert r["action"] == "escalate" and "timed out" in r["reason"]
    assert r["cause"] == "fallback"


def test_amoderate():  # T424
    import asyncio

    from gatekeeper import amoderate
    from gatekeeper.cache import CACHE
    CACHE.clear()

    class S:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    r = asyncio.run(amoderate("p23 async msg", {"plain-chat": "normal talk"}, router=S()))
    assert r["action"] == "allow"
