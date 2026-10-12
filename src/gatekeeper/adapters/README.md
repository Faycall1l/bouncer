# Adapters (T080)

| Platform | File | Setup |
|---|---|---|
| Discord | `adapters/discord_bot.py` | `pip install -e .[discord]`, `DISCORD_TOKEN=... python -m gatekeeper.adapters.discord_bot` |
| Twitch | `adapters/twitch_irc.py` | stdlib only. `TWITCH_TOKEN=... TWITCH_NICK=... TWITCH_CHAN=#x python -m gatekeeper.adapters.twitch_irc` (flag-only, never bans) |
| Slack/events | `adapters/webhooks.py` | call `receive_slack_event(body, rules)` from your receiver |
| Any | `forward_if_interesting()` | set `BOUNCER_FORWARD_URL` to POST delete/flag events |

Tokens always from env, never logged (twitch redacts, discord never prints).
