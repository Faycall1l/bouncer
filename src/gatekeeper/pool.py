"""Router pool: kwargs-keyed LRU cache of laya Routers. Thread-safe. No laya import here."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import os
import threading
from collections import OrderedDict


def _pool_max() -> int:
    try:  # T452: bound resident checkpoints (mirrors laya's own max_loaded default)
        return max(1, int(os.environ.get("BOUNCER_POOL_MAX", "2")))
    except (TypeError, ValueError):
        return 2


class RouterPool:
    """T451: one Router per distinct constructor kwargs; LRU-evicts past max_n."""

    def __init__(self, max_n: int | None = None, factory=None):
        self.max_n = max_n or _pool_max()
        self._factory = factory  # T456: injectable for tests (defaults to laya Router)
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.creates = self.evictions = 0

    def _build(self, kw: dict):
        if self._factory is not None:
            return self._factory(**kw)
        from laya import Router as _R
        return _R(**kw)

    @staticmethod
    def _sig(kw: dict) -> tuple:
        return tuple(sorted((k, repr(v)) for k, v in kw.items()))

    def get(self, **kw):
        """Return the pooled Router for these kwargs, building on first use."""
        sig = self._sig(kw)
        with self._lock:
            if sig in self._d:
                self._d.move_to_end(sig)
                self.hits += 1
                return self._d[sig]
            router = self._build(dict(kw))
            self._d[sig] = router
            self.creates += 1
            while len(self._d) > self.max_n:
                self._d.popitem(last=False)
                self.evictions += 1
            return router

    def clear(self) -> None:  # T463: drop residents (tests + low-memory hosts)
        with self._lock:
            self._d.clear()

    def stats(self) -> dict:  # T453
        with self._lock:
            return {"size": len(self._d), "max_n": self.max_n, "hits": self.hits,
                    "creates": self.creates, "evictions": self.evictions}


POOL = RouterPool()


def get_pooled_router(**kw):  # T454: public constructor cache
    mdir = os.environ.get("BOUNCER_MODEL_DIR", "").strip()  # T664: finetuned dir
    if mdir and "model" not in kw:
        kw = {**kw, "model": mdir}  # explicit model= still wins; dir beats the default
    return POOL.get(**kw)


def model_for_lang(lang: str | None) -> str | None:
    """T457: non-latin scripts ride the multilingual checkpoint; else auto-route."""
    if lang in ("ar", "zh", "ru", "fa", "ur", "he"):
        return "multilingual"
    return None
