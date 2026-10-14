"""P13 tests (T221-T230): cache-key correctness, early-path observability,
split thresholds, batch guards, fastpath word boundary. No weights."""
import sys

sys.path.insert(0, "src")

import pytest
from fastapi.testclient import TestClient

import gatekeeper
from gatekeeper import GateConfig, moderate, serve
from gatekeeper.cache import CACHE


class CtxStub:
    """Violates stay-topic iff history mentions 'raid' (context must matter)."""

    def predict(self, state, questions):
        if any("raid" in h for h in state.get("history", [])):
            choice, conf = "stay-topic", 0.9
        else:
            choice, conf = "ok", 0.9
        return {"answers": {
            "rule": {"choice": choice, "confidence": conf,
                     "probabilities": {choice: conf, "other": 0.05}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


class ViolStub:
    """Fixed violation at conf 0.8 (flag at delete>=0.9, delete at delete<=0.8)."""

    def predict(self, state, questions):
        return {"answers": {
            "rule": {"choice": "no-scams", "confidence": 0.8,
                     "probabilities": {"no-scams": 0.8, "ok": 0.1}},
            "harm": {"score": "suspicious", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


@pytest.fixture(autouse=True)
def _iso():
    CACHE.clear()
    serve._BUCKETS.clear()
    yield


def test_cache_key_covers_inputs():  # T221
    kws = {"message": "p13 key msg", "rules": {"a": "rule a text"},
           "allow_threshold": 0.85, "delete_threshold": 0.85}
    base = CACHE.key(**kws)
    assert base.startswith("v2:")
    assert CACHE.key(**{**kws, "allow_threshold": 0.5}) != base
    assert CACHE.key(**{**kws, "delete_threshold": 0.5}) != base
    assert CACHE.key(**{**kws, "lang": "es"}) != base
    assert CACHE.key(**{**kws, "context": ["u: raid at 9"]}) != base
    assert CACHE.key(**{**kws, "quiet_active": True}) != base
    assert CACHE.key(**kws) == base


def test_context_changes_decision():  # T221 e2e: same msg, other context, other verdict
    rules = {"stay-topic": "homework and exam prep only"}
    r1 = moderate("p13 ctx msg one", rules, router=CtxStub())
    assert r1["action"] == "allow"
    r2 = moderate("p13 ctx msg one", rules, context=["u: raid at 9"], router=CtxStub())
    assert r2["action"] == "delete" and not r2.get("cached")
    r3 = moderate("p13 ctx msg one", rules, context=["u: raid at 9"], router=CtxStub())
    assert r3.get("cached") is True and r3["action"] == "delete"


def test_threshold_change_not_stale():  # T221 e2e via split gates
    rules = {"no-scams": "no scams or fraud schemes"}
    plain = moderate("p13 thr msg one", rules, router=ViolStub())
    sev = moderate("p13 thr msg one", rules, router=ViolStub(),
                   config=GateConfig(delete_threshold=0.7))
    assert (plain["action"], sev["action"]) == ("flag", "delete")
    assert not sev.get("cached")


def test_fastpath_observed(tmp_path, monkeypatch):  # T222
    import importlib

    import gatekeeper.audit as _au
    from gatekeeper.stats import get_stats
    p = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BOUNCER_AUDIT", str(p))
    importlib.reload(_au)
    before = get_stats()["actions"]["allow"]
    r = moderate("p13 fp msg good game", {"no-spam": "no links or promo urls here"},
                 router=CtxStub())
    assert r["reason"] == "fastpath: no links"
    assert get_stats()["actions"]["allow"] == before + 1
    assert len(p.read_text().splitlines()) == 1


def test_empty_observed():  # T222
    from gatekeeper.stats import get_stats
    before = get_stats()["actions"]["allow"]
    r = moderate("   ", {"plain-chat": "normal talk"})
    assert r["action"] == "allow" and r["latency_ms"] == 0.0
    assert get_stats()["actions"]["allow"] == before + 1


def test_cache_clear():  # T225
    CACHE.set("k", {"a": 1})
    assert CACHE.get("k") == {"a": 1}
    CACHE.clear()
    assert CACHE.get("k") is None


def test_fastpath_word_boundary():  # T228: "ad" must not match "raid"
    r = moderate("p13 wb msg good game", {"raid-plan": "raid plans and callouts only"},
                 router=CtxStub())
    assert r["reason"] != "fastpath: no links"
    r2 = moderate("p13 wb msg two", {"no-spam": "no ads or links here"}, router=CtxStub())
    assert r2["reason"] == "fastpath: no links"


client = TestClient(serve.app)


def test_server_split_thresholds():  # T223
    gatekeeper._router = ViolStub()
    rules = {"no-scams": "no scams or fraud schemes"}
    r1 = client.post("/predict", json={"message": "p13 srv msg one", "rules": rules,
                                       "delete_threshold": 0.9})
    assert r1.status_code == 200 and r1.json()["action"] == "flag"
    r2 = client.post("/predict", json={"message": "p13 srv msg one", "rules": rules,
                                       "delete_threshold": 0.7})
    assert r2.status_code == 200 and r2.json()["action"] == "delete"


def test_server_threshold_validation():  # T223
    gatekeeper._router = ViolStub()
    r = client.post("/predict", json={"message": "hi", "rules": {"a": "rule a text"},
                                      "threshold": 1.5})
    assert r.status_code == 422


def test_server_batch_cap_and_guards():  # T224
    gatekeeper._router = ViolStub()
    rules = {"no-scams": "no scams or fraud schemes"}
    big = client.post("/predict/batch",
                      json={"messages": ["m"] * 33, "rules": rules})
    assert big.status_code == 413
    ok = client.post("/predict/batch",
                     json={"messages": ["p13 b1", "p13 b2"], "rules": rules})
    assert ok.status_code == 200 and len(ok.json()) == 2


def test_rate_sweep_evicts_idle():  # T227
    import time
    now = time.time()
    serve._BUCKETS.update({f"10.0.0.{i}": [now - 1000] for i in range(600)})
    serve._sweep(now)
    assert len(serve._BUCKETS) == 0


def test_cli_split_flags(capsys):  # T223
    from gatekeeper.cli import main
    gatekeeper._router = ViolStub()
    import json
    with open("p13-rules.json", "w") as f:
        json.dump({"no-scams": "no scams or fraud schemes"}, f)
    try:
        assert main(["check", "p13 cli msg one", "--rules", "p13-rules.json",
                     "--delete-threshold", "0.7", "--json"]) == 2
    finally:
        import os
        os.remove("p13-rules.json")
