"""Mattermost adapter (T694): websocket event stream + slash commands.

Usage: MATTERMOST_SERVER=... MATTERMOST_TOKEN=... python -m gatekeeper.adapters.mattermost
The only adapter with a dependency: `pip install -e .[mattermost]` (websockets
extra) — stdlib can't speak RFC6455, and a hand-rolled frame parser is a
security patch waiting to happen. Posts stream in via `/api/v4/websocket`
(`posted` events); the session body is `_session`, wrapped by the shared
`areconnect` loop — a dropped socket redials with capped, jittered backoff
(T852) instead of ending the process. `handle_slash()` answers
slash-command webhooks (`MATTERMOST_SLASH_TOKEN` compared constant-time).
Flag-only default — `BOUNCER_MM_DELETE=1` opts into `deletePost`.
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import hmac
import json
import sys
import urllib.parse
import urllib.request


def api(token: str, server: str, method: str, path: str, **params):
    """One Mattermost REST call as JSON.

    T851: 429/5xx are retried via the shared `http_json` helper (backoff
    honoring Retry-After); everything else still raises immediately.
    """
    from gatekeeper.adapters.common import http_json

    req = urllib.request.Request(
        f"{server}/api/v4{path}",
        data=json.dumps(params).encode() if params else None,
        method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    return http_json(req, timeout=30)


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
    from gatekeeper.adapters.common import adapter_lang, as_user_id, dry_run
    res = dict(moderate(text, rules,  # T856+T857: strikes + detected lang
                        user_id=as_user_id("mattermost",
                                           post.get("user_id")),
                        lang=adapter_lang("mattermost", text),  # T897: env pin, else detect
                        adapter="mattermost"))  # T867: per-adapter counters
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
    elif cmd == "appeal":  # T864: row-linked appeal answer
        from gatekeeper.adapters.common import as_user_id
        from gatekeeper.review import appeal_reply
        reply = appeal_reply(as_user_id("mattermost", form.get("user_id")),
                             rules)
    else:
        reply = "usage: /bouncer rules | /bouncer stats | /bouncer appeal"
        cmd = cmd or "help"
    from gatekeeper.adapters.common import dry_run
    if token and server and form.get("channel_id") and not dry_run():
        api_fn(token, server, "POST", "/posts",
               channel_id=form["channel_id"], message=reply,
               **({"root_id": form["post_id"]}  # T862: thread under trigger
                  if form.get("post_id") else {}))
    else:
        out(("[dry-run] would post: " if token else "") + reply)
    return {"action": "command", "command": cmd, "reply": reply}


async def _session(ws, *, token, rules, server, can_delete, cap, health,
                   stopping):
    """T694+T852: one websocket session — authenticate, then drain events.

    Ends when the socket dies (areconnect redials it) or `stopping` flips
    (T702: message-boundary exit; areconnect prints the clean-exit line).
    Returns via `async for` completing — the disconnect itself is
    areconnect's to observe, log (T700) and back off from.
    """
    await ws.send(json.dumps({"action": "authentication", "seq": 1,
                              "data": {"token": token}}))
    async for raw in ws:
        if stopping():  # T702: message boundary exit
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


def run():
    import asyncio

    from gatekeeper.adapters.common import (
        AdapterError,
        Health,
        areconnect,
        cfg_get,
        install_shutdown,
        load_config,
        load_rules,
        opt_in,
        rate_cap_from_env,
        require_env,
    )
    try:
        import websockets  # optional dep: pip install -e .[mattermost]
    except ImportError as e:
        raise AdapterError(
            "E_ADAPTER: mattermost needs the websockets extra — "
            "pip install -e .[mattermost]") from e
    cfg = load_config()  # T709: bouncer.toml defaults; env still wins
    server = require_env(
        "MATTERMOST_SERVER",
        cfg_get(cfg, "adapter", "mattermost", "server")).rstrip("/")
    token = require_env(
        "MATTERMOST_TOKEN", cfg_get(cfg, "adapter", "mattermost", "token"))
    rules = load_rules("mattermost", cfg=cfg)  # T698+T709
    can_delete = opt_in("BOUNCER_MM_DELETE", cfg, "mattermost", "delete")
    cap = rate_cap_from_env(cfg)  # T701+T709
    health = Health("mattermost")  # T699: same counters as run_loop's
    stopping = install_shutdown("mattermost")  # T702: SIGTERM -> clean exit

    def _dial():
        """T852: one connection attempt — areconnect owns the retry ladder."""
        return websockets.connect(
            f"{server}/api/v4/websocket",
            additional_headers={"Authorization": f"Bearer {token}"})

    async def _consume(ws):
        await _session(ws, token=token, rules=rules, server=server,
                       can_delete=can_delete, cap=cap, health=health,
                       stopping=stopping)

    # T852: a dropped socket used to end the process — areconnect redials
    # with capped, jittered backoff until SIGTERM (T702) says otherwise
    asyncio.run(areconnect(_dial, _consume, name="mattermost",
                           health=health, stopping=stopping))


if __name__ == "__main__":
    run()
