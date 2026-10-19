"""TTL LRU for repeat messages (spam waves hit the same text). No deps."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import hashlib
import threading
import time
from collections import OrderedDict


def _short(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:n]


class TTLCache:
    """T023: bounded LRU + TTL; T024 exposes hits/misses; T225 thread-safe + clear()."""

    def __init__(self, maxsize: int = 1024, ttl: float = 60.0):
        self.maxsize, self.ttl = maxsize, ttl
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    @staticmethod
    def key(message: str, rules: dict, allow_threshold: float, delete_threshold: float,
            severity: dict | None = None, lang: str | None = None,
            context: tuple | list = (), history_n: int = 4,
            quiet_active: bool = False, gates: tuple = ()) -> str:
        """T221: every input that can change the decision is in the key.

        (msg, rules, both thresholds, severity, lang, bounded context,
        history window, quiet-hours state, extra gate knobs). `v2:` prefix busts old-format keys.
        """
        hist = list(context)[-history_n:] if context else []  # T272: no copy when empty
        sev = repr(sorted(severity.items())) if severity else "{}"  # T272
        parts = [message, repr(sorted(rules.items())), repr((allow_threshold, delete_threshold)),
                 sev, repr(lang), repr(hist), repr(quiet_active), repr(gates)]
        return "v2:" + ":".join(_short(p, 12 if i else 16) for i, p in enumerate(parts))

    def get(self, k: str):
        now = time.time()
        with self._lock:
            if k in self._d:
                exp, v = self._d.pop(k)
                if exp > now:
                    self._d[k] = (exp, v)
                    self.hits += 1
                    return v
            self.misses += 1
            return None

    def set(self, k: str, v: dict) -> None:
        with self._lock:
            self._d[k] = (time.time() + self.ttl, dict(v))  # T288: copy, no aliasing
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)

    def clear(self) -> None:
        """T225: drop entries (counters kept); tests use this instead of `_d`."""
        with self._lock:
            self._d.clear()

    def stats(self) -> dict:
        """T024."""
        with self._lock:
            tot = self.hits + self.misses
            return {"hits": self.hits, "misses": self.misses, "size": len(self._d),
                    "hit_rate": round(self.hits / tot, 3) if tot else 0.0}  # T245

    def dump(self) -> dict:  # T877: live entries as a snapshot section
        now = time.time()
        with self._lock:
            live = {k: [exp, v] for k, (exp, v) in self._d.items() if exp > now}
        return {"v": 1, "entries": live}

    @staticmethod
    def check(doc) -> None:  # T877: validate a section before anything applies
        from .persist import SnapshotError
        if (not isinstance(doc, dict) or doc.get("v") != 1
                or not isinstance(doc.get("entries"), dict)):
            raise SnapshotError("E_SNAPSHOT: bad cache snapshot")
        for pair in doc["entries"].values():  # entries too — hostile docs die
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:  # here, coded
                raise SnapshotError("E_SNAPSHOT: bad cache entry")
            try:
                float(pair[0])
            except (TypeError, ValueError):
                raise SnapshotError("E_SNAPSHOT: bad cache entry") from None

    def restore(self, doc: dict) -> int:  # T877: merge a dump() back
        self.check(doc)
        now = time.time()
        n = 0
        with self._lock:
            for k, (exp, v) in doc["entries"].items():  # check() passed: safe
                if float(exp) > now and isinstance(v, dict):
                    self._d[k] = (float(exp), v)
                    n += 1
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)
        return n

    def save(self, path: str) -> str:  # T436+T877: file wrapper over dump()
        import json as _json

        from .persist import atomic_write
        atomic_write(path, _json.dumps(self.dump()))
        return path

    def load(self, path: str) -> int:  # T436+T877: file wrapper over restore()
        from .persist import read_json
        return self.restore(read_json(path))


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(__import__("os").environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(__import__("os").environ.get(name, default)))
    except (TypeError, ValueError):
        return default


CACHE = TTLCache(maxsize=_env_int("BOUNCER_CACHE_SIZE", 1024),  # T271
                 ttl=_env_float("BOUNCER_CACHE_TTL", 60.0))
