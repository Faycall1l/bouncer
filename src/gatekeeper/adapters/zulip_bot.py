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
import urllib.parse
import urllib.request


def api(email: str, key: str, site: str, method: str, path: str, **params):
    """One Zulip v1 call as JSON (HTTP Basic: bot email + api key).

    T851: 429/5xx are retried via the shared `http_json` helper (backoff
    honoring Retry-After); everything else still raises immediately.
    """
    from gatekeeper.adapters.common import http_json

    auth = base64.b64encode(f"{email}:{key}".encode()).decode()
    req = urllib.request.Request(
        f"{site}/api/v1{path}",
        data=urllib.parse.urlencode(params).encode() if params else None,
        method=method,
        headers={"Authorization": f"Basic {auth}"})
    return http_json(req, timeout=60)


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
    from gatekeeper.adapters.common import dry_run
    if creds:
        if msg.get("type") == "stream" and msg.get("display_recipient"):
            if dry_run():  # T697: print the intent, never the act
                out(f"[dry-run] would post {msg['display_recipient']}"
                    f"#{msg.get('subject')}: {reply}")
            else:  # T863: answer where the ask was, keeping its topic
                api_fn(*creds, "POST", "/messages", type="stream",
                       to=msg["display_recipient"],
                       subject=msg.get("subject") or "", content=reply)
        elif dry_run():  # T697: print the intent, never the act
            out(f"[dry-run] would PM {msg.get('sender_id')}: {reply}")
        else:
            api_fn(*creds, "POST", "/messages", type="private",
                   to=msg.get("sender_id"), content=reply)
    else:
        out(reply)
    return {"action": "command", "command": cmd, "reply": reply}


def handle_event(event: dict, rules: dict, *, own_id=None, creds=None,
                 can_delete: bool = False, api_fn=api, out=print,
                 cap=None) -> dict:
    """One queue event in, zero or one reaction out (T695). `cap` (T701)
    limits model calls per sender."""
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
    if cap is not None and not cap.allow(msg.get("sender_id")):  # T701
        out(f"[rate-limited] <{msg.get('sender_id')}> over the per-user cap; "
            "message not moderated")
        return {"action": "ignored", "reason": "rate-limited"}
    from gatekeeper import moderate
    from gatekeeper.adapters.common import as_user_id, detect_lang, dry_run
    res = dict(moderate(text, rules,  # T856+T857: strikes + detected lang
                        user_id=as_user_id("zulip", msg.get("sender_id")),
                        lang=detect_lang(text)))
    res["deleted"] = False
    if (res["action"] == "delete" and can_delete and creds
            and msg.get("id") is not None):
        if dry_run():  # T697: print the intent, never the act
            out(f"[dry-run] would delete message {msg['id']}")
            res["dry_run"] = True
        else:
            api_fn(*creds, "DELETE", f"/messages/{msg['id']}")
            res["deleted"] = True
    if res["action"] in ("delete", "flag", "escalate"):
        from gatekeeper.adapters.common import redact
        out(f"[{res['action']}] <{redact(msg.get('sender_id'))}> "
            f"{redact(text[:120])} "
            f"({res.get('rule')}@{res.get('confidence', 0):.2f})")
    return res


def run():
    from gatekeeper.adapters.common import (
        Health,
        cfg_get,
        install_shutdown,
        load_config,
        load_rules,
        opt_in,
        rate_cap_from_env,
        require_env,
        run_loop,
    )
    cfg = load_config()  # T709: bouncer.toml defaults; env still wins
    email = require_env(
        "ZULIP_EMAIL", cfg_get(cfg, "adapter", "zulip", "email"))
    key = require_env(
        "ZULIP_API_KEY", cfg_get(cfg, "adapter", "zulip", "api_key"))
    site = require_env(
        "ZULIP_SITE", cfg_get(cfg, "adapter", "zulip", "site")).rstrip("/")
    rules = load_rules("zulip", cfg=cfg)  # T698+T709
    can_delete = opt_in("BOUNCER_ZL_DELETE", cfg, "zulip", "delete")
    cap = rate_cap_from_env(cfg)  # T701+T709
    stopping = install_shutdown("zulip")  # T702: SIGTERM -> clean exit
    own_id = api(email, key, site, "GET", "/users/me").get("user_id")
    q = api(email, key, site, "POST", "/register",
            event_types=json.dumps(["message"]),
            all_public_streams="true").get("queue_id")

    def fetch():
        page = api(email, key, site, "GET", "/events", queue_id=q, timeout=25)
        return page.get("events", [])

    def handle(ev):
        handle_event(ev, rules, own_id=own_id, creds=(email, key, site),
                     can_delete=can_delete, cap=cap)  # T701

    run_loop(fetch, handle, name="zulip",  # T696 loop, T699 health line
             health=Health("zulip"), stopping=stopping)  # T702


if __name__ == "__main__":
    run()
