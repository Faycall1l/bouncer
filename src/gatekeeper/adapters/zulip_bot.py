"""Zulip adapter (T695): stdlib-only event-queue poller.

Usage: ZULIP_EMAIL=... ZULIP_API_KEY=... ZULIP_SITE=... python -m gatekeeper.adapters.zulip
Registers an event queue and long-polls `/events`. Stream messages go through
`moderate()`; the bot's own messages are skipped (a bot must never eat its own
replies). PMs and `bouncer ...` mentions are commands only
(`bouncer rules` / `bouncer stats`). Flag-only default —
`BOUNCER_ZL_DELETE=1` opts into `DELETE /messages/{id}`.
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import base64
import json
import os
import sys
import urllib.parse
import urllib.request


def api(email: str, key: str, site: str, method: str, path: str, **params):
    """One Zulip v1 call as JSON (HTTP Basic: bot email + api key)."""
    auth = base64.b64encode(f"{email}:{key}".encode()).decode()
    req = urllib.request.Request(
        f"{site}/api/v1{path}",
        data=urllib.parse.urlencode(params).encode() if params else None,
        method=method,
        headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _command(text, rules, msg, creds, api_fn, out):
    parts = text.lstrip("/").split()
    if parts and parts[0].lower() == "bouncer":  # mention/trigger prefix
        parts = parts[1:]
    cmd = parts[0].lower() if parts else ""
    if cmd == "rules":
        reply = "active: " + ", ".join(sorted(rules))
    elif cmd == "stats":
        from gatekeeper.stats import get_stats
        s = get_stats()["actions"]
        reply = "decisions: " + ", ".join(f"{a}={n}" for a, n in sorted(s.items()))
    else:
        reply = "usage: bouncer rules | bouncer stats"
        cmd = cmd or "help"
    if creds:
        api_fn(*creds, "POST", "/messages", type="private",
               to=msg.get("sender_id"), content=reply)
    else:
        out(reply)
    return {"action": "command", "command": cmd, "reply": reply}


def handle_event(event: dict, rules: dict, *, own_id=None, creds=None,
                 can_delete: bool = False, api_fn=api, out=print) -> dict:
    """One queue event in, zero or one reaction out (T695)."""
    if event.get("type") != "message":
        return {"action": "ignored", "reason": "not-message"}
    msg = event.get("message") or {}
    if own_id is not None and msg.get("sender_id") == own_id:
        return {"action": "ignored", "reason": "own-message"}  # never self-eat
    text = (msg.get("content") or "").strip()
    if not text:
        return {"action": "ignored", "reason": "no-text"}
    if msg.get("type") == "private":
        # PMs are commands-only for a moderation bot (T695)
        if not text.lstrip("/").lower().startswith("bouncer"):
            return {"action": "ignored", "reason": "private-needs-command"}
        return _command(text, rules, msg, creds, api_fn, out)
    if text.lstrip("/").lower().startswith("bouncer"):  # mention parity
        return _command(text, rules, msg, creds, api_fn, out)
    from gatekeeper import moderate
    res = dict(moderate(text, rules))
    res["deleted"] = False
    if (res["action"] == "delete" and can_delete and creds
            and msg.get("id") is not None):
        api_fn(*creds, "DELETE", f"/messages/{msg['id']}")
        res["deleted"] = True
    if res["action"] in ("delete", "flag", "escalate"):
        out(f"[{res['action']}] <{msg.get('sender_id')}> {text[:120]} "
            f"({res.get('rule')}@{res.get('confidence', 0):.2f})")
    return res


def run():
    import time

    from gatekeeper import get_preset
    from gatekeeper.adapters.common import require_env
    email = require_env("ZULIP_EMAIL")  # T691: named failure, not a crash
    key = require_env("ZULIP_API_KEY")
    site = require_env("ZULIP_SITE").rstrip("/")
    rules = get_preset("gaming")
    can_delete = os.environ.get("BOUNCER_ZL_DELETE") == "1"  # T695: opt-in
    own_id = api(email, key, site, "GET", "/users/me").get("user_id")
    q = api(email, key, site, "POST", "/register",
            event_types=json.dumps(["message"]),
            all_public_streams="true").get("queue_id")
    while True:  # long-poll; SIGTERM handling is T702's job
        try:
            page = api(email, key, site, "GET", "/events", queue_id=q,
                       timeout=25)
        except OSError as e:
            print("zulip error:", e, file=sys.stderr, flush=True)
            time.sleep(5)
            continue
        for ev in page.get("events", []):
            try:
                handle_event(ev, rules, own_id=own_id, creds=(email, key, site),
                             can_delete=can_delete)
            except Exception as e:  # noqa: BLE001 — one bad event, one line
                print("event error:", e, file=sys.stderr, flush=True)


if __name__ == "__main__":
    run()
