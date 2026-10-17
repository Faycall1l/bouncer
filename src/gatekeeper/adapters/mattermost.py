"""Mattermost adapter (T694): websocket event stream + slash commands.

Usage: MATTERMOST_SERVER=... MATTERMOST_TOKEN=... python -m gatekeeper.adapters.mattermost
The only adapter with a dependency: `pip install -e .[mattermost]` (websockets
extra) — stdlib can't speak RFC6455, and a hand-rolled frame parser is a
security patch waiting to happen. Posts stream in via `/api/v4/websocket`
(`posted` events); `handle_slash()` answers slash-command webhooks
(`MATTERMOST_SLASH_TOKEN` compared constant-time). Flag-only default —
`BOUNCER_MM_DELETE=1` opts into `deletePost`.
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import hmac
import json
import os
import sys
import urllib.parse
import urllib.request


def api(token: str, server: str, method: str, path: str, **params):
    """One Mattermost REST call as JSON."""
    req = urllib.request.Request(
        f"{server}/api/v4{path}",
        data=json.dumps(params).encode() if params else None,
        method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def handle_post(post: dict, rules: dict, *, token=None, server=None,
                can_delete: bool = False, api_fn=api, out=print,
                cap=None) -> dict:
    """One `posted` event in, zero or one reaction out (T694). `cap` (T701)
    limits model calls per user."""
    if post.get("type"):  # system messages (joins, leaves, edits) carry no text
        return {"action": "ignored", "reason": "system-post"}
    text = (post.get("message") or "").strip()
    if not text:
        return {"action": "ignored", "reason": "no-text"}
    if cap is not None and not cap.allow(post.get("user_id")):  # T701
        from gatekeeper.adapters.common import redact
        out(f"[rate-limited] <{redact(post.get('user_id'))}> over the "
            "per-user cap; message not moderated")
        return {"action": "ignored", "reason": "rate-limited"}
    from gatekeeper import moderate
    from gatekeeper.adapters.common import dry_run
    res = dict(moderate(text, rules))
    res["deleted"] = False
    if res["action"] == "delete" and can_delete and token and server:
        if dry_run():  # T697: print the intent, never the act
            out(f"[dry-run] would deletePost {post.get('id')}")
            res["dry_run"] = True
        else:
            api_fn(token, server, "DELETE", f"/posts/{post['id']}")
            res["deleted"] = True
    if res["action"] in ("delete", "flag", "escalate"):
        from gatekeeper.adapters.common import redact
        out(f"[{res['action']}] <{redact(post.get('user_id'))}> "
            f"{redact(text[:120])} "
            f"({res.get('rule')}@{res.get('confidence', 0):.2f})")
    return res


def handle_slash(form: dict, rules: dict, *, slash_token=None, token=None,
                 server=None, api_fn=api, out=print) -> dict:
    """One slash-command webhook in, one reply out (T694). The shared secret
    is compared constant-time; a mismatch is rejected, never moderated."""
    if slash_token and not hmac.compare_digest(
            str(form.get("token") or ""), slash_token):
        return {"action": "ignored", "reason": "bad-token"}
    parts = (form.get("text") or "").split()
    # Mattermost sends only the args after the trigger ("rules"); tolerate a
    # full "/bouncer rules" pasted into text too
    if parts and parts[0].lstrip("/").lower() == "bouncer":
        parts = parts[1:]
    cmd = parts[0].lstrip("/").lower() if parts else ""
    if cmd == "rules":
        reply = "active: " + ", ".join(sorted(rules))
    elif cmd == "stats":
        from gatekeeper.stats import get_stats
        s = get_stats()["actions"]
        reply = "decisions: " + ", ".join(f"{a}={n}" for a, n in sorted(s.items()))
    else:
        reply = "usage: /bouncer rules | /bouncer stats"
        cmd = cmd or "help"
    from gatekeeper.adapters.common import dry_run
    if token and server and form.get("channel_id") and not dry_run():
        api_fn(token, server, "POST", "/posts",
               channel_id=form["channel_id"], message=reply)
    else:
        out(("[dry-run] would post: " if token else "") + reply)
    return {"action": "command", "command": cmd, "reply": reply}


def run():
    import asyncio

    from gatekeeper.adapters.common import (
        AdapterError,
        Health,
        install_shutdown,
        load_rules,
        rate_cap_from_env,
        require_env,
    )
    try:
        import websockets  # optional dep: pip install -e .[mattermost]
    except ImportError as e:
        raise AdapterError(
            "E_ADAPTER: mattermost needs the websockets extra — "
            "pip install -e .[mattermost]") from e
    server = require_env("MATTERMOST_SERVER").rstrip("/")  # T691: named failure
    token = require_env("MATTERMOST_TOKEN")
    rules = load_rules("mattermost")  # T698: BOUNCER_RULES[_MATTERMOST] or preset
    can_delete = os.environ.get("BOUNCER_MM_DELETE") == "1"  # T694: opt-in
    cap = rate_cap_from_env()  # T701: per-user model-call budget
    health = Health("mattermost")  # T699: same counters as run_loop's
    stopping = install_shutdown("mattermost")  # T702: SIGTERM -> clean exit

    async def _loop():
        async with websockets.connect(
                f"{server}/api/v4/websocket",
                additional_headers={"Authorization": f"Bearer {token}"}) as ws:
            await ws.send(json.dumps({"action": "authentication", "seq": 1,
                                      "data": {"token": token}}))
            async for raw in ws:
                if stopping():  # T702: message boundary exit
                    print("mattermost: shutdown requested — exiting cleanly",
                          file=sys.stderr, flush=True)
                    break
                msg = json.loads(raw)
                if msg.get("event") != "posted":
                    continue
                post = (msg.get("data") or {}).get("post")
                post = json.loads(post) if isinstance(post, str) else post
                if not post:
                    continue
                try:
                    res = handle_post(post, rules, token=token, server=server,
                                      can_delete=can_delete,
                                      cap=cap) or {}  # T701
                    if res.get("action") not in ("ignored", "command"):
                        health.decision()
                except Exception as e:  # noqa: BLE001 — one bad post, one line
                    from gatekeeper.adapters.common import redact
                    print("post error:", redact(e), file=sys.stderr, flush=True)
                    health.error(redact(e))
                health.maybe_log()

    asyncio.run(_loop())  # SIGTERM handling is T702's job


if __name__ == "__main__":
    run()
