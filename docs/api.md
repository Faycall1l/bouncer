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
