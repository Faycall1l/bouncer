# Error codes (T808)

_(Last checked against v0.4.0.)_

Every `E_*` code bouncer can emit → what it means → the fix. Three
surfaces carry them:

* **API** — `4xx/5xx` with `{"detail": {"code": "E_*", "message": ...}}`
  (status per row; 422 unless noted).
* **CLI** — `bouncer: <code>: <message>` on stderr; configuration-class
  failures exit `4` (T787).
* **Tooling** — `eval/` runners and `scripts/` print `E_*: ...` and exit
  non-zero.

Codes are stable; messages may gain detail between releases.

## API

| code | surface | meaning | fix |
|---|---|---|---|
| `E_PRESET` | 422 | preset name unknown, `rules`+`preset` mixed (XOR), neither supplied, or a bad `BOUNCER_DEFAULT_PRESET` (T475) | send exactly one of `rules`/`preset`; list names via `GET /presets` |
| `E_RULES` | 422 | rule-set error without a more specific code | read the message; the specific `E_RULES_*` below usually applies |
| `E_RULES_EMPTY` | 422 | rules dict has no entries | ship at least one rule |
| `E_RULES_ID` | 422 | rule id isn't a ≤24-char `a-z0-9-` slug | slugify the id (T773 caps) |
| `E_RULES_TEXT` | 422 | rule text over 280 chars | shorten the text; the cap is the prompt budget |
| `E_RULES_COUNT` | 422 | more than 12 rule keys | cut the set to ≤12 or split packs |
| `E_RULES_RESERVED` | 422 | id collides with a reserved name (e.g. the `ok` bucket) | rename the rule |
| `E_RULES_SEVERITY` | 422 | severity isn't `low`/`high`, or names an unknown rule | fix the severity map keys |
| `E_CONTEXT` | 422 | more than 20 context items or an item over 8000 chars | trim the history window you send |
| `E_LANG` | 422 | `lang` isn't `[a-z-]{2,16}` (e.g. `en`, `pt-br`) | send a lowercase tag or omit it (auto) |
| `E_MODEL_NAME` | 422 | `model` not in the checkpoint allowlist | pick from `GET /models` / `bouncer models` (T459) |
| `E_TIMEOUT` | 422 | `timeout_s` outside `[0.5, 60]` — validation only: an *expired* budget shows up as escalate/breaker causes, not this code | use a value in range or unset it to inherit `BOUNCER_TIMEOUT` |
| `E_STATE` | 422 | raw `/v1/systemone` `state`/`questions` key over the cap (T775) | shorten the key; the message states the cap |
| `E_BATCH_EMPTY` | 422 | `/predict/batch` got an empty `messages` list | send at least one message |
| `E_CONFIG` | 422 / `ValueError` | bad gate config: thresholds, durations, `BOUNCER_QUESTIONS`, quiet hours | fix the field named in the message |

## Decisions & engine

| code | surface | meaning | fix |
|---|---|---|---|
| `E_MODEL` | `200` + `action=escalate` | inference failed twice (T197) — served, but escalated, never allowed | check the checkpoint/device in server logs; `GET /ready` probes this |
| `E_BOUNCER` | logs / CLI stderr | base code of every `BouncerError` without a more specific subclass | the text after the code names the failing stage |
| `E_INTERNAL` | 500 | unexpected failure, detail deliberately not leaked | read server logs; the rid in the log line matches the response |

## Persistence (CLI)

| code | surface | meaning | fix |
|---|---|---|---|
| `E_SNAPSHOT` | `bouncer snapshot load` → exit 4 | snapshot corrupt or written by an incompatible schema (T431) | restore a known-good snapshot or accept a counter reset |
| `E_VERDICT` | `bouncer adjudicate` → exit 2 | verdict isn't approve or reject (T865) | pass approve or reject exactly |

## Adapters

| code | surface | meaning | fix |
|---|---|---|---|
| `E_ADAPTER` | adapter refuses to start (fail closed, T691) | broken `bouncer.toml` or a missing required token — the message names the file/secret | fix the config or export the env var (see [environment](environment.md)) |
| `E_WEBHOOK` | logged, event not delivered | POST to `BOUNCER_FORWARD_URL` failed | check the URL, `BOUNCER_FORWARD_ALLOW` host (T785), and the target's health |
| `E_SLACK` | event rejected | malformed Slack event body | fix the sender's payload format |

## Tooling (eval / scripts — exit 1)

| code | surface | meaning | fix |
|---|---|---|---|
| `E_WARM` | `eval/bench_warm.py` | real mode requested without weights (laya + checkpoint) | run stub mode, or install the model |
| `E_IMPORT` | `eval/bench_import.py` | a timed import subprocess failed outright — the tail of its stderr follows the code | fix the import error it prints (usually a missing extra) |
| `E_BUDGET` | `eval/bench_import.py --budget-ms` | import p50 over the budget | profile the import path or raise the budget deliberately |
| `E_TAG` | `scripts/check_tag.py` | git tag ≠ `pyproject` version | bump `version` or fix the tag before releasing |
| `E_CHANGELOG` | `scripts/check_changelog.py` | no `## <version>` section in CHANGELOG.md | add the section before tagging |

Terms used here are defined in the [Glossary](glossary.md).
