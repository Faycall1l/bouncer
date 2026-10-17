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
# T758: BOUNCER_AUDIT_FSYNC=N batches disk syncs — lines still flush() to the
# OS per write (process-crash safe); every Nth write pays the fsync syscall
# (power-loss safe for the last N). 0/unset = legacy per-call open+close.
_FSYNC_N = max(0, int(os.environ.get("BOUNCER_AUDIT_FSYNC", "0") or 0))
_F = None  # open handle while batching; None = legacy mode / nothing open
_SINCE = 0  # lines written since the last fsync


def _maybe_rotate() -> bool:
    """T030: size-based rotation keeps two backup generations. True = rotated."""
    if os.path.exists(_PATH) and os.path.getsize(_PATH) > _MAX_BYTES:
        if os.path.exists(_PATH + ".1"):  # T282: shift, don't clobber
            os.replace(_PATH + ".1", _PATH + ".2")
        os.replace(_PATH, _PATH + ".1")
        return True
    return False


def _close_handle() -> None:  # T758: rotation or shutdown drops the batch
    global _F, _SINCE
    if _F is not None:
        _F.close()
        _F = None
        _SINCE = 0


def flush() -> None:  # T758: force the batched tail to disk (shutdown hooks)
    global _SINCE
    with _LOCK:
        if _F is not None:
            _F.flush()
            os.fsync(_F.fileno())
            _SINCE = 0


def log_decision(msg: str, rule: str, conf: float, action: str, latency_ms: float,
                 lang: str | None = None, context_n: int = 0,
                 thresholds: tuple | None = None) -> None:
    """T029: one JSON line per decision; rotates at 5MB (T030 trims below)."""
    h = hashlib.sha256(msg.encode()).hexdigest()[:16]
    line = _dump({"t": int(time.time()), "msg": h, "rule": rule,
                  "conf": round(conf, 3), "action": action,
                  "ms": round(latency_ms, 1), "lang": lang or "",  # T237
                  "ctx": context_n,
                  "thr": list(thresholds) if thresholds else []}) + "\n"  # T238
    global _F, _SINCE
    with _LOCK:  # T229
        if _maybe_rotate():  # T758: the rotated-away handle must be dropped
            _close_handle()
        parent = os.path.dirname(os.path.abspath(_PATH))  # T444 (mirrors T281)
        os.makedirs(parent, exist_ok=True)
        if _FSYNC_N <= 0:  # legacy path: exactly the T029 behavior
            with open(_PATH, "a") as f:
                f.write(line)
            return
        if _F is None:
            _F = open(_PATH, "a")  # noqa: SIM115 — T758: batching IS the open handle
        _F.write(line)
        _F.flush()  # OS has it (process-crash safe) — disk waits for N
        _SINCE += 1
        if _SINCE >= _FSYNC_N:
            os.fsync(_F.fileno())
            _SINCE = 0


if _FSYNC_N > 0:  # T758: process exit drains the batched tail to disk
    import atexit

    atexit.register(flush)


def tail(n: int = 20, path: str | None = None) -> list:  # T440
    """Last n audit rows as dicts (deque tail, no full-file list)."""
    from collections import deque
    target = path or _PATH
    if not os.path.exists(target):
        return []
    with open(target) as f:
        return [json.loads(line) for line in deque(f, maxlen=max(n, 1))]
