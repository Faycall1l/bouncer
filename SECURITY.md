# Security (T159)

* No secrets in code or logs. Tokens via env only (`DISCORD_TOKEN`,
  `TWITCH_TOKEN`, `BOUNCER_KEY`, `HF_TOKEN`). Twitch logs redact the token.
* Audit log stores SHA-256 hashes, never message text.

## Where the details live (T788)

* **Threat model** — assets, actors, trust boundaries, every countermeasure
  with the T-box that implements it:
  [docs/threat-model.md](docs/threat-model.md) (T771).
* **Operational security** — key rotation, `/metrics` exposure, log/demo
  handling, the webhook SSRF guard, what bouncer does and doesn't store:
  [docs/SECURITY.md](docs/SECURITY.md) (T598).
* **Ops runbook** — backup, restore, rotate, drain, at 3am:
  [docs/runbook.md](docs/runbook.md) (T789).

## Reporting a vulnerability (T788)

Use **Report a vulnerability** on this repo's *Security* tab (GitHub private
vulnerability reporting — the report stays between you and the maintainers).
Please don't open a public issue with exploit details or bypass PoCs; a fix
lands first, disclosure after. What counts: auth/key bypasses, injection into
logs or responses, rate-limit or SSRF bypasses, unsafe defaults that leak
data — jailbreak routes are the attack surface.

## `BOUNCER_*` env (T403)

| var | secret? | effect |
|---|---|---|
| `BOUNCER_KEY` | yes (≥16 chars; boot warns if short) | requires `X-API-Key` on the API |
| `BOUNCER_KEY_OLD` | yes | second key accepted during rotation (two-key window, T776) |
| `BOUNCER_CORS` | no | comma-separated allowed origins (default `*`) |
| `BOUNCER_AUDIT` | no | audit JSONL path |
| `BOUNCER_REVIEW` | no | review queue path |
| `BOUNCER_FORWARD_URL` | URL (treat as secret) | delete/flag/escalate events POSTed here |
| `BOUNCER_FORWARD_ALLOW` | no | comma-separated exact hosts the forwarder may hit (SSRF pin, T785) |
| `BOUNCER_TRUSTED_PROXY` | no | proxy peer IPs whose `X-Forwarded-For` counts for rate keys (T777) |
| `BOUNCER_BAN_AT` | no | strikes before ban suggestion (default 3) |
| `BOUNCER_CACHE_SIZE` / `BOUNCER_CACHE_TTL` | no | decision cache bounds |
