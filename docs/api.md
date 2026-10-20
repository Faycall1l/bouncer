# API reference (T141, updated T394)

_(Last checked against v0.4.0.)_

* `POST /predict` `{message, rules, context?, threshold?, allow_threshold?,
  delete_threshold?, lang?}` → decision + reason. `context` ≤ 20 items, each
  ≤ 8000 chars (else 422 `E_CONTEXT`), message ≤ 8000 chars (else 413).
  `rules` caps (T773): 1–12 keys, each a
  ≤24-char slug (`a-z0-9-`) with value ≤ 280 chars — bombs get 422
  `E_RULES_COUNT`/`E_RULES_ID`/`E_RULES_TEXT`. Rule errors → 422 `{code, message}`.
  See [Request limits](#request-limits-t844) for body caps, extra fields
  and deadline semantics.
* `POST /predict/batch` `{messages[], rules, threshold?, allow_threshold?,
  delete_threshold?, lang?, timeout_s?}` → array, order kept. 1–32 messages
  (else 422/413), each ≤ 8000 chars. `lang` validates and routes like
  `/predict`'s (T836) — a preset autofills its pack's language when `lang` is
  omitted (T502 parity). `timeout_s`/`BOUNCER_TIMEOUT` bounds the **whole
  batch** (T837): rows that don't start before the deadline return escalate
  fallbacks (cause `batch-deadline`) instead of touching the model. Shares
  rate/auth guards with `/predict`.
* `POST /v1/systemone` `{state, questions}` → raw router passthrough (Jev SDKs work) — contents untyped, but the call shares `/predict`'s timeout/retry/breaker path (T833): a dead model is a coded `503 E_MODEL`, never a hung socket.
  Same rate/auth guards apply. `state.history` is bounded server-side (T774+T775):
  newest 20 items, each trimmed to 8000 chars (silently — passthrough keeps its
  wire contract), and `state`/`questions` dict keys ≤ 64 chars (else 422
  `E_STATE` — keys can't be trimmed coherently, so they're rejected).
* `GET /health` loaded/unavailable + uptime · `GET /version` · `GET /models` ·
  `GET /stats` (decisions + cache + version + uptime; gated like `/metrics`
  when `BOUNCER_KEY` is set — T842) · `GET /presets` ·
  `GET /metrics` (per-action counters, per-rule counters, cause counts,
  latency p50/p95, strike totals (counts only), `bouncer_requests_total
  {status}`, `bouncer_auth_failures_total`, `bouncer_rate_limited_total`,
  cache hits/misses/rate,
  `bouncer_info{version}`, uptime, `bouncer_breaker_open`, `bouncer_pool_*`)
  — exposed to loopback or with `X-API-Key` once `BOUNCER_KEY` is set (T778;
  keyless servers are open everywhere anyway).
* Headers: `X-Request-ID` echo, `X-Bouncer-ms` latency,
  `X-Content-Type-Options: nosniff`. Optional `X-API-Key` when `BOUNCER_KEY`
  set (constant-time compare; <16 chars warns at boot). 60 req/min/IP with
  `Retry-After: 60` on 429. Gzip above 1000 bytes. CORS origins: comma-separated
  `BOUNCER_CORS` env (default `*`, demo-friendly) or `bouncer serve --cors`;
  applied at process start. The stdout access log line carries
  `{rid, method, path, status, ms}` (T840) and `/predict`'s decision event
  line carries the same `rid`, so a request joins to its decision by id. `bouncer serve --keep-alive SECONDS` sets uvicorn's
  `timeout_keep_alive` (proxies that drop idle sockets sooner than uvicorn's 5s
  default), `--limit-concurrency N` caps simultaneous connections (default
  unlimited; T838).

## Request limits (T844)

One place for the caps that shape every POST, so the endpoint bullets above
don't have to repeat them:

* **Body cap is 1 MB, checked twice.** A `Content-Length` over 1 MB is 413
  **before** the body is read or parsed (T775). The header is client-trust,
  so a chunked body or a lying one is counted at the **byte level** by the
  stream cap and cut off mid-stream at the same 1 MB (T831) — the handler
  never runs and the unread tail is never buffered. Both 413s fire
  **before auth** on purpose (T843): an oversized body is rejected for what
  it *is*, so the key check (and the constant-time compare behind it) is
  never spent on a body the server would refuse anyway. The only thing an
  unauthenticated prober learns is the documented 1 MB cap.
* **Unknown request fields are 422, not silently dropped** (`extra="forbid"`,
  T835) on `/predict` and `/predict/batch` — a typo like `thresold` can't
  quietly fall back to defaults. The Jev passthrough (`/v1/systemone`) stays
  permissive on purpose: SDK metadata rides along without a 422 (T832 wire
  contract).
* **`timeout_s` is a per-request budget.** On `/predict` it bounds one
  decision (0.5–60 s, T515). On `/predict/batch` it bounds the **whole
  batch** (T837): rows that don't start before the deadline return escalate
  fallbacks (cause `batch-deadline`) instead of waking the model, and
  in-flight rows get only their remaining time. Worst case for one request
  is one budget plus one retry window, not `messages × 60 s`.
* **Rate limits are per worker process.** 60 req/min/IP lives in each
  worker's memory (no shared store) — `bouncer serve --workers N` multiplies
  the *effective* ceiling by N. Behind a load balancer, either keep workers
  at 1 for a strict limit or enforce the real limit at the LB; the
  per-IP bucket keying (and its trusted-proxy rule, T777) is identical in
  every worker.

## Presets + language (T595)

* `rules` and `preset` are **mutually exclusive** on `/predict` and
  `/predict/batch`: pass a built-in pack by name (`{"preset": "gaming"}`) or your
  own rules, never both — mixing is `422 {code: "E_PRESET"}` (packs are
  single-sourced; nothing is silently merged). Neither given → uses
  `BOUNCER_DEFAULT_PRESET` env if set, else the same `E_PRESET` error.
* Unknown preset name → `422 E_PRESET` (message lists valid names).
  `GET /presets` lists packs; `GET /presets/{name}` returns one.
* `lang` is a short lowercase slug (`[a-z-]{2,16}`, e.g. `es`, `fr`, `pt-br`) or
  omitted to infer from the message script; longer or uppercase input →
  `422 {code: "E_LANG"}`. Presets tagged `es`/`fr`/`ar` autofill the hint —
  passing an explicit `lang` still wins. (The demo UI offers an `auto` option;
  the API simply omits the field.)

## Snapshots + stats export (T608)

* CLI, not HTTP (state lives in the server process; snapshotting remotely would
  race in-flight decisions):
  * `bouncer snapshot save snap.json` — decision counters + per-user strikes,
    stamped with version + timestamp. `load` restores (unknown-version warns,
    never fails; corrupt/foreign file → `E_SNAPSHOT`).
  * `bouncer export --out audit.csv [--format json] [--since TS] [--action
    delete,flag] [--limit N]` — audit log as CSV or raw JSON array; `--limit`
    uses a bounded tail read.
  * `bouncer export --queue --out appeals.csv [--format json] [--since TS]
    [--action flag] [--limit N]` — the review queue as an appeal audit trail:
    who was flagged, with cause/model/preset context, and how it was
    adjudicated (verdict, verdict time, post-amnesty strike count). Queue
    text is raw (that file is the queue's 0600 contract, T784).
  * `bouncer export --stats stats.json` — counters + strikes snapshot as JSON
    (same data `GET /stats` serves, plus strikes; path is the argument, not
    `--out`).
* Programmatic: `gatekeeper.stats.save()/load()` and `audit.tail(n)`.

## Reliability fields (T596)

* `model` (request field, `bouncer check --model`) pins a checkpoint:
  `english` | `multilingual` | `typed-decisions`. Omitted → auto-routes by
  language hint. Unknown name → `422 {code: "E_MODEL_NAME"}` (the pool never
  builds speculative checkpoints).
* `timeout_s` (request field, 0.5–60s, else `BOUNCER_TIMEOUT` env, else 10s)
  bounds each model call; overruns count toward the breaker's failure streak.
* `GET /ready` — load-balancer readiness: `{"ready": bool, "model":
  "loaded"|"unavailable", "pool": {size, max_n, hits, creates, evictions}}`.
  Unlike `/health` (process liveness), `/ready` goes false when the model can't
  answer, so LBs stop routing before requests pile up.

## Auth + rate limits (T409)

* No key configured → open API (demo default). Set `BOUNCER_KEY` → every
  `POST` needs `X-API-Key`; wrong key is 401. Keys compare in constant time,
  so timing probes learn nothing.
* 60 requests/minute per IP across all endpoints (single, batch, passthrough
  share one bucket map; idle IPs evicted past 512 entries). Over → 429 with
  `Retry-After: 60`.
* Every response carries `X-Request-ID` (echoed or generated) and
  `X-Bouncer-ms` (server-side ms) — quote the request id in bug reports.

Terms used here are defined in the [Glossary](glossary.md).
