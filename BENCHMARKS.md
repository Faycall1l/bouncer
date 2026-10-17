# Benchmarks

## Zero-shot base Laya on gatekeeper-chatmix (T108)

Kernel `faycal00/bouncer-eval-zero` (CPU, 200 rows, 1 choice question). COMPLETE.

| metric | value |
|---|---|
| rule_acc | **0.305** (≈ chance — base Laya is near-blind on unseen rule-sets, as its authors warn) |
| gate@0.85 prec | n/a (0 gated — model never confident; honest abstention) |
| p50 latency (CPU) | 1004ms (GPU T4 ref: ~33ms) |
| top confusion | be-kind→ok (73), no-spoiler→ok (32): defaults to "no violation" |
| overconfident errors | 0 |

Takeaway: zero-shot base is a demo, not a product. Fine-tune (`kaggle/train`) is the product.

## Stub overhead (T385, local CPU, no weights)

`python eval/bench_stub.py 200` → **p50 0.08ms, p95 0.11ms** per `moderate()`
(stub router: measures engine overhead — normalize, gates, cache, audit write).

`python eval/bench_questions.py` → 1-question vs 5-question payloads identical
(<0.01ms): question count costs nothing until a real model runs.

`python eval/bench_batch.py` (unique messages, cold cache per combo):

| batch | chunk 1 | chunk 4 | chunk 8 | chunk 16 |
|---|---|---|---|---|
| 1 | 7.0 (cold start) | 0.2 | 0.1 | 0.1 |
| 4 | 0.4 | 0.4 | 0.3 | 0.3 |
| 8 | 0.6 | 0.7 | 0.6 | 0.6 |
| 16 | 1.4 | 1.1 | 1.2 | 1.2 |

~0.08ms/message stub overhead, linear in batch size; chunk size is irrelevant
with a stub router (it matters for real-model padding — see T106/T107).

## i18n wiring (T499, `python eval/eval_i18n.py --json`)

No weights: checks fixtures validate, preset packs match fixture rules, every
question carries the language hint, script detection is right, and routing is
sane — 12/12 rows, 0 schema errors:

| lang | rows | script | auto model |
|---|---|---|---|
| es | 4 | latin | auto (router detects) |
| fr | 4 | latin | auto (router detects) |
| ar | 4 | arabic | multilingual (pinned) |

Latin scripts rely on laya's own auto-routing (english vs multilingual);
arabic is pinned to `multilingual` via `model_for_lang()` because base
detection under-routes it. Accuracy numbers need the finetune + real
checkpoints; this table pins the plumbing, not the quality.

## pool + breaker (T575, `eval/bench_pool.py` / `eval/breaker_sim.py`)

Both use fake 50ms router builds / injected failures — they time our
bookkeeping, not model inference.

**Pool** (`--max-n 2 --requests 10`, 2 devices): pooled 0.10s vs rebuild-
every-time 0.56s → **5.4×** (hits=8, creates=2, evictions=0). With 3 devices
in 2 slots it thrashes: 0 hits, 10 creates, 8 evictions, speedup ≈ 1.0.
That's the whole point of the knob — `BOUNCER_POOL_MAX` must cover every
checkpoint your traffic actually reaches, or you pay the load every request
(mirrors laya's own `max_loaded` docstring).

**Breaker** (`--storm 3 --cool 0.2`): 3 failing moderations (6 predict
calls — one retry each) trip the breaker; the 4th moderation never touches
the model (`cause=breaker-open`, calls stay at 6). After the 0.2s cooldown
a half-open probe reaches a healthy router and the breaker closes
(`cause=ok`). Trip threshold and cooldown are `breaker_n` / `breaker_cool_s`
in `GateConfig`; `BOUNCER_BREAKER=off` disables it entirely.

Honest limit: these reports pin control-flow behavior, not throughput under
real weights. The real numbers need the finetune + checkpoints; run the
scripts yourself — they're deterministic given the flags.

## Regex baseline (T210, local, no weights)

`python eval/baseline_regex.py data/examples.jsonl` → **0.480** on 300 rows.
Dumb links/caps rules beat uncalibrated zero-shot (0.305) on template data —
exactly why the demo shows both side by side, and why calibration + finetune matter.

## Honest limits (T109, refreshed T407)

* Template bootstrap: 6 message shapes × 3 rule-sets. Zero-shot numbers measure
  transfer to unseen phrasings, not open-world chat.
* Only 3 violation types + ok in v1 labels. Real communities need LLM-distilled rows.
* Base Laya is English-first; non-English routes to multilingual checkpoint (~23/51 usable alone).
* Keep choice questions ≤20 options (256-token head budget; Banking77 lesson).
* Refit temperatures on your own held-out data before trusting probabilities.
* Stub-overhead numbers (T385) measure engine cost only — add your model's
  forward-pass latency (base Laya: ~1000ms CPU, ~33ms T4) for honest totals.
* Regex baseline (0.48) beats zero-shot (0.305) on template data by construction:
  templates are link/caps-shaped. It says nothing about open chat.
