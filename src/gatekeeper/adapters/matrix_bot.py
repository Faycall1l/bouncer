"""Matrix adapter (T693): stdlib-only room-timeline poller.

Usage: MATRIX_TOKEN=... MATRIX_HOMESERVER=https://... python -m gatekeeper.adapters.matrix_bot
Syncs joined-room timelines (`m.room.message` / `m.text`+`m.notice`) through
`moderate()`; `!bouncer rules` / `!bouncer stats` answer in the room (discord
prefix parity). Flag-only default — `BOUNCER_MX_REDACT=1` opts into
`m.room.redaction`; a bot that redacts by default is one typo from silence.
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import json
import sys
import urllib.request


def api(token: str, homeserver: str, method: str, path: str, params=None):
    """One Matrix client-API call as JSON; raises OSError/URLError on failure.

    T851: 429/5xx are retried via the shared `http_json` helper (backoff
    honoring Retry-After); everything else still raises immediately.
    """
    from gatekeeper.adapters.common import http_json

    req = urllib.request.Request(
        f"{homeserver}/_matrix/client/v0{path}",
        data=json.dumps(params).encode() if params else None,
        method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    return http_json(req, timeout=70)


def _command(body, rules, event, token, homeserver, api_fn, out):
    from gatekeeper.adapters.common import dry_run
    cmd = body.split()[1].lower() if len(body.split()) > 1 else ""
    if cmd == "rules":
        reply = "active: " + ", ".join(sorted(rules))
    elif cmd == "stats":
        from gatekeeper.stats import get_stats
        s = get_stats()["actions"]
        reply = "decisions: " + ", ".join(f"{a}={n}" for a, n in sorted(s.items()))
    else:
        return {"action": "ignored", "reason": "unknown-command"}
    if token and homeserver and not dry_run():
        import time
        api_fn(token, homeserver, "PUT",
               f"/rooms/{event['room_id']}/send/m.room.message/"
               f"{int(time.time() * 1000)}", {"msgtype": "m.notice", "body": reply})
    else:
        out(("[dry-run] would send notice: " if token else "") + reply)
    return {"action": "command", "command": cmd, "reply": reply}


def handle_event(event: dict, rules: dict, *, token=None, homeserver=None,
                 can_redact: bool = False, api_fn=api, out=print,
                 cap=None) -> dict:
    """One timeline event in, zero or one reaction out (T693). `api_fn`/`out`
    are injectable so tests never touch a homeserver. `cap` (T701) limits
    model calls per sender."""
    if event.get("type") != "m.room.message":
        return {"action": "ignored", "reason": "not-message"}
    content = event.get("content") or {}
    body = (content.get("body") or "").strip()
    if content.get("msgtype") not in ("m.text", "m.notice") or not body:
        return {"action": "ignored", "reason": "no-text"}  # images, empties
    if body.startswith("!bouncer"):
        return _command(body, rules, event, token, homeserver, api_fn, out)
    if cap is not None and not cap.allow(event.get("sender")):  # T701
        from gatekeeper.adapters.common import redact
        out(f"[rate-limited] <{redact(event.get('sender'))}> over the "
            "per-user cap; message not moderated")
        return {"action": "ignored", "reason": "rate-limited"}
    from gatekeeper import moderate
    from gatekeeper.adapters.common import as_user_id, detect_lang, dry_run
    res = dict(moderate(body, rules,  # T856+T857: strikes + detected lang
                        user_id=as_user_id("matrix", event.get("sender")),
                        lang=detect_lang(body)))
    res["redacted"] = False
    if res["action"] == "delete" and can_redact and token and homeserver:
        if dry_run():  # T697: print the intent, never the act
            out(f"[dry-run] would redact {event['event_id']} "
                f"in {event['room_id']}")
            res["dry_run"] = True
        else:
            api_fn(token, homeserver, "PUT",
                   f"/rooms/{event['room_id']}/redact/{event['event_id']}/bouncer1",
                   {"redacts": event["event_id"],
                    "reason": f"bouncer:{res.get('rule')}"})
            res["redacted"] = True
    if res["action"] in ("delete", "flag", "escalate"):
        from gatekeeper.adapters.common import redact
        out(f"[{res['action']}] <{redact(event.get('sender'))}> "
            f"{redact(body[:120])} "
            f"({res.get('rule')}@{res.get('confidence', 0):.2f})")
    return res


def _flatten_page(page: dict) -> list:
    """T696: sync page -> flat event list, room_id stamped from the envelope."""
    events = []
    joined = (page.get("rooms") or {}).get("join") or {}
    for room_id, room in joined.items():
        for ev in (room.get("timeline") or {}).get("events", []):
            ev = dict(ev)
            ev.setdefault("room_id", room_id)
            events.append(ev)
    return events


def dispatch_page(page: dict, rules: dict, **kw) -> list:
    """T693: one sync page -> per-event results; a bad event costs one log
    line, never the loop."""
    results = []
    for ev in _flatten_page(page):
        try:
            results.append(handle_event(ev, rules, **kw))
        except Exception as e:  # noqa: BLE001
            from gatekeeper.adapters.common import redact
            print("event error:", redact(e), file=sys.stderr, flush=True)
            results.append({"action": "error", "error": str(e)})
    return results


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
    token = require_env(
        "MATRIX_TOKEN", cfg_get(cfg, "adapter", "matrix", "token"))
    homeserver = require_env(
        "MATRIX_HOMESERVER",
        cfg_get(cfg, "adapter", "matrix", "homeserver")).rstrip("/")
    rules = load_rules("matrix", cfg=cfg)  # T698+T709
    can_redact = opt_in("BOUNCER_MX_REDACT", cfg, "matrix", "redact")
    cap = rate_cap_from_env(cfg)  # T701+T709
    stopping = install_shutdown("matrix")  # T702: SIGTERM -> clean exit
    since = None

    def fetch():
        nonlocal since
        path = "/sync?timeout=50000&set_presence=offline"
        page = api(token, homeserver, "GET",
                   path + (f"&since={since}" if since else ""))
        since = page.get("next_batch") or since
        return _flatten_page(page)

    def handle(ev):
        handle_event(ev, rules, token=token, homeserver=homeserver,
                     can_redact=can_redact, cap=cap)  # T701

    run_loop(fetch, handle, name="matrix",  # T696 loop, T699 health line
             health=Health("matrix"), stopping=stopping)  # T702


if __name__ == "__main__":
    run()
