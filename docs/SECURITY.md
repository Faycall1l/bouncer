# Security notes (T598)

_(Last checked against v0.4.0.)_

The full asset/actor/trust-boundary view lives in
[threat-model.md](threat-model.md) (T771) — including its known-gaps table;
this file holds the operational how-tos, and the 3am procedures (backup,
restore, rotate, drain) live in [runbook.md](runbook.md) (T789).

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

## Demo share mode (T780)

`bouncer demo --share` asks Gradio for a public URL. Gradio links carry no
auth of their own: everyone who gets the URL sees the **rule editor (your
full rulebook), every typed message, the decision trail and the review
rows**. Bouncer prints a structured `{"warn": ...}` line at launch — before
gradio loads and before the port binds — so a shared demo can't start
quietly. Treat a shared link as full disclosure of everything typed into
it; for anything beyond disposable demo rules, run without `--share`.

## Log & terminal injection (T779)

Anything a client or an operator can type ends up in stdout somewhere, so
the guard sits at the source, not in the reader:

* every server log line (`access`, `internal-error`) is `json.dumps`-emitted:
  quotes and controls in an `X-Request-ID` or a %-decoded path get escaped
  and the key set is fixed — a hostile value can't close its string and
  forge fields, and the line always parses;
* `X-Request-ID` is scrubbed to printables **before** it's echoed in the
  response header and written to the log;
* decision **reasons** are scrubbed inside `explain()` itself — one source,
  every consumer: rule text carrying ANSI wipes, bells or newlines never
  reaches `bouncer check`/`watch` output or an API response;
* `watch` scrubs the 120-char message preview and any `watch error:` line
  before they touch your terminal.

The decision line and the JSON file outputs (`audit.jsonl`, review queue)
were already `json.dumps` — controls there were always escaped, and stay
that way.

## `/metrics` + `/stats` exposure (T778, T842)

`GET /metrics` (traffic counters, cache, breaker, latency) is gated as soon
as `BOUNCER_KEY` is set:

* **loopback** peer with no `X-Forwarded-For` (a direct local scrape) →
  served without the key;
* **anyone else** → `X-API-Key` required (Prometheus sends it as a header);
  wrong or missing key → 401.

The gate reads the **socket peer**, which no header can spoof: a
`X-Forwarded-For` can only *remove* the local exemption (your local proxy
forwarded the request), never grant it. With no key configured the server
is open on every route anyway — metrics follow the same bargain. `/health`,
`/ready`, and the other GETs keep their LB-facing contract. `GET /stats`
(decisions, breaker, strikes tallies — same data, JSON) rides the **same
gate** since T842; this gate is metrics and stats alone.

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

## Webhook forward SSRF guard (T785)

`BOUNCER_FORWARD_URL` is operator config, not end-user input — but a
copied template or a compromised config could still point the forwarder
at `file://`, an internal admin panel or the cloud metadata address. So
`forward()` refuses anything that isn't http(s) **before a socket opens**,
and setting `BOUNCER_FORWARD_ALLOW` (comma-separated hosts) narrows it
further: only those exact hosts receive events (case-insensitive; a
subdomain of an allowed host is *not* allowed). Timeout is 10s per
attempt; failures surface as `E_WEBHOOK`, never as a silent drop.

## Platform adapters — nothing destructive by default (T826)

The 0.4.0 adapters (Discord, Twitch, Telegram, Matrix, Mattermost, Zulip,
webhooks) share one posture, so a bot dropped into a busy channel can't
act beyond moderation:

* **Flag-only default.** Chat-mutating actions are refused unless the
  matching opt-in env var is `1`: `BOUNCER_TG_DELETE`,
  `BOUNCER_MX_REDACT`, `BOUNCER_MM_DELETE`, `BOUNCER_ZL_DELETE`
  (T692–T695). Out of the box every adapter only flags/escalates; Twitch
  never bans at all. `BOUNCER_DRY_RUN=1` goes further and prints every
  would-be action instead of posting it (T697).
* **Fail-closed startup.** A missing platform token or missing extra stops
  boot with a coded `E_ADAPTER` naming the first missing var and the fix —
  never a half-connected bot, never a raw traceback (T691).
* **Tokens stay env-only.** `DISCORD_TOKEN`, `TWITCH_TOKEN`,
  `TELEGRAM_TOKEN`, `MATRIX_TOKEN`, `MATTERMOST_TOKEN`, `ZULIP_API_KEY`
  are read from the environment only, and the shared redaction pass wipes
  tokens/emails out of anything adapters log (T700). The Mattermost slash
  token is compared constant-time (`hmac.compare_digest`, T694).
* **Signed webhooks are fail-closed.** Slack events passed to
  `receive_slack_event` with a `secret` are verified with constant-time
  HMAC and a 300s replay window; a missing or bad signature raises
  `E_SLACK` instead of letting an unsigned event through (T704).
* Everything an adapter forwards to `BOUNCER_FORWARD_URL` goes through the
  SSRF pin above (T785) — the platform side inherits the same guard.
* **Bounded, jittered retries** (T851–T853). One shared HTTP helper
  retries 429/5xx honoring `Retry-After` on a capped jittered ladder
  (5s base, 60s cap; websocket reconnects jitter likewise and reset after
  a stable session) — a sick platform API gets a polite client, never a
  tight hammering loop from every bot at once.
* **Per-user caps before the model** (T701, T854). Pollers enforce the
  per-user model calls/min cap *before* spending a model call, so one
  abusive platform user can't burn the quota; Twitch has no cap at all.
* **Strikes accrue per namespaced platform user** (T856, T858). Every
  adapter passes the sender as `platform:user`, so per-user strikes now
  accrue from live platform traffic — a Discord id 42 and a Telegram id
  42 stay separate rows — and cached/coalesced verdicts never carry
  another user's strikes.
* **Appeals answer; operators decide** (T864, T865, T973). The APPEAL
  command renders the user's newest queue row read-only, citing its row
  id; approve/reject and strike amnesty exist only on the operator's
  CLI (pinned T973), and every CLI amnesty writes a hash-only audit row
  (T974).

Per-platform setup (which extra, which vars) lives in the
[adapters README](https://github.com/Faycall1l/bouncer/blob/main/src/gatekeeper/adapters/README.md);
the inventory of every variable is [environment.md](environment.md).

## Data handling

* The audit log stores a **sha256-truncated hash** of each message, never raw
  text (T273). Reversible reconstruction from the log isn't possible; if you need
  the original message for an appeal, keep it in your own system.
* Snapshots contain counters and per-user strike counts — no message content.
  They're written **0600** (owner-only) by the atomic writer, so umask can't
  leak them world-readable (T783).
* The **review queue is the one artifact that holds raw message text** — by
  design: a reviewer can't adjudicate a hash. Rows are bounded (≤500 chars),
  the file is gitignored, prunable (`prune`, T442) and clearable
  (`bouncer review --clear --yes`, T318) — and written **0600** like the
  snapshots, since it's the file where raw text actually lives (T784). The
  audit log itself stays hashed (T273).
* Rate limiting is per-IP (60 req/min). Behind a reverse proxy set
  `BOUNCER_TRUSTED_PROXY` to your proxy's IP (comma-separate several): only
  when the **direct peer** matches does bouncer take the client IP from
  `X-Forwarded-For` — and only the rightmost entry, the one your proxy
  appended (anything a client sends itself sits further left, so it never
  counts). Without the var, or from any other peer, forwarding headers are
  ignored entirely and every request buckets by the socket peer — spoofed
  headers buy nobody extra rate (T777).
