# Contributing (T145, extended T804, refreshed T968)

## Repo layout

* `src/gatekeeper/` — the package (src-layout): the decide pipeline
  (`__init__.py`), `rules`, `presets`, `config`, `serve`, `cli`,
  `demo_app`, `explain`, `cache`, `review`, `stats`, `strikes`, ...
* `src/gatekeeper/adapters/` — one file per chat platform (telegram,
  matrix, mattermost, zulip, discord, twitch, webhooks) plus
  `common.py`, the shared helper owner (see *Shared-helper
  conventions*), and `README.md` with the env-var table (CI-gated since
  T710).
* `tests/` — one `test_pNN.py` file per TODO batch; a box's receipt
  tests live in the file for its phase. `tests/conftest.py` carries the
  suite wall-time budget (T967). Unit tests never need weights — the
  suite stubs the router.
* `eval/` — benches (`bench_*.py`) and gates (`gate.py`, `eval_*.py`).
  Run them as programs from the CLI or CI, never import them from unit
  tests; their reports land in `eval/reports/` (gitignored).
* `data/` — synthesis (`synth_rules.py`) plus the committed example
  datasets (`examples*.jsonl` are the only jsonl files git tracks).
* `docs/` — the mkdocs site; `docs/RELEASE-CHECKLIST.md` gates releases.
* `kaggle/` — single-file training/eval kernels. They pip-install their
  deps in-process before importing them; that contract is why `E402` is
  scoped-ignored for `kaggle/**` alone (T959). Never restructure a
  kernel into functions — the artifacts are untestable off-GPU.
* `app/` — the HF Space entry (frontmatter-carrying `app.py`, excluded
  from ruff since T388); `scripts/` and `notebooks/` are one-off tooling.

## Boxes workflow

* Work comes in TODO batches (~200 boxes with `T###` ids, e.g.
  P42 = T791–T810). One TODO box = one commit + push. Keep diffs tiny
  and green.
* Tick a box (`- [x]`) only when its work is done, in the same commit as
  the work — the tick and the change land together. Commit messages start
  with the box id: `T804 docs: ...`.
* Receipts (evidence a box was really done) live in commit messages,
  tests, and docs — never as prose inside TODO.md. Every ticked box's
  `T###` must appear literally in a non-TODO file. If a box's text went
  stale, correct the box text in the same commit. A "design" box may be
  delivered as a working implementation (a superset of the ask).

## Verify gate

* `./verify.sh "T### message"` is the gate: full `pytest -q` green AND
  `ruff check .` clean (T402+T745: repo-wide, not a src/tests subset),
  then commit + push. It stops at the first red. Never push red — fix
  forward instead. No backticks in the message (the script commits it).
* Pipe exit codes through (`tail` swallows them); fail the chain on red.
* `docs/` touched → also run a strict `mkdocs build` before pushing.
* Tests run without weights (stub routers). Weight-needing scripts live in
  `eval/` + Kaggle kernels, never in unit tests.

## Shared-helper conventions (T951–T958)

* `adapters/common.py` owns the shared surface: `require_env`,
  `load_rules`, `load_config`/`cfg_get`, `install_shutdown`,
  `as_user_id`, `Health`, `rate_cap_from_env`, `command_reply`,
  `parse_command`, `moderate_action`, `adapter_lang`, `redact`.
* Pollers ride the common startup plumbing end to end; the four simple
  pollers carry the command table through `moderate_action` (T953), the
  three direct-call surfaces (discord, twitch, webhooks) spell
  `adapter_lang` out themselves.
* An adapter that defines a name common owns must import that name from
  `common` — never re-implement it. The one documented split: discord's
  strict T705 parser answers `None` for non-commands (its docstring
  says so; it is not a copy of the shared first-word dance).
* `test_t958_adapter_parity_matrix_shared_helpers` enforces the
  adapter × helper matrix; a new adapter gets a row in it.

## Code style

* ruff over the whole repo (`ruff check .`), `line-length = 100`
  (pyproject `[tool.ruff]`); the lint set is pycodestyle `E`/`W` families
  on top of ruff's defaults (`[tool.ruff.lint]`, T959). The narrow
  src/tests lint wording is dead since T745. Violations get fixed, never
  `# noqa`'d.
* Every new CLI flag or positional carries `help=` text — the T965
  sweep fails the suite on an undocumented action.
* A test over 1s needs a written entry in `tests/conftest.py`
  `SLOW_JUSTIFIED` (T967); the budget hook fails the session otherwise.
* OpenAPI schema changes are deliberate re-pins: T964's digest test
  prints the one-liner that regenerates the pinned hash.
* Every non-obvious change carries the box id that made it: `# T###` in
  code, `(T###)` in doc headings; tests for a batch live in
  `tests/test_pNN.py` (one file per batch).
* Env vars read from the environment (`BOUNCER_*`, platform tokens) must
  be documented in the same commit: core/CLI vars in the docs env table,
  adapters in `src/gatekeeper/adapters/README.md` (CI gate since T710).
* Numbers are receipts: benchmark or accuracy figures come from real eval
  reports (BENCHMARKS.md) — never invented, never vibes.
* No secrets in code — tokens via env only.
* Rule packs: add to `presets.py` + fixtures + docs catalogue.
* Releases follow `docs/RELEASE-CHECKLIST.md` (T669): accuracy numbers must be
  refreshed from a measured eval report before any tag — never vibes.
* Branch protection (T745 — GitHub settings, repo files can't flip it):
  require the `ci` status checks (`lint`, `test` matrix, `weightless`,
  `eval-gate`) before merge to `main`, and block force-pushes. Reviews
  route through the maintainer via `.github/CODEOWNERS`.
