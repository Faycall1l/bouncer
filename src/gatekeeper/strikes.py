"""Per-user strikes: 3 flags -> suggest ban. Decay halves hourly. No deps."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import os
import time

from .persist import atomic_write  # T432: json/os only, no cycle

_strikes: dict = {}
_last_decay: list = [time.time()]

try:  # T342
    BAN_AT = max(1, int(os.environ.get("BOUNCER_BAN_AT", "3")))
except (TypeError, ValueError):
    BAN_AT = 3

_PATH = os.environ.get("BOUNCER_STRIKES", "bouncer-strikes.json")  # T432


def weight_for_action(action: str) -> int:
    """T341: strike weight per verdict (deletes hit harder than flags)."""
    return {"delete": 2, "flag": 1}.get(action, 0)


def add_strike(user: str, weight: int = 1) -> dict:
    """T181: record flag/delete against a user; returns status incl. ban suggestion."""
    _decay()
    was_empty = not _strikes
    _strikes[user] = _strikes.get(user, 0) + weight
    if was_empty:  # T280: clock went stale while idle-empty; restart it here
        _last_decay[0] = time.time()
    return {"user": user, "strikes": _strikes[user],
            "suggest_ban": _strikes[user] >= BAN_AT}


def _decay() -> None:  # T182
    if not _strikes:  # T280: no table, no clock syscall
        return
    now = time.time()
    hours = (now - _last_decay[0]) / 3600
    if hours >= 1:
        for u in list(_strikes):
            _strikes[u] = max(0, _strikes[u] - int(hours))
            if not _strikes[u]:
                del _strikes[u]
        _last_decay[0] = now


def standing(user: str) -> dict:
    _decay()
    n = _strikes.get(user, 0)  # T248: same shape as add_strike
    return {"user": user, "strikes": n, "suggest_ban": n >= BAN_AT}


def reset() -> None:  # T249: test isolation
    _strikes.clear()
    _last_decay[0] = time.time()


def save(path: str | None = None) -> str:  # T432
    """Persist the strike table atomically; returns the path written."""
    import json as _json
    import time as _t
    target = path or _PATH
    atomic_write(target, _json.dumps({"v": 1, "t": int(_t.time()),
                                     "strikes": dict(_strikes)}))
    return target
