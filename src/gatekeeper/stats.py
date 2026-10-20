"""In-memory decision counters. No deps, no weights."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import os
import threading

from .persist import atomic_write, read_json  # T435: json/os only, no cycle

_PATH = os.environ.get("BOUNCER_STATS", "bouncer-stats.json")  # T435

_lock = threading.Lock()
_counts = {"allow": 0, "flag": 0, "delete": 0, "escalate": 0}
_by_rule: dict = {}
_joint: dict = {}  # T231: (action, rule) -> n
_lat: list = []  # T232: ring buffer of recent latency_ms (cap 200)
_cheap = 0  # T233: decisions served without a model call (empty/fastpath)
_causes: dict = {}  # T234: cause -> n (margin, needs-human, quiet, low-conf, ...)
_adapt: dict = {}  # T867: (adapter, action) -> n — which platform is loud

# T942: rule ids arrive from client request bodies (`rules: {"id": "text"}`),
# so the label set is client-controlled. Past this many distinct ids the
# counter folds new ones into one `_other` series — /stats stays honest
# (it counts decisions, not label sets) while no scrape can grow unbounded.
MAX_RULE_LABELS = 200
_OTHER = "_other"


def _pct(xs: list, q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(q * len(s)))], 1)


def record(action: str, rule: str, latency_ms: float | None = None,
           cheap: bool = False, cause: str | None = None,
           adapter: str | None = None) -> None:
    """T027: count every decision + per-rule hits; T867: optionally tag
    which platform adapter asked (None = HTTP/CLI/batch: not an adapter)."""
    global _cheap
    with _lock:
        _counts[action] = _counts.get(action, 0) + 1
        if rule not in _by_rule and len(_by_rule) >= MAX_RULE_LABELS:  # T942
            rule = _OTHER  # a fresh client id past the cap counts, never labels
        _by_rule[rule] = _by_rule.get(rule, 0) + 1
        _joint[(action, rule)] = _joint.get((action, rule), 0) + 1
        if adapter:  # T867
            _adapt[(adapter, action)] = _adapt.get((adapter, action), 0) + 1
        if cause:  # T234
            _causes[cause] = _causes.get(cause, 0) + 1
        if cheap:  # T233
            _cheap += 1
        if latency_ms is not None:  # T232
            _lat.append(float(latency_ms))
            del _lat[:-200]


def get_stats() -> dict:
    """T028: snapshot for /stats and CLI."""
    with _lock:
        nested: dict = {}
        for (a, r), n in sorted(_joint.items()):
            nested.setdefault(r, {})[a] = n
        by_adp: dict = {}
        for (a, act), n in sorted(_adapt.items()):  # T867
            by_adp.setdefault(a, {})[act] = n
        return {"actions": dict(_counts), "rules": dict(sorted(_by_rule.items())),  # T283
                "actions_by_rule": nested,  # T231
                "adapters": by_adp,  # T867
                "latency": {"n": len(_lat), "p50_ms": _pct(_lat, 0.5),  # T232
                            "p95_ms": _pct(_lat, 0.95)},
                "cheap_paths": _cheap,  # T233
                "causes": dict(sorted(_causes.items())),  # T234
                "total": sum(_counts.values())}


def reset_stats() -> None:
    global _cheap
    with _lock:
        _counts.clear()
        _counts.update({"allow": 0, "flag": 0, "delete": 0, "escalate": 0})
        _by_rule.clear()
        _joint.clear()  # T231
        _adapt.clear()  # T867
        del _lat[:]  # T232
        _cheap = 0  # T233
        _causes.clear()  # T234


def snapshot() -> dict:  # T434
    """Point-in-time copy for save(); restore() takes it back."""
    import time as _t
    with _lock:
        return {"v": 2,  # T876: v2 declares the adapters section (T867)
                "t": int(_t.time()), "counts": dict(_counts),
                "by_rule": dict(_by_rule),
                "joint": [list(k) + [v] for k, v in _joint.items()],
                "adapters": [list(k) + [v] for k, v in _adapt.items()],  # T867
                "causes": dict(_causes), "cheap": _cheap}


def restore(snap: dict) -> None:  # T434
    """Replace counters from a snapshot(); shape validated (see T447)."""
    global _cheap
    from .persist import SnapshotError
    if not isinstance(snap, dict) or snap.get("v") not in (1, 2):
        raise SnapshotError("E_SNAPSHOT: bad stats snapshot version")
    # T876: v1 files predate the adapters section (T867) — .get() below
    # defaults it, so migrating is accepting the older version, nothing else
    known = ("allow", "flag", "delete", "escalate")
    extra = sorted(set(snap.get("counts", {})) - set(known))  # T447
    if extra:
        raise SnapshotError(f"E_SNAPSHOT: unknown actions {extra}")
    with _lock:
        _counts.clear()
        _counts.update({k: int(snap.get("counts", {}).get(k, 0)) for k in known})
        _by_rule.clear()
        for r, n in snap.get("by_rule", {}).items():  # T942: snapshots are
            # operator files, but a stale 50k-rule snapshot must not outlive
            # the cap either — fold past it exactly like the network path
            if r != _OTHER and r not in _by_rule and len(_by_rule) >= MAX_RULE_LABELS:
                r = _OTHER
            _by_rule[r] = _by_rule.get(r, 0) + int(n)
        _joint.clear()
        for a, r, n in snap.get("joint", []):
            _joint[(a, r)] = int(n)
        _adapt.clear()  # T867: absent in pre-0.5.0 snapshots -> empty
        for a, act, n in snap.get("adapters", []):
            _adapt[(a, act)] = int(n)
        _causes.clear()
        _causes.update(snap.get("causes", {}))
        _cheap = int(snap.get("cheap", 0))


def save(path: str | None = None) -> str:  # T435
    """Persist counters atomically; returns the path written."""
    import json as _json
    target = path or _PATH
    atomic_write(target, _json.dumps(snapshot()))
    return target


def load(path: str | None = None) -> None:  # T435
    """Restore counters from a file written by save()."""
    restore(read_json(path or _PATH))
