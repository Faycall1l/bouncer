"""P28 tests (T511-T530): reliability. No weights."""
import sys

sys.path.insert(0, "src")

import gatekeeper
from gatekeeper import GateConfig, moderate
from gatekeeper.cache import CACHE


class Boom:
    calls = 0

    def predict(self, state, questions):
        type(self).calls += 1
        raise RuntimeError("down")


def _reset_breaker():
    gatekeeper._BREAKER.update({"fails": 0, "open_until": 0.0, "half_open": False})


def test_breaker_cause():  # T512+T513
    CACHE.clear()
    _reset_breaker()
    Boom.calls = 0
    cfg = GateConfig(breaker_n=2, breaker_cool_s=60.0)
    rules = {"plain-chat": "normal talk"}
    r1 = moderate("p28 tripped one", rules, config=cfg, router=Boom())
    assert r1["cause"] == "fallback" and Boom.calls == 2  # one retry per call
    r2 = moderate("p28 tripped two", rules, config=cfg, router=Boom())
    assert r2["cause"] == "fallback"
    r3 = moderate("p28 tripped three", rules, config=cfg, router=Boom())
    assert r3["cause"] == "breaker-open" and r3["action"] == "escalate"
    assert Boom.calls == 4  # third call never touched the model
    _reset_breaker()


def test_breaker_closes_on_success():  # T514
    CACHE.clear()
    _reset_breaker()

    class Flaky:
        calls = 0

        def predict(self, state, questions):
            type(self).calls += 1
            if type(self).calls <= 2:  # first moderate: both attempts fail
                raise RuntimeError("once")
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    cfg = GateConfig(breaker_n=5, breaker_cool_s=60.0)
    rules = {"plain-chat": "normal talk"}
    moderate("p28 flaky one", rules, config=cfg, router=Flaky())
    assert gatekeeper._BREAKER["fails"] == 1
    moderate("p28 flaky two", rules, config=cfg, router=Flaky())
    assert gatekeeper._BREAKER["fails"] == 0
    _reset_breaker()


def test_breaker_off(monkeypatch):  # T523
    CACHE.clear()
    _reset_breaker()
    monkeypatch.setenv("BOUNCER_BREAKER", "off")
    gatekeeper._BREAKER.update({"fails": 99, "open_until": 9999999999.0,
                                "half_open": False})
    try:
        assert gatekeeper._breaker_tripped() is False
    finally:
        _reset_breaker()


def test_request_timeout_default(monkeypatch):  # T524
    from gatekeeper.serve import _request_timeout
    assert _request_timeout(None) == 10.0
    assert _request_timeout(2.5) == 2.5
    monkeypatch.setenv("BOUNCER_TIMEOUT", "3")
    assert _request_timeout(None) == 3.0
    monkeypatch.setenv("BOUNCER_TIMEOUT", "junk")
    assert _request_timeout(None) == 10.0


def test_breaker_trips_exactly_at_n():  # T511+T526
    import pytest

    from gatekeeper.config import ConfigError, GateConfig
    with pytest.raises(ConfigError, match="breaker_n"):
        GateConfig(breaker_n=0)
    with pytest.raises(ConfigError, match="breaker_cool"):
        GateConfig(breaker_cool_s=0)
    CACHE.clear()
    _reset_breaker()
    Boom.calls = 0
    cfg = GateConfig(breaker_n=3, breaker_cool_s=60.0)
    rules = {"plain-chat": "normal talk"}
    moderate("p28 exact one", rules, config=cfg, router=Boom())
    moderate("p28 exact two", rules, config=cfg, router=Boom())
    assert gatekeeper._breaker_tripped() is False  # 2 < 3
    moderate("p28 exact three", rules, config=cfg, router=Boom())
    assert gatekeeper._breaker_tripped() is True
    _reset_breaker()
