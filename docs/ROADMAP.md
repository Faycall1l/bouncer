# Roadmap (T805) — beyond 0.4.0

_(Last checked against v0.4.0.)_

Where bouncer goes after the 0.4.0 line (eval gates, CI hardening,
security work, and this docs site). Plans, not promises: an item leaves
this page when receipts exist for it — the same rule
[BENCHMARKS.md](https://github.com/Faycall1l/bouncer/blob/main/BENCHMARKS.md)
uses.

## Fine-tune results (status: NOT RUN)

* The fine-tune has **not run**. BENCHMARKS.md's "before vs after
  finetune" table keeps its "after" column empty on purpose — only
  `mode:"real"` reports may fill it (T751 rule).
* What is measured today: zero-shot base **0.305** rule accuracy vs the
  **0.403** regex floor. Zero-shot is a demo, not a product; the gap is
  the point of the run.
* Post-0.4.0: execute the `kaggle/train` recipe, file the eval report,
  then — and only then — fill the after-column, refresh the
  known-numbers table, and let `docs/RELEASE-CHECKLIST.md` gate the next
  tag on those refreshed numbers.
* What the run can and cannot change is pre-registered in
  `docs/drafts/finetune-run-impact.md` — unmeasured until the run
  happens, no exceptions.
* The PIPELINE around the run is built and receipted, even though the
  run itself is not (P48, `tests/test_p48.py`): import-safe train script
  with dry-run config validation (T911/T919), resume (T914), provenance
  in every log line (T916), an auto-generated model card (T917), a data
  gate that refuses on bad rows or a hash mismatch before training starts
  (T924), and a ship gate that runs gate.py's FULL thresholds with no
  local overrides (T915/T920).
* Pre-flight without a GPU: `python scripts/ft_smoke.py` chains the dry
  run with the dataset schema check (T926), and the nightly workflow
  runs that same smoke on CPU (T927) — config parse + data validate, no
  weights. Still not a run: these receipts prove the path is testable,
  not that a checkpoint was trained or pushed.

## Plugins (status: planned — design not started)

* Today's extension points are already first-class: rule packs
  (`presets.py` / `bouncer pack init`), platform adapters, webhook
  forwarding, per-request `model=` pinning.
* Direction: stable plugin entry points for (a) custom rule providers,
  (b) action executors beyond allow/flag/delete/escalate, (c) explain
  hooks that can carry platform-specific formatting.
* Nothing here is API. No plugin interface is stable until it ships with
  tests, and nothing in this repo ships without them.

## Versioned docs site

* The deploy workflow already exists behind the `DOCS_DEPLOY` flag
  (T801): flip it once the Pages source is set to "GitHub Actions".
* Then: versioned builds per tag, so the version switcher promised on
  [Version notes](versions.md) actually appears — each entry resolving
  to its delta section.

## How items graduate

* Planned → shipped = receipts: a measured report or a merged test file.
* Planned → cut = an honest line written here, never a silent deletion.

Terms used here are defined in the [Glossary](glossary.md).
