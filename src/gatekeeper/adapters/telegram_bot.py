"""Telegram adapter (T692): stdlib-only long-poll bot, flag-only by default.

Usage: TELEGRAM_TOKEN=... python -m gatekeeper.adapters.telegram_bot
`/rules`, `/stats`, `/help` are answered; everything else goes through
`moderate()`. Flag-only default: delete-actions are printed, not executed —
set BOUNCER_TG_DELETE=1 to let them call deleteMessage. A moderation bot that
deletes by default is one rule typo away from silencing a channel.
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.

API_URL = "https://api.telegram.org/bot{token}/{method}"


def api(token: str, method: str, **params):
    """One Bot API call as JSON; raises OSError/URLError on network failure.

    T851: 429/5xx are retried via the shared `http_json` helper (backoff
    honoring Retry-After); T951: the request builder itself now lives in
    `common.api` — this wrapper keeps only the URL and the body.
    """
    from gatekeeper.adapters.common import api as _api

    return _api(API_URL.format(token=token, method=method), params=params,
                headers={"Content-Type": "application/json"}, timeout=60)


def _command(text: str, rules: dict, chat_id, token, api_fn, out,
             reply_to=None, user=None):
    """T692: `/` commands answer in place; no model call, no side effects.
    T860: the answer threads under its trigger (reply_to_message_id), so
    in a busy group the notice says which command it answers."""
    from gatekeeper.adapters.common import command_reply, dry_run, parse_command
    cmd = parse_command(text.split("@", 1)[0])  # T952: shared first-word dance
    reply = command_reply(  # T952: the shared table, not a local ladder
        cmd, rules, user,
        help_text="bouncer: /rules, /stats, /appeal, /help — messages are "
                  "moderated, flag-only by default (BOUNCER_TG_DELETE=1 to delete)")
    if reply is None:
        return {"action": "ignored", "reason": "unknown-command"}
    if token and not dry_run():
        api_fn(token, "sendMessage", chat_id=chat_id, text=reply,
               **({"reply_to_message_id": reply_to} if reply_to else {}))  # T860
    else:
        out(("[dry-run] would send: " if token else "") + reply)
    return {"action": "command", "command": cmd, "reply": reply}


def handle_update(update: dict, rules: dict, *, token: str | None = None,
                  can_delete: bool = False, api_fn=api, out=print,
                  cap=None) -> dict:
    """One update in, zero or one reaction out. `api_fn`/`out` are injectable
    so tests never touch the network. `cap` (T701) limits model calls per chat."""
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id")
    if not text or chat_id is None:
        return {"action": "ignored", "reason": "no-text"}  # stickers/embeds
    if text.startswith("/"):
        from gatekeeper.adapters.common import as_user_id
        return _command(text, rules, chat_id, token, api_fn, out,
                        reply_to=msg.get("message_id"),  # T860: in-thread
                        user=as_user_id("telegram",  # T864: appeal target
                                        (msg.get("from") or {}).get("id")))
    if cap is not None and not cap.allow(chat_id):  # T701: flood != model fuel
        out(f"[rate-limited] chat {chat_id} over the per-user cap; "
            "message not moderated")
        return {"action": "ignored", "reason": "rate-limited"}
    from gatekeeper.adapters.common import moderate_action

    def _delete(dry, res):  # T953: the platform-shaped part of the skeleton
        if dry:
            out(f"[dry-run] would deleteMessage chat={chat_id} "
                f"msg={msg.get('message_id')}")
            return
        api_fn(token, "deleteMessage", chat_id=chat_id,
               message_id=msg.get("message_id"))

    return moderate_action(
        text, rules, adapter="telegram",
        uid=(msg.get("from") or {}).get("id"),
        enabled=bool(can_delete and token), effect=_delete, out=out,
        sender=False)  # the group line already shows who sent it


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
        "TELEGRAM_TOKEN", cfg_get(cfg, "adapter", "telegram", "token"))
    rules = load_rules("telegram", cfg=cfg)  # T698+T709
    can_delete = opt_in("BOUNCER_TG_DELETE", cfg, "telegram", "delete")
    cap = rate_cap_from_env(cfg)  # T701+T709: per-chat model-call budget
    stopping = install_shutdown("telegram")  # T702: SIGTERM -> clean exit
    offset = 0

    def fetch():  # ack the whole page up front: at-most-once, never re-read
        nonlocal offset
        page = api(token, "getUpdates", offset=offset, timeout=50,
                   allowed_updates=["message"])
        result = page.get("result", [])
        if result:
            offset = result[-1]["update_id"] + 1
        return result

    def handle(upd):
        handle_update(upd, rules, token=token, can_delete=can_delete,
                      cap=cap)  # T701

    run_loop(fetch, handle, name="telegram",  # T696 loop, T699 health line
             health=Health("telegram"), stopping=stopping,  # T702
             message_of=lambda u: (u.get("message") or {}).get("text", ""))  # T866


if __name__ == "__main__":
    run()
