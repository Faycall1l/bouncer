# Release checklist (T669, updated at T999)

_(Last checked against v0.4.0.)_

Run before every version tag. The 0.3.0 release did these steps by hand; 0.4.0
(P43) follows this list literally, and 0.5.0 (P53) does too — with the
newer gates T999 added below.

- [ ] `pytest -q` green and `ruff check .` clean on the release commit
- [ ] version bumped in **both** `src/gatekeeper/__init__.py` and `pyproject.toml`
      (a consistency test fails the suite if they drift)
- [ ] CHANGELOG entry dated, with a release-notes draft in `docs/drafts/`
- [ ] **accuracy numbers refreshed** (T669): `BENCHMARKS.md`, the README
      honest-limits table, and the FAQ checkpoint entry carry the latest
      *measured* numbers from an `eval_gatekeeper.py` report — never vibes.
      If the fine-tune ran: `eval/compare_models.py` on base-vs-ft reports,
      update per `docs/drafts/finetune-run-impact.md`. If it didn't run:
      say so explicitly — stale numbers must not silently survive a release.
- [ ] docs-consistency tests still pass (they fail on README-vs-CLI drift)
- [ ] **the newer gates pass** (T999):
  * `python eval/bench_metrics.py` then `python eval/gate.py --all --ci` —
    the metrics report (T948) gates the `/metrics` exposition itself:
    every sample line parses, each family carries exactly one HELP +
    one TYPE, and the scrape p50 stays under the gate's threshold. It
    runs in-process (TestClient), so no server needs to be up.
  * `python eval/eval_i18n.py` (T898) — script detection must land every
    fixture on the checkpoint its language deserves. Weightless and
    deterministic; `gate.py` picks its report up by kind, so the
    `--all` verdict above covers it once the report exists.
  * Regenerate the weightless report set before trusting any verdict —
    `gate.py --all` gates what's on disk. CI regenerates with T739's
    eight runners every run: `eval/bench_pool.py`,
    `eval/breaker_sim.py`, `eval/bench_stub.py 200`,
    `eval/bench_warm.py --stub --n 50`, `eval/bench_stats.py`,
    `eval/bench_import.py --n 3`, `eval/bench_questions.py`,
    `eval/bench_batch.py`.
- [ ] tagged and pushed: `git tag -a vX.Y.Z -m "..." && git push origin HEAD --tags`
