# 🛡️ bouncer — programmable live-chat mod in one 30ms pass

[![ci](https://github.com/Faycall1l/bouncer/actions/workflows/ci.yml/badge.svg)](https://github.com/Faycall1l/bouncer/actions/workflows/ci.yml)
![license](https://img.shields.io/badge/license-Apache--2.0-green)
![python](https://img.shields.io/badge/python-3.10%2B-blue)

Per-server rules in, typed decisions out. No retrain per community.

Built on [Laya](https://github.com/NandhaKishorM/laya) (Apache-2.0 System One model, Jev-compatible). Classical classifiers die here: rule-sets change every server, every message.

```python
from gatekeeper import moderate
res = moderate(
    message="FREE NITRO CLICK HERE!!!",
    rules={"no-spam": "no ads, links, self-promo", "be-kind": "no insults"},
)
# -> {'action': 'delete', 'rule': 'no-spam', 'confidence': 0.94}
```

One `Router.predict()` answers 5 questions in parallel:

| qid | type | what |
|---|---|---|
| `rule` | `choice` | which rule violated? criteria = YOUR rules + `ok` (dynamic K=3-12) |
| `harm` | `score` | `[safe, sus, harmful]` |
| `hype` | `score` | `[dead, chill, hyped]` |
| `jailbreak` | `noul` | prompt-injection / ignore-instructions? |
| `escalate` | `noul` | needs human? (used for gating) |

Gate: `auto-delete` if harm≥sus @ conf≥0.85, `allow` if ok @ conf≥0.85, else `escalate` to human/LLM.

## Why not classical

* Fixed-class BERT needs retrain per rule-set. Here K and rule text vary per row — shared scorer head, zero retrain.
* 3 tasks, 1 forward pass (~33ms T4). Classical = 3 models.
* Calibrated confidence → automate top-50% @ 90%+ precision, escalate rest. Classical softmax lies.

## Cost (T148)

| approach | per 1k messages | latency |
|---|---|---|
| bouncer (self-hosted Laya) | ~$0 marginal | ~33ms, 5 questions, 1 pass |
| LLM judge (5 calls) | ~$0.50–2.50 | seconds |
| regex | $0 | instant, blind to phrasing |

## Error codes (T198)

| code | meaning | HTTP |
|---|---|---|
| `E_RULES_EMPTY/ID/TEXT/COUNT/RESERVED` | bad rule-set (see message) | 422 |
| `E_RULES_SEVERITY` | severity not low/high or on unknown rule | 422 |
| `E_CONFIG` | bad gate config (thresholds, timeouts, quiet_hours) | 422 / ValueError |
| `E_WEBHOOK` | event forward POST failed | exception |
| `E_SLACK` | malformed Slack event body | exception |
| `E_INTERNAL` | unexpected server failure (no detail leaked) | 500 |
| `E_MODEL` | inference failed twice → escalated | 200 + action=escalate |
| 429/413 | rate limited / body too long | as numbered |

Batch: `POST /predict/batch` takes ≤32 messages (413 beyond), each ≤8000 chars;
context lists cap at 20 items (422 beyond). Empty batches are 422. 429s carry
`Retry-After: 60`.

## Quickstart (30 seconds, zero-shot — no training)

```bash
pip install -e .
python -c "
from gatekeeper import moderate, get_preset
print(moderate('FREE NITRO http://x.gg', get_preset('gaming')))
"
# bouncer check "you all suck" --preset gaming
# bouncer serve  # API on :8000
```

```bash
pip install -e ".[server,demo]"
bouncer check "you all suck" --preset gaming
bouncer check "you all suck" --preset gaming --allow-threshold 0.9 --delete-threshold 0.7
bouncer serve  # API on :8000
bouncer demo   # Gradio UI
bouncer watch --preset gaming < chat.log        # live tail, colored verdicts
bouncer review                                  # queued flags/escalations
bouncer snapshot save snap.json                 # counters + strikes (T606)
bouncer snapshot load snap.json
bouncer export --out audit.csv                  # audit log -> CSV
bouncer models; bouncer presets                 # checkpoints, rule-packs
```

Split gates: `--allow-threshold` / `--delete-threshold` (and the same JSON keys
on `POST /predict` + `/predict/batch`) tune the two bars independently;
bare `--threshold` sets both. Higher allow = fewer auto-allows, more escalations.

## Config file (T709+T727)

Adapters and `bouncer doctor` read an optional `bouncer.toml` (stdlib
`tomllib`) from the working directory — override the path with
`BOUNCER_CONFIG`. Precedence is always **env var > file > default**: a
missing file is fine (defaults), a broken one fails closed with `E_ADAPTER`
naming the file. The full annotated example lives in
[`src/gatekeeper/adapters/README.md`](src/gatekeeper/adapters/README.md).

## Router pools (T592)

Routers (one per checkpoint × device) are expensive to build, so bouncer keeps an
LRU pool keyed by constructor kwargs:

* `BOUNCER_POOL_MAX` (default `2`) — slots in the pool. Size it to every
  checkpoint your traffic actually reaches; fewer slots than hot checkpoints means
  an eviction storm where every request pays a full reload (`eval/bench_pool.py`
  demonstrates both: 5.4× speedup with hits, ~1× thrashing without).
* `BOUNCER_DEVICE` (e.g. `cuda`, `mps`, `cpu`) — default device for pool builds.
* `BOUNCER_MODEL_DIR` (e.g. `/kaggle/working/bouncer-421m`) — load a local
  fine-tuned checkpoint for every request: beats language routing, while an
  explicit `model=` pin still wins. This is how a Kaggle-trained model (P35)
  becomes the engine's default (T663); pool builds honor it too (T664).
* `model=` — pin a checkpoint per request: `moderate(msg, rules, model="multilingual")`,
  `POST /predict {"model": "typed-decisions"}`, `bouncer check --model english`.
  `None`/`auto` routes by language hint: non-latin scripts (ar/zh/ru/fa/ur/he) pin
  `multilingual`, latin rides laya's own auto-routing.
* Pool size/hits/evictions appear in `GET /stats`, `GET /ready`, and
  `bouncer models`.

## Presets as rules (T593)

A "preset" is just a named rule-pack (`bouncer presets` lists them with
language tags; `bouncer pack init FILE --preset gaming` writes one out to edit).
Anywhere bouncer takes `rules`, it also takes `preset` — **never both**:

* `bouncer check "msg" --preset study` · `POST /predict {"message": …, "preset": "es"}`
* `GET /presets/{name}` returns the pack for inspection.
* Passing both exits 4 (CLI) / `422 E_PRESET` (API) — packs are single-sourced,
  mixing silently merges nothing.
* `BOUNCER_DEFAULT_PRESET=study` fills the gap server-side: requests with neither
  `rules` nor `preset` use it (bad value → `E_PRESET`).
* Presets carry a language tag (`PRESET_LANG`): choosing `es`/`fr`/`ar` also hints
  the language downstream (reason language, model routing).

## Multilingual (T594)

`lang=` (API field, `--lang` CLI flag, per-line `"lang"` with `watch --json-in`)
hints both the reason language and the model route; omitted (the default) it
infers from the message script (`detect_script()`: latin vs arabic at minimum).
Presets tagged `es`/`fr`/`ar` autofill the hint. Bad hints (not a short lowercase
slug) are rejected with `422 E_LANG`.
Fixtures + wiring check: `data/examples_i18n.jsonl` and `eval/eval_i18n.py`.
Honest limit: base-model accuracy outside English is unmeasured — see
[BENCHMARKS.md](BENCHMARKS.md#honest-limits).

## Circuit breaker (T594)

When the model misbehaves, the breaker stops wasting latency on it:

* `breaker_n` consecutive failures open the breaker; `breaker_cool_s` cooldown
  then allows a half-open trial probe — one success closes it again.
* Open-breaker requests short-circuit to `escalate` with `cause: breaker-open`
  (never silently allow).
* `BOUNCER_BREAKER=off` disables it entirely; trip state shows in `GET /stats`,
  `GET /ready`, and the demo meters.
* `timeout_s` (API field, 0.5–60s; `BOUNCER_TIMEOUT` env) bounds each model call —
  timeouts count toward the failure streak.

## Persistence (T591)

Nothing persists by default — bouncer is in-memory per process. Two opt-in files:

* **Audit log** (`BOUNCER_AUDIT`, default `bouncer-audit.jsonl`): one JSON line per
  decision — timestamp, hashed message (never raw text), action, rule, confidence,
  latency. `bouncer export --out decisions.csv` (also `--format json`, `--since`,
  `--action`, `--limit`) reads it back.
* **Review queue** (`BOUNCER_REVIEW`, default `review-queue.jsonl`): flag/escalate
  rows queued for a human; `bouncer review --since/--rule/--action/--prune` filters
  it, `--clear --yes` empties it. The demo's 🚩 button writes here too.
* **Snapshots**: `bouncer snapshot save snap.json` freezes decision counters +
  per-user strikes; `bouncer snapshot load snap.json` restores them (version-mismatch
  warns, never fails; corrupt files raise `E_SNAPSHOT`). Programmatic equivalent:
  `gatekeeper.stats.save()/load()` writing `BOUNCER_STATS` (default
  `bouncer-stats.json`).

## Fine-tune (Kaggle 2xT4, 4-5h)

1. `python data/synth_rules.py --n 12000 --out data/gatekeeper-12k.jsonl` (needs `OPENAI_BASE_URL`+key, or `--template-only`)
2. Upload `notebooks/finetune_kaggle.py` to Kaggle, run
3. Pushes to `YOUR_HF/gatekeeper-laya-421m` + eval table in README

See `data/README.md` for dataset spec, `notebooks/README.md` for RLCD loop.

## Docs

* [Rule-writing guide](docs/rule-guide.md) · [Threshold tuning](docs/thresholds.md)
* [Architecture](docs/architecture.md) · [API reference](docs/api.md)
  · [Gate precedence](docs/gates.md)
* [Adapters](src/gatekeeper/adapters/README.md) · [Benchmarks](BENCHMARKS.md)
  · [Security](docs/SECURITY.md)

## Honest limits (T144)

Template bootstrap (6 message shapes), 3 violation types in v1, English-first,
≤20 options per question, refit temperatures on your data. Full list:
[BENCHMARKS.md](BENCHMARKS.md#honest-limits-t109).

## Benchmarks (measured, base `laya`)

| split | acc(rule) | gate@0.85 | p50 |
|---|---|---|---|
| gatekeeper 200-row, CPU zero-shot | **0.305** (≈ chance) | 0 gated (honest abstention) | 1004ms CPU / ~33ms T4 ref |
| gatekeeper-test fine-tuned | **target 0.80+** | — | — |

Base is near-blind on unseen rule-sets (Laya's own warning) — the finetune is the
product. Full numbers: [BENCHMARKS.md](BENCHMARKS.md). Be honest — see `eval/`.
