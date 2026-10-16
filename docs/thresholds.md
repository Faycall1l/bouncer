# Threshold tuning (T139)

One slider, two gates: `allow_threshold` (ok + confident → auto-allow),
`delete_threshold` (violation + confident → auto-delete). Between them sits
`flag`; below both, `escalate`.

* Start at 0.85/0.85. Measure `gate_prec` in `eval/reports/`.
* Too many mistakes → raise to 0.9 (fewer auto-actions, more review queue).
* Too much review load → lower to 0.75, but watch overconfident errors.
* High-severity rules (scams, PII) get an automatic −0.15 via `severity`.
* Margin abstention (`margin_abstain=0.15`) escalates close calls regardless.

## Flag band + severity offset (T398)

* `flag_margin` (default 0.15): violation confidence in
  `[delete_bar − flag_margin, delete_bar)` → `flag` instead of `escalate`.
  Widen it (0.25) when reviewers prefer a visible-suspect queue over silent
  escalation; narrow it (0.05) when flags are mostly noise.
* `severity_offset` (default 0.15): high-severity rules delete at
  `delete_threshold − severity_offset`. Raise it for zero-tolerance rules
  (PII leaks), lower it when severity is a weak signal.
* `require_calm` (default off): allow only when `harm == safe`. Turn it on for
  support desks where a suspicious-but-clean verdict should still see a human.
