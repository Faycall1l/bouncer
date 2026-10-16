"""P25 tests (T451-T470): router pools. No weights."""
import sys

sys.path.insert(0, "src")


def test_pool_max_env(monkeypatch):  # T452
    from gatekeeper import pool as _pool
    monkeypatch.setenv("BOUNCER_POOL_MAX", "3")
    assert _pool._pool_max() == 3
    monkeypatch.setenv("BOUNCER_POOL_MAX", "junk")
    assert _pool._pool_max() == 2


def test_pool_stats():  # T453
    from gatekeeper.pool import RouterPool
    made = []
    p = RouterPool(max_n=4, factory=lambda **kw: made.append(kw) or object())
    p.get(device="cpu")
    p.get(device="cpu")
    s = p.stats()
    assert (s["hits"], s["creates"], s["size"]) == (1, 1, 1)


def test_pooled_identity():  # T454
    import gatekeeper.pool as _pool
    from gatekeeper.pool import get_pooled_router
    _pool.POOL.clear()
    made = []
    _pool.POOL._factory = lambda **kw: made.append(kw) or object()
    try:
        assert get_pooled_router(device="cpu") is get_pooled_router(device="cpu")
        assert len(made) == 1
    finally:
        _pool.POOL._factory = None
        _pool.POOL.clear()


def test_pool_eviction_lru():  # T456
    from gatekeeper.pool import RouterPool
    p = RouterPool(max_n=2, factory=lambda **kw: dict(kw))
    p.get(device="a")
    p.get(device="b")
    p.get(device="a")  # a is now MRU
    p.get(device="c")  # evicts b
    s = p.stats()
    assert s == {"size": 2, "max_n": 2, "hits": 1, "creates": 3, "evictions": 1}
    assert p.get(device="a")["device"] == "a"  # still resident


def test_model_for_lang():  # T457
    from gatekeeper.pool import model_for_lang
    assert model_for_lang("ar") == "multilingual"
    assert model_for_lang("en") is None
    assert model_for_lang(None) is None
    assert model_for_lang("fr") is None  # latin scripts auto-route


def test_pool_clear():  # T463
    from gatekeeper.pool import RouterPool
    p = RouterPool(max_n=2, factory=lambda **kw: object())
    p.get(device="a")
    assert p.stats()["size"] == 1
    p.clear()
    assert p.stats()["size"] == 0


def test_pool_threadsafe():  # T465
    import threading
    import time as _t

    from gatekeeper.pool import RouterPool
    built = []
    lock = threading.Lock()

    def _factory(**kw):
        _t.sleep(0.05)
        with lock:
            built.append(kw)
        return dict(kw)
    p = RouterPool(max_n=4, factory=_factory)
    outs = []
    ts = [threading.Thread(target=lambda: outs.append(p.get(device="x"))) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(set(map(id, outs))) == 1 and p.stats()["creates"] == 1


def test_model_reaches_predict():  # T466
    from gatekeeper import moderate
    from gatekeeper.cache import CACHE
    CACHE.clear()
    seen = {}

    class S:
        def predict(self, state, questions, model=None):
            seen["model"] = model
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    moderate("p25 model msg", {"plain-chat": "normal talk"}, model="multilingual", router=S())
    assert seen["model"] == "multilingual"
