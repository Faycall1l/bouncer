"""Review queue: escalations/flags awaiting humans. JSONL, gitignored."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import json
import os
import time
import uuid
from collections import deque

_PATH = os.environ.get("BOUNCER_REVIEW", "review-queue.jsonl")


def add(message: str, res: dict, user: str | None = None) -> None:  # T170+T864
    parent = os.path.dirname(os.path.abspath(_PATH))  # T281
    os.makedirs(parent, exist_ok=True)
    # T784: the queue is the ONE artifact that holds raw message text (by
    # design — a human can't adjudicate a hash), so it gets the same 0600
    # treatment as snapshots; fchmod also drops a stale file's old mode.
    fd = os.open(_PATH, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps({"t": int(time.time()),  # T441: for prune()
                            "id": uuid.uuid4().hex[:8],  # T864: appeal linkage
                            "user": user,  # T864: T858 namespaced key, or None
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


def latest_for(user: str | None) -> dict | None:  # T864
    """Newest queue row for this namespaced user (T858 keys); rows without
    a user (CLI escalations) are nobody's appeal target."""
    if not user:
        return None
    for row in reversed(list_queue(limit=1000)):
        if row.get("user") == user:
            return row
    return None


def appeal_reply(user: str | None, rules: dict) -> str:  # T864
    """The APPEAL command's answer: the user's newest queue row rendered in
    the T183 appeal template, with the row id so the reply links back to
    the exact queue entry an operator will adjudicate (T865)."""
    row = latest_for(user)
    if row is None:
        return ("nothing queued for this user — APPEAL answers your newest "
                "flagged message; this user has none.")
    from gatekeeper.explain import appeal_text
    res = {"action": row["action"], "rule": row["rule"],
           "confidence": row.get("conf", 0.0)}
    return f"{appeal_text(res, rules)} (queue row {row['id']})"


def adjudicate(row_id: str, verdict: str) -> dict | None:  # T865
    """Operator approve/reject of one queue row, rewritten in place (the
    prune pattern): the row gains `verdict` + `vt`. Reject runs the strike
    amnesty path — the row's user loses exactly the weight that verdict
    accrued (T341), recorded back on the row as `after`. Unknown id ->
    None; a verdict that is not approve/reject -> ValueError (E_VERDICT)."""
    if verdict not in ("approve", "reject"):
        raise ValueError(f"E_VERDICT: {verdict!r} is not approve/reject")
    if not os.path.exists(_PATH):
        return None
    with open(_PATH) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    hit = None
    for r in rows:
        if r.get("id") == row_id:
            r["verdict"] = verdict
            r["vt"] = int(time.time())
            hit = r
            break
    if hit is None:
        return None
    with open(_PATH, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    if verdict == "reject" and hit.get("user"):  # T865: strike amnesty path
        from gatekeeper import strikes
        from gatekeeper.strikes import weight_for_action
        hit["after"] = strikes.amnesty(
            hit["user"], weight_for_action(hit.get("action", "")))
    return hit


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
