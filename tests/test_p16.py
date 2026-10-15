"""P16 tests (T271-T290): performance. No weights."""
import sys

sys.path.insert(0, "src")


def test_forced_ok_skips_dists():  # T276
    from gatekeeper.explain import explain
    res = {"action": "delete", "rule": "ok", "confidence": 0.95, "forced": "jailbreak 0.95",
           "rule_dist": None}
    s = explain(res, {})
    assert s.startswith("delete: override") and "runner-up" not in s


def test_from_dict():  # T289
    import pytest

    from gatekeeper.config import ConfigError, GateConfig
    assert GateConfig.from_dict({"allow_threshold": 0.9}).allow_threshold == 0.9
    with pytest.raises(ConfigError, match="unknown keys"):
        GateConfig.from_dict({"nope": 1})
    with pytest.raises(ConfigError, match="E_CONFIG"):
        GateConfig.from_dict({"timeout_s": -1})


def test_fastpath_cached_repeat():  # T287
    from gatekeeper import moderate
    from gatekeeper.cache import CACHE
    CACHE.clear()

    class S:
        called = 0

        def predict(self, state, questions):
            type(self).called += 1
            raise AssertionError("fastpath must not reach the router")
    rules = {"no-spam": "no links or promo urls here"}
    r1 = moderate("p16 fp cache msg", rules, router=S())
    assert r1["cached"] is False
    r2 = moderate("p16 fp cache msg", rules, router=S())
    assert r2.get("cached") is True and S.called == 0


def test_gzip_middleware_present():  # T284
    from starlette.middleware.gzip import GZipMiddleware

    from gatekeeper import serve
    assert any(m.cls is GZipMiddleware for m in serve.app.user_middleware)


def test_empty_batch_422():  # T279
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    class S:
        def predict(self, state, questions):
            raise AssertionError("unreachable")
    gatekeeper._router = S()
    serve._BUCKETS.clear()
    r = TestClient(serve.app).post("/predict/batch",
                                   json={"messages": [], "rules": {"a": "rule a text"}})
    assert r.status_code == 422
