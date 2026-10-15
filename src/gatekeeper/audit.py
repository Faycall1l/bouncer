"""JSONL audit trail: hash of message (never raw text by default), decision, latency."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import hashlib
import json
import os
import threading
import time

try:  # T194: orjson fastpath when installed
    import orjson as _oj

    def _dump(d: dict) -> str:
        return _oj.dumps(d).decode()
except ImportError:
    def _dump(d: dict) -> str:
        return json.dumps(d)

_PATH = os.environ.get("BOUNCER_AUDIT", "bouncer-audit.jsonl")
_MAX_BYTES = 5 * 1024 * 1024
_LOCK = threading.Lock()  # T229: threaded server must not interleave lines


def _maybe_rotate() -> None:
    """T030: size-based rotation keeps one backup generation."""
    if os.path.exists(_PATH) and os.path.getsize(_PATH) > _MAX_BYTES:
        os.replace(_PATH, _PATH + ".1")


def log_decision(msg: str, rule: str, conf: float, action: str, latency_ms: float,
                 lang: str | None = None, context_n: int = 0,
                 thresholds: tuple | None = None) -> None:
    """T029: one JSON line per decision; rotates at 5MB (T030 trims below)."""
    h = hashlib.sha256(msg.encode()).hexdigest()[:16]
    with _LOCK:  # T229
        _maybe_rotate()
        with open(_PATH, "a") as f:
            f.write(_dump({"t": int(time.time()), "msg": h, "rule": rule,
                           "conf": round(conf, 3), "action": action,
                           "ms": round(latency_ms, 1), "lang": lang or "",  # T237
                           "ctx": context_n,
                           "thr": list(thresholds) if thresholds else []}) + "\n")  # T238
