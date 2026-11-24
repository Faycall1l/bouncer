"""P62 tests (T1245-T1248): typed, counted, traced fallback paths."""
import time

import pytest

from eval.harness.decision import DecisionConfig, DecisionPolicy, moderate_decision
from gatekeeper import CACHE, GateConfig, moderate
from gatekeeper.stats import breaker_counts, get_stats, reset_stats, source_counts


class OkRouter:
    def predict(self, state, questions):
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95,
                     "probabilities": {"ok": 0.95, "no-spam": 0.05}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0},
        }}


def _policy():
    return DecisionPolicy(name="p62", outcomes=("allow", "delete", "flag", "escalate",
                                               "abstain"),
                          sources=("model", "cache", "fastpath", "empty", "breaker",
                                   "fallback", "coalesced"))


def test_fastpath_is_typed_counted_and_traced():  # T1245
    reset_stats()
    rules = {"no-spam": "no link"}
    r = moderate("p62 fastpath plain message", rules, router=OkRouter())
    assert r["source"] == "fastpath"
    assert r["cause"] == "fastpath: no links"
    assert get_stats()["source_counts"]["fastpath"] == 1
    assert get_stats()["causes"]["fastpath: no links"] == 1
    cfg = DecisionConfig(name="p62", policy=_policy(), gate=GateConfig())
    d = moderate_decision(cfg, "p62 fastpath traced", rules, router=OkRouter(),
                          instance_id="fp")
    assert d.source == "fastpath" and d.cause == "fastpath: no links"


def test_cache_is_typed_counted_and_traced(monkeypatch):  # T1246
    CACHE.clear()
    k = CACHE.key("p62 cache msg", {"r": "t"}, 0.85, 0.9)
    val = {"action": "allow", "rule": "ok", "confidence": 1.0}
    CACHE.set(k, val)
    before = CACHE.stats()["hits"]
    assert CACHE.get(k) is not None
    assert CACHE.stats()["hits"] == before + 1
    # Force expiry through the typed counter by rewinding the entry timestamp.
    CACHE._d[k] = (time.time() - 1, CACHE._d[k][1])
    before_expired = CACHE.stats()["ttl_expired"]
    assert CACHE.get(k) is None
    assert CACHE.stats()["ttl_expired"] == before_expired + 1


def test_breaker_counters_are_typed():  # T1247
    reset_stats()
    from gatekeeper.stats import record_breaker

    record_breaker("open")
    record_breaker("half_open", 2)
    record_breaker("closed")
    counts = breaker_counts()
    assert counts == {"closed": 1, "half_open": 2, "open": 1}
    with pytest.raises(ValueError, match="unknown breaker outcome"):
        record_breaker("maybe")
    with pytest.raises(ValueError, match="n must be"):
        record_breaker("open", 0)


def test_engine_sources_are_counted_and_closed():  # T1245
    reset_stats()
    moderate("p62 model source msg", {"no-spam": "no links"}, router=OkRouter())
    assert source_counts().get("model", 0) >= 1
    allowed = set(source_counts())
    assert allowed.issubset({"model", "cache", "fastpath", "empty", "breaker",
                             "fallback", "coalesced"})
    with pytest.raises(ValueError, match="unknown decision source"):
        __import__("gatekeeper.stats", fromlist=["record_source"]).record_source("mystery")
