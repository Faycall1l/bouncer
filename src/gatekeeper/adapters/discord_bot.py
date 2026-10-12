"""Discord adapter stub (T073-T075). `pip install -e .[discord]` then run this module."""
from __future__ import annotations

import os


def run(token: str | None = None, preset: str = "gaming"):
    import discord  # optional dep; ImportError message tells the extra
    from gatekeeper import moderate, get_preset

    rules = get_preset(preset)
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_message(msg):  # T073
        if msg.author.bot:
            return
        if msg.content.strip() == "!bouncer rules":  # T074
            await msg.channel.send("active: " + ", ".join(rules))
            return
        res = moderate(msg.content, rules)
        if res["action"] == "delete":
            await msg.delete()
            await msg.channel.send(f"removed ({res['rule']} @ {res['confidence']:.2f})", delete_after=10)
        elif res["action"] in ("flag", "escalate"):
            await msg.add_reaction("⚠️")

    client.run(token or os.environ["DISCORD_TOKEN"])  # T075: env, never logged


if __name__ == "__main__":
    run()
