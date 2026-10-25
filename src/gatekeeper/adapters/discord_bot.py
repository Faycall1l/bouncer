"""Discord adapter stub (T073-T075). `pip install -e .[discord]` then run this module."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import sys


def parse_command(text: str) -> str | None:  # T705: one parser, both surfaces
    """`!bouncer <cmd>` (prefix message) and `/bouncer <cmd>` (slash-form)
    parse identically; the bare prefix lists the commands. Returns the
    subcommand name, or None when the text isn't a command at all."""
    t = (text or "").strip()
    low = t.lower()
    for prefix in ("!bouncer", "/bouncer"):
        if low == prefix:
            return "help"
        if low.startswith(prefix + " "):
            rest = t[len(prefix):].strip()
            return rest.split()[0].lower() if rest else "help"
    return None


def command_reply(cmd: str, rules: dict, stats=None,  # T705 → T952 shared
                  user=None) -> str | None:
    """The prefix handler and the slash handler both call this, so the two
    surfaces cannot drift apart — and since T952 the ladder itself lives
    in `common.command_reply`, so no *adapter* can drift from the others
    either. This wrapper keeps discord's signature and its help line (the
    `!bouncer`/`/bouncer` prefixes are this surface's own)."""
    from gatekeeper.adapters.common import command_reply as _table
    return _table(cmd, rules, user, stats=stats, help_text=_HELP_TEXT)


_HELP_TEXT = ("commands: !bouncer rules | !bouncer stats | !bouncer appeal "
              "| !bouncer help (slash: /bouncer command:)")


def moderate_message(text: str, user_id, rules: dict, *, health,
                     cap, msg_key=None) -> dict:  # T854
    """T854: one message in, one decision out — with the two guards every
    other adapter already had.

    RateCap (T701) runs before the model call: one flood can't monopolize
    it; an over-cap message logs `[rate-limited]` and returns ignored.
    Health (T699) runs after: real decisions counted, `maybe_log()` on
    every message, and a model failure costs one redacted line plus a
    recorded error — never the bot (the per-event guard run_loop and
    areconnect give their traffic).

    `msg_key` (T1034) is the message id: a repeat judgment of the same
    message accrues no second strike — the decision carries the live
    standing instead — and callers without a key keep accrue-per-call.
    """
    from gatekeeper import moderate
    from gatekeeper.adapters.common import (
        adapter_lang,
        as_user_id,
        remod_mark,
        remod_see,
    )

    user = as_user_id("discord", user_id)
    mkey = f"discord:{msg_key}" if msg_key else None  # T1034
    struck = remod_see(mkey, "struck")  # T1034: same message judged before
    if cap is not None and not cap.allow(user_id):  # T701+T854
        from gatekeeper.adapters.common import redact
        print(f"[rate-limited] <{redact(user_id)}> over the "
              "per-user cap; message not moderated")
        res = {"action": "ignored", "reason": "rate-limited"}
    else:
        try:
            res = dict(moderate(text, rules,  # T856+T857: strikes + lang hint
                                user_id=None if struck else user,  # T1034
                                lang=adapter_lang("discord", text),  # T897: env pin, else detect
                                adapter="discord"))  # T867: per-adapter counters
            if res["action"] not in ("ignored", "command"):  # T699
                health.decision()
        except Exception as e:  # noqa: BLE001 — one bad event, one line
            from gatekeeper.adapters.common import redact
            print("discord event error:", redact(e), file=sys.stderr,
                  flush=True)
            health.error(redact(e))
            res = {"action": "ignored", "reason": "moderate-error"}
        if res.get("action") in ("flag", "delete"):
            if struck and user:  # T1034: show standing, don't add to it
                from gatekeeper.strikes import standing
                res["strikes"] = standing(user)
            elif user:
                remod_mark(mkey, "struck")  # T1034: mirrors accrual exactly
    health.maybe_log()
    return res


async def send_removed_notice(msg, res):  # T859
    """The post-delete notice, as a threaded reply rather than a bare
    channel message: `reference=msg` keeps message_reference on it, so the
    notice stays anchored to the message it removed — in a thread
    msg.channel is the thread, in a channel the reference carries the
    context. delete_after=10 stays: a tombstone, not a monument."""
    await msg.channel.send(
        f"removed ({res['rule']} @ {res['confidence']:.2f})",
        delete_after=10, reference=msg)


def run(token: str | None = None, preset: str = "gaming"):
    from gatekeeper.adapters.common import AdapterError
    try:
        import discord  # optional dep: pip install -e .[discord]
    except ImportError as e:  # T820: coded, not a raw ModuleNotFoundError
        raise AdapterError(
            "E_ADAPTER: discord needs the discord.py extra — "
            "pip install -e .[discord]") from e

    from gatekeeper.adapters.common import (
        Health,
        cfg_get,
        install_shutdown,
        load_config,
        load_rules,
        rate_cap_from_env,
        require_env,
    )

    install_shutdown("discord", hard=True)  # T702: discord.py owns the loop
    cfg = load_config()  # T709: bouncer.toml defaults; env still wins
    rules = load_rules("discord", preset, cfg=cfg)  # T698+T709
    health = Health("discord")  # T699+T854: same counters as run_loop's
    cap = rate_cap_from_env(cfg)  # T701+T709+T854: parity with the pollers
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.tree.command(name="bouncer",  # T705: slash surface
                         description="moderation bot commands")
    @discord.app_commands.choices(command=[
        discord.app_commands.Choice(name=c, value=c)
        for c in ("rules", "stats", "appeal", "help")
    ])
    async def bouncer_slash(interaction, command: str):
        """Same table as the prefix surface — parity by construction."""
        from gatekeeper.adapters.common import as_user_id
        uid = as_user_id("discord", interaction.user.id)  # T864
        await interaction.response.send_message(
            command_reply(command, rules, user=uid)
            or command_reply("help", rules))

    async def _act(msg, res):  # T1033: one action path — posts and edits share it
        from gatekeeper.adapters.common import (
            dry_run,
            remod_mark,
            remod_see,
        )
        if dry_run():  # T697: print the intent, never the act
            if res["action"] in ("delete", "flag", "escalate"):
                from gatekeeper.adapters.common import redact
                print(f"[dry-run] discord {res['action']} "
                      f"({res['rule']}@{res['confidence']:.2f}): "
                      f"{redact(msg.content[:80])}")  # T700: pass, not leak
            return
        if res["action"] == "delete":
            mid = getattr(msg, "id", None)  # T1034: id-less fixtures opt out
            akey = f"discord:{mid}" if mid is not None else None
            if remod_see(akey, "removed"):  # T1034: no re-remove
                res["already_removed"] = True
                return
            try:  # T296: missing perms must not crash the bot loop
                await msg.delete()
            except Exception:  # noqa: BLE001 — fall back to flagging in place
                await msg.add_reaction("⚠️")
                return
            remod_mark(akey, "removed")  # T1034: only a real removal counts
            await send_removed_notice(msg, res)  # T859: threaded reply
        elif res["action"] in ("flag", "escalate"):
            await msg.add_reaction("⚠️")

    @client.event
    async def on_message(msg):  # T073
        if msg.author.bot:
            return
        if not msg.content.strip():  # T298: embeds/stickers carry no text
            return
        cmd = parse_command(msg.content)  # T705: prefix surface
        if cmd is not None:
            from gatekeeper.adapters.common import as_user_id
            await msg.channel.send(
                command_reply(cmd, rules,
                              user=as_user_id("discord", msg.author.id))  # T864
                or command_reply("help", rules))  # T705
            return
        res = moderate_message(msg.content, msg.author.id,  # T854: cap+health
                               rules, health=health, cap=cap,
                               msg_key=getattr(msg, "id", None))  # T1034
        await _act(msg, res)

    @client.event
    async def on_message_edit(before, after):  # T1033: MESSAGE_UPDATE judges
        """discord.py routes MESSAGE_UPDATE here; on_message judged first
        posts only. The same moderate_message path runs (RateCap and Health
        ride along, T854), so an edit into a violation cannot walk past the
        gate — and embed/title churn, which fires this event with identical
        text, never burns a model call."""
        if after.author.bot:
            return
        if not after.content.strip():  # T298: no text, nothing to judge
            return
        if before.content == after.content:
            return  # T1033: churn, not an edit — no text change, no re-judge
        if parse_command(after.content) is not None:
            return  # T1031 rule: commands fire on send, not on edit
        res = moderate_message(after.content, after.author.id,  # T854
                               rules, health=health, cap=cap,
                               msg_key=getattr(after, "id", None))  # T1034
        await _act(after, res)

    client.run(token or require_env(
        "DISCORD_TOKEN", cfg_get(cfg, "adapter", "discord", "token")))  # T691+T709


if __name__ == "__main__":
    run()
