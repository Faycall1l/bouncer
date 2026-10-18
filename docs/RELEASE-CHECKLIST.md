# Release checklist (T669)

_(Last checked against v0.3.0.)_

Run before every version tag. The 0.3.0 release did these steps by hand; 0.4.0
(P43) follows this list literally.

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
- [ ] tagged and pushed: `git tag -a vX.Y.Z -m "..." && git push origin HEAD --tags`
