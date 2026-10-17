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
What the fine-tune is expected to change — and what it cannot — is spelled out
in `docs/drafts/finetune-run-impact.md` (T665 draft, unmeasured until the run).

## Stub overhead (T385, local CPU, no weights; table refreshed T753)

`python eval/bench_stub.py 200` → **p50 0.08ms, p95 0.11ms** per `moderate()`
(stub router: measures engine overhead — normalize, gates, cache, audit write).

`python eval/bench_questions.py` → 1-question vs 5-question payloads identical
(<0.01ms): question count costs nothing until a real model runs.

`python eval/bench_batch.py` (unique messages, cold cache per combo; re-run
T753 2026-10-17, Apple-silicon laptop CPU — the old rows dated from T384):

| batch | chunk 1 | chunk 4 | chunk 8 | chunk 16 |
|---|---|---|---|---|
| 1 | 9.3 (cold start) | 0.3 | 0.3 | 0.2 |
| 4 | 0.8 | 1.0 | 1.0 | 0.7 |
| 8 | 1.8 | 1.9 | 1.5 | 1.5 |
| 16 | 3.1 | 2.9 | 2.9 | 2.9 |

~0.2ms/message stub overhead, linear in batch size; chunk size is irrelevant
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

## Warm-pool latency (T751)

`eval/bench_warm.py` splits the number everyone actually pays into the two
halves that matter:

* **COLD** — first `pool.get()`: checkpoint load included, timed once.
* **WARM** — N × (`pool.get()` hit + `moderate()`): p50/p95, lookup cost
  included, exactly what a serve request pays. `creates==1` and `hits==n+1`
  in the report's `pool` block prove the warm path was the one measured
  (N loop calls + the cache replay below).
* **CACHE** — one replay of warm message 0 (identical rules): the TTL
  cache serves the decision without waking the router. `cache_hit_ms` is
  that call's latency; `cache_hit: true` is the receipt that it really
  came from the cache (T752).

```bash
python eval/bench_warm.py --n 50        # real weights required
python eval/bench_warm.py --stub --json # mechanics only
```

Real mode without weights exits 1 (`E_WARM`) and writes **no** report —
this file will not carry warm numbers until they're measured on hardware
that has the checkpoint (`mode: "real"` in `eval/reports/warm.json` is the
receipt). `--stub` reports `mode: "stub"` and times our bookkeeping only,
like the pool/breaker benches above.

## Regex baseline (T210, refreshed T637, local, no weights)

`python eval/baseline_regex.py data/examples.jsonl` → **0.403** on 300 rows.
The file was regenerated 2026-10-17 (T637) through `data/build_dataset.py`:
history windows (2–4 turns) + 30 hard negatives (linkless spam, polite insults)
+ corrected escalate labels — the old hand-rolled file scored 0.480, and the
drop to 0.403 is exactly the hard negatives: regex can't see them.
Dumb links/caps rules still beat uncalibrated zero-shot (0.305) —
exactly why the demo shows both side by side, and why calibration + finetune matter.

## Known numbers (T684)

`python eval/gate.py REPORT --check-docs` reads this table and fails if the
threshold defaults it enforces have drifted from the documented numbers
(T669 release-checklist companion). The `_acc` rows are reference values
(nothing enforces them; they are what the gates are built around):

| metric | value |
|---|---|
| zero_shot_rule_acc | 0.305 |
| regex_baseline_acc | 0.403 |
| regex_floor | 0.403 |
| max_ece | 0.15 |
| max_p95_ms_t4 | 44 |
| pool_speedup_floor | 2.0 |

## Running the gates (T688)

`eval/gate.py` is the single pass/fail runner over any eval report. It reads a
report JSON, applies thresholds, and exits `0` (all applied gates passed),
`1` (a gate failed or the report is structurally unusable), or `2` (input
unreadable/unparseable). A metric absent from the report is **skipped** — a
missing number never counts as a green light.

```bash
python eval/gate.py --all                               # make-style: whole reports dir
python eval/gate.py eval/reports/latest.json           # human verdict
python eval/gate.py REPORT --ci                        # one verdict line, for CI
python eval/gate.py REPORT --against REF.json          # + informational deltas
python eval/gate.py REPORT --check-docs                # + drift check vs table above
python eval/gate.py REPORT --against REF --changelog   # + dated diff into CHANGELOG
```

Report kinds are detected by shape and gated by family:

| report shape | family | what is checked |
|---|---|---|
| `rule_acc` (or baseline `acc`) | eval | `rule_acc >= 0.403`, `ECE <= 0.15`, `p95 <= 44ms`, abstention in (0, 0.3], worst per-rule >= 0.3 |
| `per_lang` (eval_i18n.py) | i18n | `errors == 0` |
| `tripped`/`closed` (breaker_sim.py) | breaker | tripped **and** closed both true |
| `speedup`/`thrash` (bench_pool.py) | pool | hits-scenario speedup >= 2x |

Every threshold is a flag (`--min-rule-acc`, `--max-ece`, `--max-p95-ms`,
`--min-abstention`, `--max-abstention`, `--min-per-rule-acc`,
`--per-rule-min-n`, `--min-speedup`), with defaults pinned by the
Known-numbers table above and
drift-checked by `--check-docs`. Reports older than
`--max-report-age-days` (default 14) warn on stderr without changing the
verdict. Regenerate any report by rerunning its producer in `eval/`; the
newest eval report is always at `eval/reports/latest.json` (T686, gitignored).

## Run costs (T666, estimates — not receipts)

| item | cost | notes |
|---|---|---|
| full run | **2×T4, ~4–5h** | Kaggle quota is 30h/week → ≤6 full runs/week, less if you also eval |
| smoke run | 1×GPU, minutes | `--max-samples 50`, 1 epoch (T659) — run it before every full run |
| checkpoint upload | **~1.8GB per push** | 421M params in fp32 safetensors + tokenizer + config |
| HF storage growth | ~1.8GB × every kept revision | one repo, revisions accumulate — prune or branch old runs |
| local dev loop | $0 | everything except the fine-tune runs on CPU with the stub router |

Rough GPU-dollar equivalents if you don't have quota: 2×T4 × 5h ≈ 10 T4-hours;
at common on-demand rates that's a few dollars per run — cheap enough to
iterate, expensive enough to run the smoke path first (T659) and the pre-flight
checks (T656/T657) before burning quota.

## Honest limits (T109, refreshed T407)

* Template bootstrap: 6 message shapes × 3 rule-sets. Zero-shot numbers measure
  transfer to unseen phrasings, not open-world chat.
* Only 3 violation types + ok in v1 labels. Real communities need LLM-distilled rows.
* Base Laya is English-first; non-English routes to multilingual checkpoint (~23/51 usable alone).
* Keep choice questions ≤20 options (256-token head budget; Banking77 lesson).
* Refit temperatures on your own held-out data before trusting probabilities.
* Stub-overhead numbers (T385) measure engine cost only — add your model's
  forward-pass latency (base Laya: ~1000ms CPU, ~33ms T4) for honest totals.
* Regex baseline (0.403 post-T637, was 0.480 pre-hard-negatives) beats zero-shot
  (0.305) on template data by construction: templates are link/caps-shaped.
  It says nothing about open chat.
