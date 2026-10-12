"""Per-user strikes: 3 flags -> suggest ban. Decay halves hourly. No deps."""
from __future__ import annotations

import time

_strikes: dict = {}
_last_decay: list = [time.time()]
BAN_AT = 3  # T181


def add_strike(user: str, weight: int = 1) -> dict:
    """T181: record flag/delete against a user; returns status incl. ban suggestion."""
    _decay()
    _strikes[user] = _strikes.get(user, 0) + weight
    return {"user": user, "strikes": _strikes[user],
            "suggest_ban": _strikes[user] >= BAN_AT}


def _decay() -> None:  # T182
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
    return {"user": user, "strikes": _strikes.get(user, 0)}
