"""Review queue: escalations/flags awaiting humans. JSONL, gitignored."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import json
import os
import time
from collections import deque

_PATH = os.environ.get("BOUNCER_REVIEW", "review-queue.jsonl")


def add(message: str, res: dict) -> None:  # T170
    parent = os.path.dirname(os.path.abspath(_PATH))  # T281
    os.makedirs(parent, exist_ok=True)
    # T784: the queue is the ONE artifact that holds raw message text (by
    # design — a human can't adjudicate a hash), so it gets the same 0600
    # treatment as snapshots; fchmod also drops a stale file's old mode.
    fd = os.open(_PATH, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps({"t": int(time.time()),  # T441: for prune()
                            "message": message[:500], "action": res["action"],
                            "rule": res["rule"], "conf": round(res["confidence"], 3),
                            "cause": res.get("cause", ""),  # T448
                            "ms": res.get("latency_ms", 0.0)}) + "\n")  # T244


def list_queue(limit: int = 20, action: str | None = None,
               since: float = 0, rule: str | None = None) -> list:  # T537+T543
    if not os.path.exists(_PATH):
        return []
    with open(_PATH) as f:  # T229: tail via deque, no full-file list in memory
        rows = [json.loads(line) for line in deque(f, maxlen=1000)]
    if action:  # T243
        rows = [r for r in rows if r.get("action") == action]
    if since:  # T537: rows at/after this epoch second
        rows = [r for r in rows if r.get("t", 0) >= since]
    if rule:  # T543: rows for this rule id only
        rows = [r for r in rows if r.get("rule") == rule]
    return rows[-max(limit, 1):]


def clear_queue() -> int:  # T318: truncate; returns rows dropped
    if not os.path.exists(_PATH):
        return 0
    with open(_PATH) as f:
        n = sum(1 for _ in f)
    with open(_PATH, "w"):
        pass
    return n


def prune(max_age_s: float) -> int:  # T442: drop rows older than this; returns dropped
    if not os.path.exists(_PATH):
        return 0
    cutoff = time.time() - max_age_s
    with open(_PATH) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    kept = [r for r in rows if r.get("t", cutoff) >= cutoff]
    with open(_PATH, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in kept)
    return len(rows) - len(kept)
