"""P25 tests (T451-T470): router pools. No weights."""
import sys

sys.path.insert(0, "src")


def test_pool_max_env(monkeypatch):  # T452
    from gatekeeper import pool as _pool
    monkeypatch.setenv("BOUNCER_POOL_MAX", "3")
    assert _pool._pool_max() == 3
    monkeypatch.setenv("BOUNCER_POOL_MAX", "junk")
    assert _pool._pool_max() == 2
