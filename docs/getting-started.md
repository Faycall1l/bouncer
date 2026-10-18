# Getting started (T793)

_(Last checked against v0.4.0.)_

Install → first decision → serve, in that order. Every command here is
verbatim; where a value depends on your checkpoint, this page says so
instead of inventing one (measured numbers live in
[BENCHMARKS.md](https://github.com/Faycall1l/bouncer/blob/main/BENCHMARKS.md)).

## 1. Install

```bash
pip install -e ".[server,demo]"   # from a checkout: core + API server + demo UI
```

* Python **3.10–3.13** (`requires-python >= 3.10`; the CI matrix tests all four).
* Extras: `server` (fastapi + uvicorn, what `bouncer serve` needs), `demo`
  (gradio), `dev` (pytest, ruff, pytest-cov), `adapters`, `finetune` — see the
  README for the full list.
* No training, no data: bouncer is zero-shot. The first run downloads or loads
  the System One checkpoint you pick (`bouncer models` lists what's
  configured).

## 2. First decision

```bash
bouncer check "you all suck" --preset gaming
```

Default output is one line: `ACTION: reason`, where the reason cites the rule
that fired:

```text
ACTION: violates 'rule-id' — <your rule text> (conf 0.NN)
```

`ACTION` is one of `allow`, `flag`, `delete`, `escalate` — and the **exit
code
makes it machine-usable** in scripts:

| exit | meaning |
|---|---|
| 0 | allow |
| 2 | delete **or** flag (and argparse usage errors) |
| 3 | escalate |
| 4 | configuration error (bad preset, bad rules file, ...) |

Useful flags: `--quiet` prints just the action, `--json` the full decision
object, `--rules PATH` your own rule pack instead of a preset, and split gates
`--allow-threshold` / `--delete-threshold` to tune the two bars independently
(`--threshold` sets both).

!!! note "Why no confidence numbers on this page"
    Confidences are your checkpoint's output, not a constant of the
    format string. The measured, real-weights numbers are receipts in
    BENCHMARKS.md — docs don't restate them.

## 3. Serve

```bash
export BOUNCER_KEY="$(python -c 'import secrets; print(secrets.token_hex(16))')"
bouncer serve          # API on :8000
```

With `BOUNCER_KEY` set, every `POST` requires `X-API-Key` (wrong key → 401,
constant-time compare). Without it the API is open — fine on localhost,
set a key for anything else. The same decision, over HTTP:

```bash
curl -sS -X POST http://localhost:8000/predict \
  -H "content-type: application/json" \
  -H "x-api-key: $BOUNCER_KEY" \
  -d '{"message": "you all suck", "preset": "gaming"}'
```

The response carries the decision itself (fields, not sample values — see
[api.md](api.md) for the full contract):

| field | meaning |
|---|---|
| `action` | `allow` / `flag` / `delete` / `escalate` |
| `rule` | id of the fired rule (`ok` when none fired) |
| `confidence` | your checkpoint's score for that rule |
| `reason` | one-line human explanation citing rule text |
| `latency_ms` | server-side decision time |
| `strikes` | the user's strike count, when a `user_id` was sent |

Errors are always structured: `{"detail": {"code": "E_*", "message": ...}}`
(`E_PRESET`, `E_RULES_*`, `E_CONTEXT`, `E_STATE`, ... — meaning and fix for
every code live in the [error-code index](error-codes.md). Rate limiting
is 60 requests/min per IP; 429s carry `Retry-After: 60`.

Health checks for load balancers: `GET /health`, `GET /ready` (checks the
model, not just the process), `GET /version`.

## Next

* [Example scripts](examples/01_in_process.py) — three copy-paste starting
  points in `docs/examples/`: in-process, API client, custom rule pack
* [Demo script](demo-script.md) — the Gradio UI tour
* [Rules guide](rule-guide.md) — writing rules that behave
* [Runbook](runbook.md) — backup, restore, rotate, drain
* [Security](SECURITY.md) / [Threat model](threat-model.md) — what's enforced
  and how

Terms used here are defined in the [Glossary](glossary.md).
