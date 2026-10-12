"""In-memory decision counters. No deps, no weights."""
from __future__ import annotations

import threading

_lock = threading.Lock()
_counts = {"allow": 0, "flag": 0, "delete": 0, "escalate": 0}
_by_rule: dict = {}


def record(action: str, rule: str) -> None:
    """T027: count every decision + per-rule hits."""
    with _lock:
        _counts[action] = _counts.get(action, 0) + 1
        _by_rule[rule] = _by_rule.get(rule, 0) + 1


def get_stats() -> dict:
    """T028: snapshot for /stats and CLI."""
    with _lock:
        return {"actions": dict(_counts), "rules": dict(_by_rule),
                "total": sum(_counts.values())}


def reset_stats() -> None:
    with _lock:
        _counts.clear()
        _counts.update({"allow": 0, "flag": 0, "delete": 0, "escalate": 0})
        _by_rule.clear()
