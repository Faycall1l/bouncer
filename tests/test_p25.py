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
