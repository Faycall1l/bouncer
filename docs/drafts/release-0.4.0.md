# Release notes: v0.4.0 (T812/T817, DRAFT)

200 boxes (T631–T830) across eval gates, adapters, packaging, CI/CD,
performance, security & ops, the docs site, and the 0.4.0 release itself.
Still no model changes — same zero-shot behavior, far better operations,
surface, and docs around it.

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
