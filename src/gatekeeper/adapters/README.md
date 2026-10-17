# Adapters (T080)

| Platform | File | Setup |
|---|---|---|
| Discord | `adapters/discord_bot.py` | `pip install -e .[discord]`, `DISCORD_TOKEN=... python -m gatekeeper.adapters.discord_bot` |
| Twitch | `adapters/twitch_irc.py` | stdlib only. `TWITCH_TOKEN=... TWITCH_NICK=... TWITCH_CHAN=#x python -m gatekeeper.adapters.twitch_irc` (flag-only, never bans) |
| Slack/events | `adapters/webhooks.py` | call `receive_slack_event(body, rules)` from your receiver |
| Any | `forward_if_interesting()` | set `BOUNCER_FORWARD_URL` to POST delete/flag/escalate events |

Tokens always from env, never logged (twitch redacts, discord never prints).

## Notes (T408)

* Discord: `!bouncer rules` prints the pack, `!bouncer stats` prints decision
  counts. Deletes fall back to ⚠️ on missing perms; empty messages ignored.
* Twitch: reconnects 3× with backoff, then exits 1. All console output passes
  `redact()` (exact token + any `oauth:` secret masked).
* Webhooks: `forward()` sends `User-Agent: bouncer/<ver>` + `X-Bouncer-Event`;
  failures raise `E_WEBHOOK`. Slack ignores `bot_message` subtypes
  (explicit `ignored` shape) and rejects malformed bodies with `E_SLACK`.

## Model routing (T604)

Adapters call `moderate(msg, rules)` with **no `model=`/`lang=`** — that means
auto-routing: with no `lang` hint, `model_for_lang()` returns nothing and laya
routes by the `script` the engine computed for the state (non-latin text tends
to land on the multilingual checkpoint). Every checkpoint touched lands in the
shared pool (`BOUNCER_POOL_MAX`, default 2), so a multilingual community can
hold both english + multilingual routers in memory. Two operational consequences:

* A mixed-language server can exceed the pool's slots and thrash (each request
  paying a full reload) — raise `BOUNCER_POOL_MAX` if `GET /stats` shows
  `pool.evictions` climbing.
* To pin one checkpoint for an adapter (e.g. english-only Twitch), pass
  `model=` at its `moderate()` call — the adapters don't expose a flag for it
  yet; copy the 3-line loop or send those messages through
  `POST /predict {"model": ...}` instead.
