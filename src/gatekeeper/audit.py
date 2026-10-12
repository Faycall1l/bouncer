"""JSONL audit trail: hash of message (never raw text by default), decision, latency."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import hashlib
import json
import os
import time

_PATH = os.environ.get("BOUNCER_AUDIT", "bouncer-audit.jsonl")
_MAX_BYTES = 5 * 1024 * 1024


def _maybe_rotate() -> None:
    """T030: size-based rotation keeps one backup generation."""
    if os.path.exists(_PATH) and os.path.getsize(_PATH) > _MAX_BYTES:
        os.replace(_PATH, _PATH + ".1")


def log_decision(msg: str, rule: str, conf: float, action: str, latency_ms: float) -> None:
    """T029: one JSON line per decision; rotates at 5MB (T030 trims below)."""
    _maybe_rotate()
    h = hashlib.sha256(msg.encode()).hexdigest()[:16]
    with open(_PATH, "a") as f:
        f.write(json.dumps({"t": int(time.time()), "msg": h, "rule": rule,
                            "conf": round(conf, 3), "action": action,
                            "ms": round(latency_ms, 1)}) + "\n")
