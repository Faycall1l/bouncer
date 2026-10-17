# eval/reports (T389+T578)

Machine-generated eval/bench output lands here:

| artifact | producer |
| --- | --- |
| `zero-shot.json` | `eval/eval_gatekeeper.py` (`--limit`, `--model` T576) |
| `latest.json` | pointer copy of the newest `eval_gatekeeper.py` report + `_source`/`_generated_at` provenance (T686) |
| `i18n.json` | `eval/eval_i18n.py` (T509) |
| `breaker.json` | `eval/breaker_sim.py` (T571) |
| `pool.json` | `eval/bench_pool.py` (T572) |
| `stub-latency.json`, `questions.json`, `batch-sweep.json`, `bench-audit.jsonl` | other `eval/bench_*.py` |

All ignored by git — regenerate with `eval/*.py`. Committed benchmark tables live
in `BENCHMARKS.md`, not here.
