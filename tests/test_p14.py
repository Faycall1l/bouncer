"""P14 tests (T231-T250): observability + stats. No weights."""
import sys

sys.path.insert(0, "src")

from gatekeeper.stats import get_stats, record, reset_stats


def test_reset_clears_all():  # T239
    reset_stats()
    record("delete", "no-spam", 12.5, cause="violation")
    record("allow", "ok", 0.0, cheap=True, cause="fastpath")
    s = get_stats()
    assert s["actions_by_rule"] == {"no-spam": {"delete": 1}, "ok": {"allow": 1}}
    assert s["latency"]["n"] == 2 and s["cheap_paths"] == 1
    assert s["causes"] == {"violation": 1, "fastpath": 1}
    reset_stats()
    s = get_stats()
    assert s["total"] == 0 and s["latency"]["n"] == 0
    assert s["cheap_paths"] == 0 and s["causes"] == {} and s["actions_by_rule"] == {}
    reset_stats()  # leave clean state for later tests


def test_latency_percentiles():  # T232
    reset_stats()
    for ms in (10.0, 20.0, 30.0, 40.0):
        record("allow", "ok", ms)
    s = get_stats()["latency"]
    assert (s["n"], s["p50_ms"], s["p95_ms"]) == (4, 30.0, 40.0)
    reset_stats()


def test_cache_hit_rate():  # T245
    from gatekeeper.cache import TTLCache
    c = TTLCache()
    assert c.stats()["hit_rate"] == 0.0
    c.set("k", {"a": 1})
    assert c.get("k") == {"a": 1} and c.get("nope") is None
    assert c.stats()["hit_rate"] == 0.5


def test_metrics_lines():  # T235+T236
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
    body = client.get("/metrics").text
    assert "bouncer_cache_hits" in body and "bouncer_latency_p50_ms" in body
    assert f'version="{gatekeeper.__version__}"' in body and "bouncer_uptime_seconds" in body
    st = client.get("/stats").json()  # T240
    assert st["version"] == gatekeeper.__version__ and st["uptime_s"] >= 0


def test_audit_fields(tmp_path, monkeypatch):  # T237+T238
    import importlib
    import json as _json

    import gatekeeper.audit as _au
    p = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BOUNCER_AUDIT", str(p))
    importlib.reload(_au)
    _au.log_decision("hello", "ok", 0.9, "allow", 3.0, lang="es", context_n=2,
                     thresholds=(0.9, 0.7))
    row = _json.loads(p.read_text().splitlines()[0])
    assert (row["lang"], row["ctx"], row["thr"]) == ("es", 2, [0.9, 0.7])


def test_review_filter_and_fields(tmp_path, monkeypatch):  # T243+T244
    import importlib

    import gatekeeper.review as _rv
    p = tmp_path / "review.jsonl"
    monkeypatch.setenv("BOUNCER_REVIEW", str(p))
    importlib.reload(_rv)
    _rv.add("m1", {"action": "flag", "rule": "r", "confidence": 0.81, "latency_ms": 4.2})
    _rv.add("m2", {"action": "escalate", "rule": "r", "confidence": 0.5, "latency_ms": 1.0})
    assert [r["message"] for r in _rv.list_queue(action="flag")] == ["m1"]
    assert len(_rv.list_queue()) == 2


def test_fresh_result_marks_uncached():  # T247
    from gatekeeper import moderate
    from gatekeeper.cache import CACHE
    CACHE.clear()

    class S:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    r = moderate("p14 uncached marker msg", {"plain-chat": "normal talk"}, router=S())
    assert r["cached"] is False


def test_strikes_standing_and_reset():  # T248+T249
    from gatekeeper import strikes
    strikes.reset()
    assert strikes.standing("u") == {"user": "u", "strikes": 0, "suggest_ban": False}
    strikes.add_strike("u")
    assert strikes.standing("u")["strikes"] == 1
    strikes.reset()
    assert strikes.standing("u")["strikes"] == 0


def test_explain_extras():  # T241+T242
    from gatekeeper.explain import appeal_text, explain
    res = {"action": "delete", "rule": "no-spam", "confidence": 0.9, "harm": "harmful",
           "rule_dist": {"no-spam": 0.9}}
    assert "[harm=harmful]" in explain(res, {"no-spam": "no ads"})
    assert "no ads" in appeal_text(res, {"no-spam": "no ads"})
    assert "APPEAL" in appeal_text(res)
