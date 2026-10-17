# Security notes (T598)

## API keys

* `BOUNCER_KEY` env — when set, every `POST` requires `X-API-Key`; wrong key is
  401. Comparison is constant-time (timing probes learn nothing). Keys shorter
  than 16 chars log a warning at boot (never the key itself).
* Unset → open API. That's the demo default and fine for localhost; anything
  internet-facing should set a key. `bouncer serve --key-file PATH` reads the
  key from a file and exports it as `BOUNCER_KEY` for the server process —
  same checks apply.

## `serve --key-file` (docker-secrets style, T547)

Instead of putting the key in the environment (which shows in `ps`, CI logs,
compose files), point bouncer at a file:

```bash
echo -n "s3cret..." > /run/secrets/bouncer_key   # or: docker secret create
bouncer serve --key-file /run/secrets/bouncer_key
```

The file is read once at startup, stripped of surrounding whitespace, and loaded
into `BOUNCER_KEY` for the server process. Missing or empty file → exit 4
(refuses to serve half-configured). The file is never logged or echoed.

## Key rotation

There is exactly one active key — bouncer doesn't keep a keyring, so rotation is
a restart:

1. Write the new key to the secrets file (atomic replace: write temp + `mv`).
2. Restart the process (`systemctl restart`, `docker compose up -d`, etc.).
3. Roll the new key to clients, then delete the old value everywhere it lived.

During the restart window `/health` fails (process down) — that's why `/ready`
exists for LBs; drain first if you need zero-dropped-requests rotation.

## Data handling

* The audit log stores a **sha256-truncated hash** of each message, never raw
  text (T273). Reversible reconstruction from the log isn't possible; if you need
  the original message for an appeal, keep it in your own system.
* Snapshots contain counters and per-user strike counts — no message content.
* Rate limiting is per-IP (60 req/min); behind a proxy set the real client IP
  via your reverse proxy's forwarding headers, or every user shares one bucket.
