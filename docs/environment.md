# Environment variables (T807)

_(Last checked against v0.3.0.)_

Every environment variable the code reads, in one table. The split of
duties: this page is the *inventory* (kept honest by a test in both
directions — a variable added to code must get a row, a row without a
code read dies), the [adapters README](https://github.com/Faycall1l/bouncer/blob/main/src/gatekeeper/adapters/README.md)
carries per-platform setup depth, and [Security](SECURITY.md) /
[Runbook](runbook.md) carry the operational procedures. Defaults below
are what the code falls back to at read time.

## Server & CLI

| variable | default | meaning |
|---|---|---|
| `BOUNCER_KEY` | unset (API open) | shared secret: when set, every `POST` needs `X-API-Key`, compared constant-time; keys shorter than 16 chars warn at boot (T053, T292) |
| `BOUNCER_KEY_OLD` | unset | second accepted key during the two-key rotation window (T776) |
| `BOUNCER_CORS` | `*` | comma-separated allowed origins; `serve --cors` beats the env (T549) |
| `BOUNCER_TRUSTED_PROXY` | unset | comma-separated proxy peer IPs whose `X-Forwarded-For` counts for rate keys (T777) |
| `BOUNCER_DEFAULT_PRESET` | unset | preset used when a request carries neither `rules` nor `preset`; an unknown name fails the first request with 422 `E_PRESET` (T475) |
| `BOUNCER_QUESTIONS` | `5` | model question count, `3` or `5` — anything else is `E_CONFIG` (T755) |
| `BOUNCER_CACHE_SIZE` | `1024` | decision-cache entries (T271) |
| `BOUNCER_CACHE_TTL` | `60.0` | seconds before a cached decision expires (T271) |
| `BOUNCER_BREAKER` | `on` | `off` disables the circuit breaker (T523) |
| `BOUNCER_TIMEOUT` | `10.0` | per-request model timeout in seconds, clamped to 0.5–60 |
| `BOUNCER_POOL_MAX` | `2` | router-pool slots (T597); size it ≥ hot checkpoints |
| `BOUNCER_DEVICE` | unset (auto) | `cpu` / `cuda` device hint for router construction |
| `BOUNCER_MODEL_DIR` | unset | directory holding finetuned checkpoints (T664) |
| `BOUNCER_BAN_AT` | `3` | strikes before a ban is *suggested* — the action stays yours |

## State files

| variable | default | meaning |
|---|---|---|
| `BOUNCER_AUDIT` | `bouncer-audit.jsonl` | append-only decision log path (hashes only, no raw text) |
| `BOUNCER_AUDIT_FSYNC` | `0` | fsync every N audit lines; `0` = no forced fsync |
| `BOUNCER_REVIEW` | `review-queue.jsonl` | queue of flags/escalations, written `0600` (T784) |
| `BOUNCER_STATS` | `bouncer-stats.json` | counters snapshot path (T435) |
| `BOUNCER_STRIKES` | `bouncer-strikes.json` | per-user strike counters path (T432) |
| `BOUNCER_CONFIG` | `bouncer.toml` | config file read by CLI and adapters |
| `BOUNCER_RULES` | unset | default rules for adapters: a preset name or a JSON file path |
| `BOUNCER_RULES_<ADAPTER>` | unset | per-adapter override of `BOUNCER_RULES` (e.g. `BOUNCER_RULES_MATRIX`); either a preset name or a JSON path |
| `BOUNCER_PRESET` | `gaming` | preset for the container self-test in `scripts/docker-entrypoint.sh` |

## Adapters & forwarding

| variable | default | meaning |
|---|---|---|
| `BOUNCER_DRY_RUN` | unset | `1` = adapters print actions, never post (T697) |
| `BOUNCER_RATE_CAP` | `bouncer.toml` `[tuning] rate_cap`, then `10` | per-user model calls/min in pollers; `0` disables (T701) |
| `BOUNCER_TG_DELETE` | unset (flag-only) | `1` = Telegram may use deleteMessage |
| `BOUNCER_MX_REDACT` | unset (flag-only) | `1` = Matrix may redact messages |
| `BOUNCER_MM_DELETE` | unset (flag-only) | `1` = Mattermost may delete posts |
| `BOUNCER_ZL_DELETE` | unset (flag-only) | `1` = Zulip may delete messages |
| `BOUNCER_FORWARD_URL` | unset | webhook target for delete/flag/escalate events — treat the URL as a secret |
| `BOUNCER_FORWARD_ALLOW` | unset | comma-separated exact hosts the forwarder may hit, case-insensitive (SSRF pin, T785) |

## Platform tokens & hub

Connection credentials for the bots — setup steps per platform live in
the adapters README.

| variable | used by |
|---|---|
| `DISCORD_TOKEN` | Discord bot |
| `TWITCH_TOKEN` | Twitch IRC auth |
| `TWITCH_NICK` | Twitch nick |
| `TWITCH_CHAN` | Twitch channel (e.g. `#x`) |
| `TELEGRAM_TOKEN` | Telegram bot |
| `MATRIX_TOKEN` | Matrix access token |
| `MATRIX_HOMESERVER` | Matrix homeserver URL |
| `MATTERMOST_TOKEN` | Mattermost bot token |
| `MATTERMOST_SERVER` | Mattermost server URL |
| `ZULIP_API_KEY` | Zulip bot key |
| `ZULIP_EMAIL` | Zulip bot email |
| `ZULIP_SITE` | Zulip site URL |
| `HF_TOKEN` | checked by `scripts/check_kaggle_env.py`; huggingface_hub uses it for gated/private checkpoint downloads |

Terms used here are defined in the [Glossary](glossary.md).
