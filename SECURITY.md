# Security (T159)

* No secrets in code or logs. Tokens via env only (`DISCORD_TOKEN`,
  `TWITCH_TOKEN`, `BOUNCER_KEY`, `HF_TOKEN`). Twitch logs redact the token.
* Audit log stores SHA-256 hashes, never message text.
* Report vulns via GitHub private vulnerability reporting (no public PoC for
  bypasses until fixed — jailbreak routes are the attack surface).
