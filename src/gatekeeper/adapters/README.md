# Adapters (T080)

| Platform | File | Setup | SDK features (T691–T702) |
|---|---|---|---|
| Discord | `adapters/discord_bot.py` | `pip install -e .[discord]`, `DISCORD_TOKEN=... python -m gatekeeper.adapters.discord_bot` | Health, RateCap (T854), require_env, load_rules, dry-run, redact, SIGTERM (hard — discord.py owns cleanup) |
| Twitch | `adapters/twitch_irc.py` | stdlib only. `TWITCH_TOKEN=... TWITCH_NICK=... TWITCH_CHAN=#x python -m gatekeeper.adapters.twitch_irc` (flag-only, never bans) | Health (T855), require_env, load_rules, redact (delegates to shared pass), dry-run (no-op — print-only), SIGTERM (between reconnects) |
| Telegram | `adapters/telegram_bot.py` | stdlib only. `TELEGRAM_TOKEN=... python -m gatekeeper.adapters.telegram_bot` (long-poll, `/rules` `/stats` `/appeal` `/help`, flag-only default; `BOUNCER_TG_DELETE=1` opts into deleteMessage) | run_loop, Health, RateCap, require_env, load_rules, dry-run, redact, SIGTERM |
| Matrix | `adapters/matrix_bot.py` | stdlib only. `MATRIX_TOKEN=... MATRIX_HOMESERVER=... python -m gatekeeper.adapters.matrix_bot` (sync timeline, `!bouncer rules` `!bouncer stats`, flag-only default; `BOUNCER_MX_REDACT=1` opts into redactions) | run_loop, Health, RateCap, require_env, load_rules, dry-run, redact, SIGTERM |
| Mattermost | `adapters/mattermost.py` | `pip install -e .[mattermost]`. `MATTERMOST_SERVER=... MATTERMOST_TOKEN=... python -m gatekeeper.adapters.mattermost` (websocket `posted` events + `/bouncer` slash webhook, `MATTERMOST_SLASH_TOKEN` compared constant-time; `BOUNCER_MM_DELETE=1` opts into deletePost) | areconnect + `_session` (T852: dropped socket redials with capped jittered backoff), Health, RateCap, require_env, load_rules, dry-run, redact, SIGTERM |
| Zulip | `adapters/zulip_bot.py` | stdlib only. `ZULIP_EMAIL=... ZULIP_API_KEY=... ZULIP_SITE=... python -m gatekeeper.adapters.zulip_bot` (event-queue poll, stream messages moderated, PMs/mentions are `bouncer` commands; `BOUNCER_ZL_DELETE=1` opts into delete) | run_loop, Health, RateCap, require_env, load_rules, dry-run, redact, SIGTERM |
| Slack/events | `adapters/webhooks.py` | call `receive_slack_event(body, rules)` from your receiver; pass `secret`+`raw`+`ts`+`signature` to enforce Slack v0 signature verification (fail-closed) | dry-run, redact, verify_signature |
| Any | `forward_if_interesting()` | set `BOUNCER_FORWARD_URL` to POST delete/flag/escalate events; fires from the HTTP receivers and from every `run_loop` poll loop now too (T866: each adapter passes `message_of` for the event text); breaker-open results fire too and carry `cause`; http(s) only, and `BOUNCER_FORWARD_ALLOW` (comma-separated hosts) pins exact destinations (T785) | dry-run, redact |
| *shared* | `adapters/common.py` | imported, never run directly | require_env, load_rules, run_loop, http_json, backoff_wait, areconnect, Health, RateCap, redact, as_user_id, detect_lang, dry_run, install_shutdown, verify_signature, load_config |

The matrix's SDK column is the T703 truth: `common.py` (T691–T709) is the
whole shared surface — `require_env`/`load_rules`/`load_config` at startup,
`run_loop` + `Health` + `RateCap` + `install_shutdown` around the loop,
`redact` + `dry_run` on every outbound line, `as_user_id` (T856+T858) handing
each platform's user to `moderate(user_id=...)` namespaced `platform:user`
so per-user strikes accrue per platform from chat traffic, not just the
CLI, and `detect_lang` (T857) deriving
`lang=` from the message script so non-latin platform traffic pins the
multilingual checkpoint instead of routing as auto. Every `moderate(...)`
call also carries `adapter=` (T867) — its platform name — so `stats`
counts decisions per adapter. A new adapter gets all
of it by importing from `common`; nothing in the column may name a helper
that doesn't exist.

## Capabilities (T868)

Reply / thread / health / rate-cap / forward / lang per platform — every
cell is a source fact, and `test_readme_capability_matrix_matches_sources`
checks them against the adapters. `—` means the platform can't express it
or the adapter never posts.

| Platform | reply anchor | answer / notice threading | health line | rate cap | forward | lang hint |
|---|---|---|---|---|---|---|
| Telegram | commands → `reply_to_message_id` (T860) | answers nest under the ask; moderation prints (flag-only default) | T699 | T701 | T866 `message_of` | T857 |
| Matrix | command notices → `m.relates_to.m.in_reply_to` (T861) | threaded under the trigger; moderation redacts + prints | T699 | T701 | T866 `message_of` | T857 |
| Zulip | PM/mention answers | stream replies keep the `subject` topic (T863) | T699 | T701 | T866 `message_of` | T857 |
| Mattermost | slash → `root_id` (T862) | slash answer threads under the command; ws moderation prints | T699 | T701 | — own websocket loop | T857 |
| Discord | prefix + slash answers, unanchored | delete tombstone → `reference=msg` (T859) | T699 | T701 + T854 | — own event loop | T857 |
| Twitch | — no command surface | moderation prints, never bans | T855 | — no cap wired | — own loop | T857 |
| Slack/events | — never posts | — never posts | — library, no loop | — | the forwarder itself (T707) | T857 |

## Config file (T709)

Every adapter reads `bouncer.toml` from the working directory (override the
path with `BOUNCER_CONFIG`) via the shared `load_config()`, stdlib `tomllib`.
The precedence is always: **env var > file > default** — the file supplies
defaults, the environment is the deployment. A missing file is fine (`{}`);
broken TOML fails at startup with `E_ADAPTER` naming the file.

```toml
# bouncer.toml — adapter defaults; env vars always win (T709)
[adapter.telegram]
token = "123456:AA..."          # instead of TELEGRAM_TOKEN
delete = true                   # instead of BOUNCER_TG_DELETE=1
rules = "gaming"                # preset name or JSON file path (T698)

[adapter.matrix]
token = "syt_..."
homeserver = "https://matrix.example.org"
redact = true                   # BOUNCER_MX_REDACT

[adapter.mattermost]
server = "https://mm.example.org"
token = "..."
delete = false                  # flag-only default stands

[adapter.zulip]
email = "bouncer-bot@example.org"
api_key = "..."
site = "https://zulip.example.org"
delete = false

[adapter.twitch]
nick = "bouncerbot"
chan = "#gaming"
token = "oauth:..."

[adapter.discord]
token = "..."

[tuning]
rate_cap = 10                   # per-user model calls/min (T701); 0 disables
```

Tokens always from env, never logged — every printed line passes the shared
`redact()` (T700). Missing tokens fail at startup via the shared
`require_env()` guard (`gatekeeper.adapters.common`, `E_ADAPTER`) — the error
names the variable instead of a raw `KeyError`; blank counts as missing (T691).

The shared SDK (`common.py`) is `require_env()` + `run_loop()` (T696): every
sync poller (telegram, matrix, zulip) runs the same fetch/handle loop —
fetch failures log and back off from 5s, doubling with jitter up to a 60s
cap (T853), a bad event costs one log line, Ctrl-C
always stops the bot. Mattermost's websocket session is the async
exception; its per-event guard matches `run_loop()`'s, and the reconnect
loop around it is `areconnect()` (T852): a dropped socket logs one
redacted line, records a health error, and redials with capped exponential
backoff + jitter — bounded by SIGTERM, never by a server restart.

`BOUNCER_DRY_RUN=1` (T697) applies to every adapter: outbound calls
(delete/redact/PM/reply/forward) are printed as `[dry-run] would ...` and
never performed. Twitch is print-only by design, so it's a no-op there.

Rules come from `load_rules()` (T698): `BOUNCER_RULES` names a preset or
points at a JSON file of rules; `BOUNCER_RULES_<ADAPTER>` (e.g.
`BOUNCER_RULES_MATRIX`) overrides it per adapter. An unknown preset or an
unreadable rules file fails at startup with `E_ADAPTER`, before any loop
starts.

Every adapter's loop also logs a health line (T699, all six since T855)
every 5 minutes:
`<name> health: N decisions/min, last error: <age> — <msg>` (or `none`).
Ignored traffic and command replies aren't counted as decisions; fetch and
event errors are recorded as the last error with its age.

Every log line and decision print goes through the shared `redact()` pass
(T700): exact env token/site values, `Bearer`/`oauth:`/`Basic` credentials,
emails, and URL query secrets are masked. Twitch's T077 `redact()` now
delegates to it.

Every adapter that can act on a message carries a per-user rate cap
(T701): `BOUNCER_RATE_CAP` model
calls per user per minute (default 10, `0` disables). Over-cap messages
are logged as `[rate-limited]` and skipped — a flood can't monopolize the
model. Command replies bypass the cap; they never reach the model anyway.

SIGTERM shuts every adapter down cleanly (T702): the poll loops finish the
current page and exit; a second SIGTERM force-exits (128+sig, uvicorn
style). Discord's handler is hard — discord.py owns its own loop and
cleanup. Ctrl-C works everywhere, as always.

Webhook receivers verify signatures with `verify_signature()` (T704):
constant-time `hmac.compare_digest` throughout, malformed input is a
mismatch (never an exception), `prefix` covers GitHub-style `sha256=`
schemes. `webhooks.verify_slack_signature()` wraps it for Slack's v0
scheme with a 300s replay window; pass a `secret` to
`receive_slack_event` to enforce it — fail-closed, a missing piece
raises `E_SLACK` instead of letting an unsigned event through.

## Notes (T408)

* Discord: `!bouncer <cmd>` and the `/bouncer` slash command answer from one
  table (T705): `rules`, `stats`, `help` (unknown subcommands fall back to
  help). Deletes fall back to ⚠️ on missing perms; empty messages ignored.
* Twitch: reconnects 3× with backoff, then exits 1. All console output passes
  `redact()` — the T077 helper now delegates to the shared T700 pass.
  Mentions are ordinary PRIVMSG text and get moderated like any message;
  whispers (`WHISPER` lines) are out of scope (T706) — a flag-only bot can't
  act on them, and the parser drops them before moderation. Need eyes on
  whispers? Route them through your own receiver + `forward_if_interesting()`.
* Webhooks: `forward()` sends `User-Agent: bouncer/<ver>` + `X-Bouncer-Event`;
  failures raise `E_WEBHOOK`. Slack ignores `bot_message` subtypes
  (explicit `ignored` shape) and rejects malformed bodies with `E_SLACK`.
  `forward_if_interesting()` (T707) fires on breaker-open too — keyed on
  `cause`, and the payload carries `cause` so the receiver can tell a model
  escalation from a breaker-driven default.

## Model routing (T604)

Adapters call `moderate(msg, rules)` with **no `model=`** and only the
script-derived `lang=` (T857): latin traffic stays hintless, so
`model_for_lang()` returns nothing and laya routes by the `script` the
engine computed for the state; arabic/cjk/cyrillic carry `lang=` and pin
the multilingual checkpoint directly (either way it lands there).
Every checkpoint touched lands in the shared pool (`BOUNCER_POOL_MAX`,
default 2), so a multilingual community can
hold both english + multilingual routers in memory. Two operational consequences:

* A mixed-language server can exceed the pool's slots and thrash (each request
  paying a full reload) — raise `BOUNCER_POOL_MAX` if `GET /stats` shows
  `pool.evictions` climbing.
* To pin one checkpoint for an adapter (e.g. english-only Twitch), pass
  `model=` at its `moderate()` call — the adapters don't expose a flag for it
  yet; copy the 3-line loop or send those messages through
  `POST /predict {"model": ...}` instead.
