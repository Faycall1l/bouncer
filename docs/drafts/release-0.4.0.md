# Release notes: v0.4.0 (T812/T817, DRAFT)

200 boxes (T631–T830) across eval gates, adapters, packaging, CI/CD,
performance, security & ops, the docs site, and the 0.4.0 release itself.
Still no model changes — same zero-shot behavior, far better operations,
surface, and docs around it.

Highlights for users:

* **Eval gates**: `eval/gate.py` is the single pass/fail runner over every
  eval/bench report — exit-code contract 0/1/2, one-line `--ci` verdict,
  threshold flags (regex floor 0.403, ECE 0.15, p95 44ms, abstention band,
  pool 2× speedup, per-bench perf budgets), `--against` deltas, and
  `--check-docs` drift-checking against the BENCHMARKS Known-numbers table.
  CI runs it on a freshly generated weightless report set on every push.
* **Platform adapters**: Discord/Twitch/Telegram/Matrix/Mattermost/Zulip
  bots plus Slack-verified webhooks — matrix-tested against stubs,
  fail-closed startup with coded `E_ADAPTER` faults, and destructive chat
  actions opt-in only (`BOUNCER_TG_DELETE`, `BOUNCER_MX_REDACT`,
  `BOUNCER_MM_DELETE`, `BOUNCER_ZL_DELETE`, `BOUNCER_DRY_RUN=1`).
* **Packaging**: `bouncer` console script, clean wheel/sdist, optional
  `server`/`demo`/`adapters`/`finetune` dep groups, Dockerfile +
  docker-compose (non-root, OCI labels, start-time self-test), `py.typed`,
  and `bouncer doctor` for env/dep/route self-diagnosis. Core import stays
  weightless — no numpy/laya hard dep.
* **CI/CD**: pytest + ruff across python 3.10–3.13, wheel + SBOM attached
  to GitHub Releases on tags, tag-vs-version guard, secret scan, coverage
  artifact, nightly stub suite, release-notes check, PR/issue templates.
* **Performance**: warm-pool and cache-hit latency receipts, import budget
  < 200ms (lazy gradio), batch-size sweep, coalescing metric in `/stats`,
  audit write batching, fixed bench-report schema gated by perf budgets.
  All numbers dated, all limits honest — before/after-finetune columns
  stay empty until a real run.
* **Security & ops**: threat-model/runbook/SECURITY doc set, key-rotation
  window (`BOUNCER_KEY_OLD`), proxy-pinned rate keys
  (`BOUNCER_TRUSTED_PROXY`), forwarder SSRF pin (`BOUNCER_FORWARD_ALLOW`),
  review queue `0600` with bounded raw keep.
* **Docs site**: mkdocs-material site (nav == file set) with getting-
  started, cookbook, environment-variable table, error-code index, three
  runnable examples, and test-enforced link/heading/freshness lints.

Bugs found by the release tests themselves:

* The T781 audit job ran `pip-audit -r pyproject.toml` — `-r` reads
  requirements format, not TOML, so the job errored on line 1 every run
  since introduction; the workflow now extracts the declared deps first
  (T814).
* `tomllib` is stdlib only from python 3.11, so the whole 3.10 matrix leg
  cascaded-failed until the `tomli>=2.0; python_version < '3.11'` backport
  dep + import shims landed (T814).
* A 2000-deep JSON pack raises `RecursionError` on ≤3.11/3.13 — the
  pack-load guard only caught `OSError, ValueError`, so the CLI
  tracebacked instead of exiting 4 (T814).
* `eval_gatekeeper.py` wrote its `latest.json` pointer to a hardcoded
  `eval/reports/` even when `--out` pointed elsewhere — every pytest run
  left a fake n=1 stub that failed `gate.py --all` on the next invocation
  (T815).
* macOS case-insensitive APFS hid a PR-template path-case mismatch that
  Linux CI caught; the bench_warm refusal test silently depended on laya
  being absent (T814, both test-side).

Upgrade notes:

* New required-or-default behavior: none — existing configs keep working.
  New optional dep groups (`.[server]`, `.[demo]`, `.[adapters]`,
  `.[finetune]`) only if you want those surfaces.
* On python < 3.11, `tomli>=2.0` is now installed automatically (core
  dep with an environment marker).
* Destructive chat actions in the new adapters are off unless you set
  their opt-in flags; `BOUNCER_DRY_RUN=1` previews instead of posting.
* `__version__` / package version: `0.4.0`.
* 413 tests green without weights; `ruff check .` green; CI green on all
  four matrix legs.

Tag: `v0.4.0`.

## Verification

* `pytest -q`: **412 passed, 1 warning** (2026-10-18, weightless env,
  macOS arm64) — T812.
* `ruff check .`: **clean** (repo-wide, line-length 100) — T813.
* `ci workflow` (release commit): **green** — red for 30+ runs on five
  root causes, all fixed in this release tree: `tomllib` is stdlib only
  from 3.11 so the whole py3.10 matrix leg cascaded (added
  `tomli>=2.0; python_version < '3.11'` marker dep + import shims at all
  8 sites), the PR-template test read `PULL_REQUEST_TEMPLATE.md` while
  git tracks lowercase `pull_request_template.md` (case-insensitive APFS
  hid it), the bench_warm refusal test assumed "no laya anywhere" but CI
  installs the package *with* laya so real mode actually ran (now forced
  hermetically via a raising-laya shadow), a 2000-deep JSON pack raises
  `RecursionError` on ≤3.11/3.13 which the pack-load guard didn't catch
  (now `OSError, ValueError, RecursionError` → exit 4), and the T781
  `audit` job ran `pip-audit -r pyproject.toml` — `-r` reads requirements
  format, not TOML, so it errored on line 1 every run since T781 (now
  extracts the declared core deps to `reqs.txt` first; local pip-audit
  over the extracted deps: no known vulnerabilities) — T814.
* `eval/gate.py --all --ci`: **PASS (9 reports gated)** — refreshed the
  full weightless set (pool/breaker/stub/warm/stats/import/questions/
  batch + i18n) and every gate holds; `--check-docs` shows zero drift
  between the Known-numbers table and the enforced defaults. Fixed the
  leak that used to poison local runs: `eval_gatekeeper.py` wrote its
  `latest.json` pointer to a hardcoded `eval/reports/` even when `--out`
  pointed at tmp, so every pytest run left a fake n=1 stub there that
  failed `gate.py --all` on the next invocation (pointer now lands
  beside `--out`; the i18n sweep test passes `--out` too). Regex baseline
  re-measured: **0.403** on `data/examples.jsonl`, exactly the documented
  floor. Known-numbers table gained a status column (T815):
  `zero_shot_rule_acc` 0.305 marked **STALE** (needs laya + the gitignored
  12k dataset — unrefreshable in a weightless env; last measured on the
  T108 CPU kernel), the threshold rows name the flag enforcing them —
  T815.

(Highlights / bugs / upgrade notes land with T817.)
