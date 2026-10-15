"""Review queue: escalations/flags awaiting humans. JSONL, gitignored."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import json
import os
from collections import deque

_PATH = os.environ.get("BOUNCER_REVIEW", "review-queue.jsonl")


def add(message: str, res: dict) -> None:  # T170
    parent = os.path.dirname(os.path.abspath(_PATH))  # T281
    os.makedirs(parent, exist_ok=True)
    with open(_PATH, "a") as f:
        f.write(json.dumps({"message": message[:500], "action": res["action"],
                            "rule": res["rule"], "conf": round(res["confidence"], 3),
                            "ms": res.get("latency_ms", 0.0)}) + "\n")  # T244


def list_queue(limit: int = 20, action: str | None = None) -> list:  # T170+T243
    if not os.path.exists(_PATH):
        return []
    with open(_PATH) as f:  # T229: tail via deque, no full-file list in memory
        rows = [json.loads(line) for line in deque(f, maxlen=1000)]
    if action:  # T243
        rows = [r for r in rows if r.get("action") == action]
    return rows[-max(limit, 1):]


def clear_queue() -> int:  # T318: truncate; returns rows dropped
    if not os.path.exists(_PATH):
        return 0
    with open(_PATH) as f:
        n = sum(1 for _ in f)
    with open(_PATH, "w"):
        pass
    return n
