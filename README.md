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
| `E_MODEL` | inference failed twice → escalated | 200 + action=escalate |
| 429/413 | rate limited / body too long | as numbered |

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
bouncer serve  # API on :8000
bouncer demo   # Gradio UI
```

## Fine-tune (Kaggle 2xT4, 4-5h)

1. `python data/synth_rules.py --n 12000 --out data/gatekeeper-12k.jsonl` (needs `OPENAI_BASE_URL`+key, or `--template-only`)
2. Upload `notebooks/finetune_kaggle.py` to Kaggle, run
3. Pushes to `YOUR_HF/gatekeeper-laya-421m` + eval table in README

See `data/README.md` for dataset spec, `notebooks/README.md` for RLCD loop.

## Docs

* [Rule-writing guide](docs/rule-guide.md) · [Threshold tuning](docs/thresholds.md)
* [Architecture](docs/architecture.md) · [API reference](docs/api.md)
* [Adapters](src/gatekeeper/adapters/README.md) · [Benchmarks](BENCHMARKS.md)

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
