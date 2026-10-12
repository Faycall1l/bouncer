# API reference (T141)

* `POST /predict` `{message, rules, context?, threshold?, lang?}` → decision + reason.
  Rule errors → 422 with `E_RULES_*` code.
* `POST /predict/batch` `{messages[], rules, threshold?}` → array, order kept.
* `POST /v1/systemone` `{state, questions}` → raw router passthrough (Jev SDKs work).
* `GET /health` model + uptime · `GET /version` · `GET /models` · `GET /stats`
  · `GET /presets` · `GET /metrics` (prometheus text).
* Headers: `X-Request-ID` echo, `X-Bouncer-ms` latency. Optional `X-API-Key`
  when `BOUNCER_KEY` set. 60 req/min/IP.
