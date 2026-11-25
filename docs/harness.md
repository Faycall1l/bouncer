# Decision and evaluation harness

_(Last checked against v0.5.0.)_

See the [glossary](glossary.md). This harness is explicit and fail-closed. It
does not publish model accuracy or latency evidence; it publishes decisions,
policies, and traces.

## Eval API (T1234-T1240)

```python
from eval.harness import build_manifest, run_pairs, compute_metrics, stability_gate

manifest = build_manifest("data/fixture.jsonl", dataset_id="fixture", split="dev",
                          policy=policy, config=config, git_sha="<git-sha>", seed=7)
specs = load_specs("data/fixture.jsonl", dataset="fixture", split="dev",
                   policy=policy, config=config, variants=("identity",))
batch = run_pairs(specs, base=base_binding, candidate=candidate_binding,
                  manifest_hash=manifest.fingerprint(), variants=("identity",))
metrics = compute_metrics(batch, specs, MetricsConfig(ece_bins=5, gate_min_n=10))
evidence = PairedEvidence(manifest=manifest, batch=batch, metrics=metrics,
                          bootstrap=..., sign_test=...)
assert parity_gate(evidence, specs, variants=("identity",)).ok
assert evidence_gate(evidence, min_boot=500, min_ci=0.95).ok
assert stability_gate(*run_twice(...), manifest_hash=manifest.fingerprint()).verdict.ok
```

The CLI is explicit-only: every important value is a required flag.

```sh
python eval/harness/cli.py manifest --data data/fixture.jsonl --dataset fixture --split dev \
  --policy eval/harness/fixtures/policy.json --config eval/harness/fixtures/config.json \
  --git-sha "$(git rev-parse HEAD)" --seed 7 --out eval/reports/fixture-manifest.json
```

## Decision API (T1241-T1244)

```python
from eval.harness import Decision, DecisionConfig, DecisionPolicy, run_scenarios

policy = DecisionPolicy(name="prod", outcomes=("allow", "delete", "flag", "escalate", "abstain"),
                        sources=("model", "cache", "fastpath", "empty", "breaker", "fallback", "coalesced"))
cfg = DecisionConfig(name="prod-gate", policy=policy, gate=GateConfig())
d = moderate_decision(cfg, message, rules, router=router, instance_id="banned_ads")
assert d.outcome in policy.outcomes and d.source in policy.sources
```

Closed outcome enum (excluding reserved failures): `allow`, `delete`, `flag`,
`escalate`, `abstain`. Closed source enum: `model`, `cache`, `fastpath`,
`empty`, `breaker`, `fallback`, `coalesced`. Missing cause, source, action, or
reason is an error, never a default. `run_scenarios()` and
`compare_runs()` provide the explicit scenario and policy-comparison report.

## Fallback taxonomy (T1245-T1248)

| Path | Source | Typed counter | Cause |
|---|---|---|---|
| Fastpath | `fastpath` | `source_counts()["fastpath"]` | `fastpath: no links` |
| Cache | `cache` | `source_counts()["cache"]` | stored result cause |
| TTL | cache | `CACHE.stats()["ttl_expired"]` | typed expiry counter |
| Breaker open/half-open/closed | breaker | `breaker_counts()` | `breaker-open`, `needs-human` |
| Engine fallback/batch fallback | `fallback` | `source_counts()["fallback"]` | `fallback` |
| Empty message | `empty` | `source_counts()["empty"]` | `empty message` |
| Model | `model` | `source_counts()["model"]` | typed cause strings |

Hard-to-undo edits and model calls use explicit config and never invent
fallbacks. `GateConfig` and `DecisionConfig` validate and serialize all knobs.

## Receipts

- T1231 research notes: `reports/Jev System One research.md`
- T1232 README rewrite: `README.md`
- T1233 generated figures: `docs/assets/decision-trace.gif`, `docs/assets/gate-precedence.svg`
- T1234-T1235 typed eval records/manifests: `eval/harness/schema.py`, `eval/harness/manifest.py`
- T1236-T1237 paired runner/metrics: `eval/harness/runner.py`, `eval/harness/metrics.py`
- T1238-T1239 inference/gates: `eval/harness/stats.py`, `eval/harness/gates.py`
- T1240 stability/CLI: `eval/harness/stability.py`, `eval/harness/cli.py`
- T1241-T1244 decision harness: `eval/harness/decision.py`
- T1245-T1248 typed fallbacks: `src/gatekeeper/stats.py`, `src/gatekeeper/cache.py`, `src/gatekeeper/__init__.py`, `src/gatekeeper/config.py`
- T1249 this contract.
