# API reference (T141, updated T394)

* `POST /predict` `{message, rules, context?, threshold?, allow_threshold?,
  delete_threshold?, lang?}` → decision + reason. `context` ≤ 20 items (else 422),
  message ≤ 8000 chars (else 413). Rule errors → 422 `{code, message}`.
* `POST /predict/batch` `{messages[], rules, threshold?, allow_threshold?,
  delete_threshold?}` → array, order kept. 1–32 messages (else 422/413), each
  ≤ 8000 chars. Shares rate/auth guards with `/predict`.
* `POST /v1/systemone` `{state, questions}` → raw router passthrough (Jev SDKs work).
  Same rate/auth guards apply.
* `GET /health` loaded/unavailable + uptime · `GET /version` · `GET /models` ·
  `GET /stats` (decisions + cache + version + uptime) · `GET /presets` ·
  `GET /metrics` (per-action counters, cache hits/misses/rate, latency p50,
  `bouncer_info{version}`, uptime).
* Headers: `X-Request-ID` echo, `X-Bouncer-ms` latency,
  `X-Content-Type-Options: nosniff`. Optional `X-API-Key` when `BOUNCER_KEY`
  set (constant-time compare; <16 chars warns at boot). 60 req/min/IP with
  `Retry-After: 60` on 429. Gzip above 1000 bytes.

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

## Auth + rate limits (T409)

* No key configured → open API (demo default). Set `BOUNCER_KEY` → every
  `POST` needs `X-API-Key`; wrong key is 401. Keys compare in constant time,
  so timing probes learn nothing.
* 60 requests/minute per IP across all endpoints (single, batch, passthrough
  share one bucket map; idle IPs evicted past 512 entries). Over → 429 with
  `Retry-After: 60`.
* Every response carries `X-Request-ID` (echoed or generated) and
  `X-Bouncer-ms` (server-side ms) — quote the request id in bug reports.
