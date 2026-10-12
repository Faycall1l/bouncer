"""Review queue: escalations/flags awaiting humans. JSONL, gitignored."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import json
import os

_PATH = os.environ.get("BOUNCER_REVIEW", "review-queue.jsonl")


def add(message: str, res: dict) -> None:  # T170
    with open(_PATH, "a") as f:
        f.write(json.dumps({"message": message[:500], "action": res["action"],
                            "rule": res["rule"], "conf": res["confidence"]}) + "\n")


def list_queue(limit: int = 20) -> list:  # T170
    if not os.path.exists(_PATH):
        return []
    return [json.loads(l) for l in open(_PATH)][-limit:]
