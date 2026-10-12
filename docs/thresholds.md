# Threshold tuning (T139)

One slider, two gates: `allow_threshold` (ok + confident → auto-allow),
`delete_threshold` (violation + confident → auto-delete). Between them sits
`flag`; below both, `escalate`.

* Start at 0.85/0.85. Measure `gate_prec` in `eval/reports/`.
* Too many mistakes → raise to 0.9 (fewer auto-actions, more review queue).
* Too much review load → lower to 0.75, but watch overconfident errors.
* High-severity rules (scams, PII) get an automatic −0.15 via `severity`.
* Margin abstention (`margin_abstain=0.15`) escalates close calls regardless.
