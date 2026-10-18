# Security notes (T598)

The full asset/actor/trust-boundary view lives in
[threat-model.md](threat-model.md) (T771) — including its known-gaps table;
this file holds the operational how-tos.

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

## Key rotation — two-key window (T776)

Rotation without a client deadline uses a second accepted key,
`BOUNCER_KEY_OLD`. The server accepts **both** `BOUNCER_KEY` (current) and
`BOUNCER_KEY_OLD` (outgoing) — each compared constant-time, wrong key is 401
either way, and both comparisons always run (a `|=` on bools doesn't
short-circuit, so timing can't reveal which key was close). Runbook:

1. **Open the window.** Set `BOUNCER_KEY` to the *new* key and
   `BOUNCER_KEY_OLD` to the key clients hold today (same atomic secrets-file
   replace as above; with `serve --key-file` the file supplies the primary —
   export the old one in the environment). Restart once.
2. **Migrate at any pace.** Every client on either key keeps working; there
   is no clock on this step. The only rule: nothing still holding the old key
   may survive step 3.
3. **Close the window.** Unset `BOUNCER_KEY_OLD`, restart. The old key dies
   everywhere at once.

Notes: `BOUNCER_KEY_OLD` never enables auth by itself — only `BOUNCER_KEY`
turns the check on; the old key only widens it. Both vars warn at boot when
shorter than 16 chars (never the values). Drain via `/ready` for each restart
and nothing drops.

## Data handling

* The audit log stores a **sha256-truncated hash** of each message, never raw
  text (T273). Reversible reconstruction from the log isn't possible; if you need
  the original message for an appeal, keep it in your own system.
* Snapshots contain counters and per-user strike counts — no message content.
* Rate limiting is per-IP (60 req/min). Behind a reverse proxy set
  `BOUNCER_TRUSTED_PROXY` to your proxy's IP (comma-separate several): only
  when the **direct peer** matches does bouncer take the client IP from
  `X-Forwarded-For` — and only the rightmost entry, the one your proxy
  appended (anything a client sends itself sits further left, so it never
  counts). Without the var, or from any other peer, forwarding headers are
  ignored entirely and every request buckets by the socket peer — spoofed
  headers buy nobody extra rate (T777).
