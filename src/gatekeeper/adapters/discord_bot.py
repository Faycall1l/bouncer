"""Discord adapter stub (T073-T075). `pip install -e .[discord]` then run this module."""
from __future__ import annotations

# Apache-2.0. See LICENSE.


def run(token: str | None = None, preset: str = "gaming"):
    import discord  # optional dep; ImportError message tells the extra

    from gatekeeper import moderate
    from gatekeeper.adapters.common import install_shutdown, load_rules

    install_shutdown("discord", hard=True)  # T702: discord.py owns the loop
    rules = load_rules("discord", preset)  # T698: preset arg is just the default
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_message(msg):  # T073
        if msg.author.bot:
            return
        if not msg.content.strip():  # T298: embeds/stickers carry no text
            return
        if msg.content.strip() == "!bouncer rules":  # T074
            await msg.channel.send("active: " + ", ".join(rules))
            return
        if msg.content.strip() == "!bouncer stats":  # T297
            from gatekeeper.stats import get_stats
            s = get_stats()["actions"]
            await msg.channel.send("decisions: " + ", ".join(f"{a}={n}" for a, n in
                                                             sorted(s.items())))
            return
        res = moderate(msg.content, rules)
        from gatekeeper.adapters.common import dry_run
        if dry_run():  # T697: print the intent, never the act
            if res["action"] in ("delete", "flag", "escalate"):
                print(f"[dry-run] discord {res['action']} "
                      f"({res['rule']}@{res['confidence']:.2f}): "
                      f"{msg.content[:80]}")
            return
        if res["action"] == "delete":
            try:  # T296: missing perms must not crash the bot loop
                await msg.delete()
            except Exception:  # noqa: BLE001 — fall back to flagging in place
                await msg.add_reaction("⚠️")
                return
            await msg.channel.send(f"removed ({res['rule']} @ {res['confidence']:.2f})",
                                   delete_after=10)
        elif res["action"] in ("flag", "escalate"):
            await msg.add_reaction("⚠️")

    from gatekeeper.adapters.common import require_env
    client.run(token or require_env("DISCORD_TOKEN"))  # T075+T691: env, named


if __name__ == "__main__":
    run()
