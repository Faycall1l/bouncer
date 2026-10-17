# Adapters (T080)

| Platform | File | Setup |
|---|---|---|
| Discord | `adapters/discord_bot.py` | `pip install -e .[discord]`, `DISCORD_TOKEN=... python -m gatekeeper.adapters.discord_bot` |
| Twitch | `adapters/twitch_irc.py` | stdlib only. `TWITCH_TOKEN=... TWITCH_NICK=... TWITCH_CHAN=#x python -m gatekeeper.adapters.twitch_irc` (flag-only, never bans) |
| Telegram | `adapters/telegram_bot.py` | stdlib only. `TELEGRAM_TOKEN=... python -m gatekeeper.adapters.telegram_bot` (long-poll, `/rules` `/stats` `/help`, flag-only default; `BOUNCER_TG_DELETE=1` opts into deleteMessage) |
| Matrix | `adapters/matrix_bot.py` | stdlib only. `MATRIX_TOKEN=... MATRIX_HOMESERVER=... python -m gatekeeper.adapters.matrix_bot` (sync timeline, `!bouncer rules` `!bouncer stats`, flag-only default; `BOUNCER_MX_REDACT=1` opts into redactions) |
| Mattermost | `adapters/mattermost.py` | `pip install -e .[mattermost]`. `MATTERMOST_SERVER=... MATTERMOST_TOKEN=... python -m gatekeeper.adapters.mattermost` (websocket `posted` events + `/bouncer` slash webhook; `BOUNCER_MM_DELETE=1` opts into deletePost) |
| Zulip | `adapters/zulip_bot.py` | stdlib only. `ZULIP_EMAIL=... ZULIP_API_KEY=... ZULIP_SITE=... python -m gatekeeper.adapters.zulip_bot` (event-queue poll, stream messages moderated, PMs/mentions are `bouncer` commands; `BOUNCER_ZL_DELETE=1` opts into delete) |
| Slack/events | `adapters/webhooks.py` | call `receive_slack_event(body, rules)` from your receiver |
| Any | `forward_if_interesting()` | set `BOUNCER_FORWARD_URL` to POST delete/flag/escalate events |

Tokens always from env, never logged (twitch redacts, discord never prints).
Missing tokens fail at startup via the shared `require_env()` guard
(`gatekeeper.adapters.common`, `E_ADAPTER`) — the error names the variable
instead of a raw `KeyError`; blank counts as missing (T691).

The shared SDK (`common.py`) is `require_env()` + `run_loop()` (T696): every
sync poller (telegram, matrix, zulip) runs the same fetch/handle loop —
fetch failures log and back off 5s, a bad event costs one log line, Ctrl-C
always stops the bot. Mattermost's websocket loop is the async exception;
its per-event guard matches `run_loop()`'s.

`BOUNCER_DRY_RUN=1` (T697) applies to every adapter: outbound calls
(delete/redact/PM/reply/forward) are printed as `[dry-run] would ...` and
never performed. Twitch is print-only by design, so it's a no-op there.

Rules come from `load_rules()` (T698): `BOUNCER_RULES` names a preset or
points at a JSON file of rules; `BOUNCER_RULES_<ADAPTER>` (e.g.
`BOUNCER_RULES_MATRIX`) overrides it per adapter. An unknown preset or an
unreadable rules file fails at startup with `E_ADAPTER`, before any loop
starts.

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
