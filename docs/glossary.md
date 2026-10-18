# Glossary (T150)

_(Last checked against v0.4.0.)_

* **System One model** — fast typed-decision model (Kahneman's System 1): state in,
  probabilities out, no text generation. Jev (closed) / Laya (open) started the category.
* **choice** — pick one label from a dynamic set; full distribution returned.
* **score** — ordered levels (e.g. safe/suspicious/harmful); expectation + distribution.
* **noul** — yes/no proposition with calibrated P(true).
* **RLCD** — Reinforcement Learning for Calibrated Decisions: proper scoring rules
  reward honest probabilities.
* **gate** — confidence threshold policy mapping decisions to allow/flag/delete/escalate.
* **flag band** (T331) — confidence slice just under the delete bar where a
  suspected violation becomes `flag` instead of `escalate`.
* **coalescing** (T180) — concurrent identical requests join one in-flight
  inference instead of doubling model work.
* **quiet-hours** (T185) — UTC window where auto-delete demotes to escalate.
* **fastpath** (T017) — model-free allow when link-worded rules meet a linkless
  message (word-boundary matched since T228).
* **margin** (T335) — top1-minus-top2 rule probability; below `margin_abstain`
  the call abstains to escalate.
* **router pool** (T451) — LRU cache of built Laya routers keyed by constructor
  kwargs (checkpoint × device). Building a router is expensive; the pool reuses
  them, evicting least-recently-used when `BOUNCER_POOL_MAX` is hit.
* **circuit breaker** (T511) — failure-counting guard: after `breaker_n`
  consecutive model failures it stops calling the model and short-circuits to
  `escalate` (`cause=breaker-open`) until a cooldown passes.
* **half-open** (T516) — the breaker's probe state after cooldown: exactly one
  trial request reaches the model; success closes the breaker, failure re-opens
  it for another cooldown.
* **snapshot** (T434) — point-in-time copy of decision counters + per-user
  strikes (`bouncer snapshot save/load`); version-stamped, restored best-effort
  across versions.
* **multitenancy** (T471) — serving several communities from one process: each
  request brings its own rules (or `preset`), thresholds, lang and model pin —
  nothing about a server is global state.
