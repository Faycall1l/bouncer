"""Telegram adapter (T692): stdlib-only long-poll bot, flag-only by default.

Usage: TELEGRAM_TOKEN=... python -m gatekeeper.adapters.telegram_bot
`/rules`, `/stats`, `/help` are answered; everything else goes through
`moderate()`. Flag-only default: delete-actions are printed, not executed —
set BOUNCER_TG_DELETE=1 to let them call deleteMessage. A moderation bot that
deletes by default is one rule typo away from silencing a channel.
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import json
import os
import sys
import urllib.request

API_URL = "https://api.telegram.org/bot{token}/{method}"


def api(token: str, method: str, **params):
    """One Bot API call as JSON; raises OSError/URLError on network failure."""
    req = urllib.request.Request(
        API_URL.format(token=token, method=method),
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _command(text: str, rules: dict, chat_id, token, api_fn, out):
    """T692: `/` commands answer in place; no model call, no side effects."""
    cmd = text.split("@", 1)[0].lstrip("/").split()[0].lower()
    if cmd == "rules":
        reply = "active: " + ", ".join(sorted(rules))
    elif cmd == "stats":
        from gatekeeper.stats import get_stats
        s = get_stats()["actions"]
        reply = "decisions: " + ", ".join(f"{a}={n}" for a, n in sorted(s.items()))
    elif cmd == "help":
        reply = "bouncer: /rules, /stats, /help — messages are moderated, " \
                "flag-only by default (BOUNCER_TG_DELETE=1 to delete)"
    else:
        return {"action": "ignored", "reason": "unknown-command"}
    if token:
        api_fn(token, "sendMessage", chat_id=chat_id, text=reply)
    else:
        out(reply)
    return {"action": "command", "command": cmd, "reply": reply}


def handle_update(update: dict, rules: dict, *, token: str | None = None,
                  can_delete: bool = False, api_fn=api, out=print) -> dict:
    """One update in, zero or one reaction out. `api_fn`/`out` are injectable
    so tests never touch the network."""
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id")
    if not text or chat_id is None:
        return {"action": "ignored", "reason": "no-text"}  # stickers/embeds
    if text.startswith("/"):
        return _command(text, rules, chat_id, token, api_fn, out)
    from gatekeeper import moderate
    res = dict(moderate(text, rules))
    res["deleted"] = False
    if res["action"] == "delete" and can_delete and token:
        api_fn(token, "deleteMessage", chat_id=chat_id,
               message_id=msg.get("message_id"))
        res["deleted"] = True
    if res["action"] in ("delete", "flag", "escalate"):
        out(f"[{res['action']}] {text[:120]} ({res.get('rule')}@"
            f"{res.get('confidence', 0):.2f})")
    return res


def run():
    import time

    from gatekeeper import get_preset
    from gatekeeper.adapters.common import require_env
    token = require_env("TELEGRAM_TOKEN")  # T691: named failure, not a crash
    rules = get_preset("gaming")
    can_delete = os.environ.get("BOUNCER_TG_DELETE") == "1"  # T692: opt-in
    offset = 0
    while True:  # long-poll loop; SIGTERM handling is T702's job
        try:
            page = api(token, "getUpdates", offset=offset, timeout=50,
                       allowed_updates=["message"])
        except OSError as e:
            print("telegram error:", e, file=sys.stderr, flush=True)
            time.sleep(5)
            continue
        for upd in page.get("result", []):
            offset = upd["update_id"] + 1  # ack before handling: never re-read
            try:
                handle_update(upd, rules, token=token, can_delete=can_delete)
            except Exception as e:  # noqa: BLE001 — one bad update, one log line
                print("update error:", e, file=sys.stderr, flush=True)


if __name__ == "__main__":
    run()
