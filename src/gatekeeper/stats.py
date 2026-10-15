"""In-memory decision counters. No deps, no weights."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import threading

_lock = threading.Lock()
_counts = {"allow": 0, "flag": 0, "delete": 0, "escalate": 0}
_by_rule: dict = {}
_joint: dict = {}  # T231: (action, rule) -> n


def record(action: str, rule: str) -> None:
    """T027: count every decision + per-rule hits."""
    with _lock:
        _counts[action] = _counts.get(action, 0) + 1
        _by_rule[rule] = _by_rule.get(rule, 0) + 1
        _joint[(action, rule)] = _joint.get((action, rule), 0) + 1


def get_stats() -> dict:
    """T028: snapshot for /stats and CLI."""
    with _lock:
        nested: dict = {}
        for (a, r), n in sorted(_joint.items()):
            nested.setdefault(r, {})[a] = n
        return {"actions": dict(_counts), "rules": dict(_by_rule),
                "actions_by_rule": nested,  # T231
                "total": sum(_counts.values())}


def reset_stats() -> None:
    with _lock:
        _counts.clear()
        _counts.update({"allow": 0, "flag": 0, "delete": 0, "escalate": 0})
        _by_rule.clear()
        _joint.clear()  # T231
