"""Discord adapter stub (T073-T075). `pip install -e .[discord]` then run this module."""
from __future__ import annotations

# Apache-2.0. See LICENSE.


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


def command_reply(cmd: str, rules: dict, stats=None) -> str | None:  # T705
    """The single command table — the prefix handler and the slash handler
    both call this, so the two surfaces cannot drift apart."""
    if cmd == "rules":
        return "active: " + ", ".join(rules)
    if cmd == "stats":
        if stats is None:
            from gatekeeper.stats import get_stats
            stats = get_stats()["actions"]
        return "decisions: " + ", ".join(
            f"{a}={n}" for a, n in sorted(stats.items()))
    if cmd == "help":
        return ("commands: !bouncer rules | !bouncer stats | !bouncer help "
                "(slash: /bouncer command:)")
    return None


def run(token: str | None = None, preset: str = "gaming"):
    from gatekeeper.adapters.common import AdapterError
    try:
        import discord  # optional dep: pip install -e .[discord]
    except ImportError as e:  # T820: coded, not a raw ModuleNotFoundError
        raise AdapterError(
            "E_ADAPTER: discord needs the discord.py extra — "
            "pip install -e .[discord]") from e

    from gatekeeper import moderate
    from gatekeeper.adapters.common import (
        cfg_get,
        install_shutdown,
        load_config,
        load_rules,
        require_env,
    )

    install_shutdown("discord", hard=True)  # T702: discord.py owns the loop
    cfg = load_config()  # T709: bouncer.toml defaults; env still wins
    rules = load_rules("discord", preset, cfg=cfg)  # T698+T709
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.tree.command(name="bouncer",  # T705: slash surface
                         description="moderation bot commands")
    @discord.app_commands.choices(command=[
        discord.app_commands.Choice(name=c, value=c)
        for c in ("rules", "stats", "help")
    ])
    async def bouncer_slash(interaction, command: str):
        """Same table as the prefix surface — parity by construction."""
        await interaction.response.send_message(
            command_reply(command, rules) or command_reply("help", rules))

    @client.event
    async def on_message(msg):  # T073
        if msg.author.bot:
            return
        if not msg.content.strip():  # T298: embeds/stickers carry no text
            return
        cmd = parse_command(msg.content)  # T705: prefix surface
        if cmd is not None:
            await msg.channel.send(command_reply(cmd, rules)
                                   or command_reply("help", rules))  # T705
            return
        res = moderate(msg.content, rules)
        from gatekeeper.adapters.common import dry_run
        if dry_run():  # T697: print the intent, never the act
            if res["action"] in ("delete", "flag", "escalate"):
                from gatekeeper.adapters.common import redact
                print(f"[dry-run] discord {res['action']} "
                      f"({res['rule']}@{res['confidence']:.2f}): "
                      f"{redact(msg.content[:80])}")  # T700: pass, not leak
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

    client.run(token or require_env(
        "DISCORD_TOKEN", cfg_get(cfg, "adapter", "discord", "token")))  # T691+T709


if __name__ == "__main__":
    run()
