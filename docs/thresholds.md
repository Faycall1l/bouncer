# Threshold tuning (T139)

_(Last checked against v0.3.0.)_

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

## Reliability knobs (T602)

Not thresholds on confidence — thresholds on *failure*. They trade availability
against honesty: bouncer never lets a broken model silently allow anything.

* `breaker_n` (default 5, ≥1): consecutive model failures that trip the
  breaker. Lower it (2–3) when outages are cheap to observe and escalations are
  cheap to review — you stop paying timeouts sooner. Raise it (10) for flaky
  hardware where single-digit failures are noise.
* `breaker_cool_s` (default 30.0): seconds requests short-circuit to
  `escalate` (`cause=breaker-open`) before one half-open trial probes the
  model. Short cooldown (5s) recovers fast but re-hammers a dying model;
  long cooldown (120s) protects it but queues more escalations for humans.
* `timeout_s` (per-request, 0.5–60s, env `BOUNCER_TIMEOUT`, default 10):
  budget for one model call. Overruns count as failures toward `breaker_n`.
  Set it near your p95 latency — much higher and slow calls stack up before
  the breaker can trip.
* `questions` (default 5, env `BOUNCER_QUESTIONS`, only 3 or 5 accepted):
  how many questions each predict carries. `3` is the light set
  (rule+jailbreak+escalate): harm/hype drop out and default neutral — which
  makes `require_calm` meaningless in light mode (it can't see harm). Worth
  it when real-model padding/token cost dominates; with a stub the end-to-end
  delta is ~0.1ms (BENCHMARKS, T755). 3q and 5q decisions never share a
  cache entry.
* `max_context_tokens` (default 1000, 0 = unlimited): token budget for the
  history window that reaches the model — newest lines are kept first and
  the oldest drop out; the newest line is never dropped. The count is a
  documented chars/4 estimate (no tokenizer dependency), and every
  decision reports what actually shipped as
  `context: {items, tokens_est, cap, dropped}` — a guard you can audit,
  not a silent truncate.
* `BOUNCER_BREAKER=off`: disables the guard entirely. Only for benchmarks or
  when you have an outer health-check that does the same job.

Tuning instinct: escalation volume during an outage ≈ `requests × breaker_cool_s`
per recovery cycle. If that queue is too big, shorten the cooldown *or* lower
`breaker_n` (trips earlier, less wasted time before the trip). Simulate before
changing anything: `eval/breaker_sim.py --storm 3 --cool 0.2`.

Terms used here are defined in the [Glossary](glossary.md).
