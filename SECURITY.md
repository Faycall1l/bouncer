# Security (T159)

* No secrets in code or logs. Tokens via env only (`DISCORD_TOKEN`,
  `TWITCH_TOKEN`, `BOUNCER_KEY`, `HF_TOKEN`). Twitch logs redact the token.
* Audit log stores SHA-256 hashes, never message text.
* Report vulns via GitHub private vulnerability reporting (no public PoC for
  bypasses until fixed — jailbreak routes are the attack surface).

## `BOUNCER_*` env (T403)

| var | secret? | effect |
|---|---|---|
| `BOUNCER_KEY` | yes (≥16 chars; boot warns if short) | requires `X-API-Key` on the API |
| `BOUNCER_CORS` | no | comma-separated allowed origins (default `*`) |
| `BOUNCER_AUDIT` | no | audit JSONL path |
| `BOUNCER_REVIEW` | no | review queue path |
| `BOUNCER_FORWARD_URL` | URL (treat as secret) | delete/flag/escalate events POSTed here |
| `BOUNCER_BAN_AT` | no | strikes before ban suggestion (default 3) |
| `BOUNCER_CACHE_SIZE` / `BOUNCER_CACHE_TTL` | no | decision cache bounds |
