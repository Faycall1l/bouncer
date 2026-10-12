"""TTL LRU for repeat messages (spam waves hit the same text). No deps."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import hashlib
import time
from collections import OrderedDict


class TTLCache:
    """T023: bounded LRU + TTL; T024 exposes hits/misses."""

    def __init__(self, maxsize: int = 1024, ttl: float = 60.0):
        self.maxsize, self.ttl = maxsize, ttl
        self._d: OrderedDict = OrderedDict()
        self.hits = self.misses = 0

    @staticmethod
    def key(message: str, rules: dict, threshold: float, severity: dict | None = None) -> str:
        h = hashlib.sha256(message.encode()).hexdigest()[:16]
        rh = hashlib.sha256(repr(sorted(rules.items())).encode()).hexdigest()[:8]
        sh = hashlib.sha256(repr(sorted((severity or {}).items())).encode()).hexdigest()[:8]
        return f"{h}:{rh}:{threshold}:{sh}"

    def get(self, k: str):
        now = time.time()
        if k in self._d:
            exp, v = self._d.pop(k)
            if exp > now:
                self._d[k] = (exp, v)
                self.hits += 1
                return v
        self.misses += 1
        return None

    def set(self, k: str, v: dict) -> None:
        self._d[k] = (time.time() + self.ttl, v)
        while len(self._d) > self.maxsize:
            self._d.popitem(last=False)

    def stats(self) -> dict:
        """T024."""
        return {"hits": self.hits, "misses": self.misses, "size": len(self._d)}


CACHE = TTLCache()
