# Glossary (T150)

_(Last checked against v0.5.0.)_
_(Terms added at T1001: appeal, amnesty, namespaced strike, script
routing — the P44–P50 vocabulary the other pages kept citing.)_

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
* **appeal** (T864) — a user contesting a moderation action from the chat
  platform (the `APPEAL` command): it lands a row in the review queue linked
  by queue-row id, and the newest verdict is rendered back to the user
  citing that id.
* **amnesty** (T881) — operator forgiveness of a user's strikes without a
  queue row (`bouncer amnesty USER [--weight N]`): clear them all, or
  subtract exactly N (T974). Every amnesty writes one audit row — who, when,
  why (T988); a no-strikes amnesty writes nothing. Adjudicating a queue row
  `reject` grants it too, weighted per action (delete wipes 2, flag 1,
  escalate 0 — T341's table, spent through T865's adjudicate path).
* **namespaced strike** (T858) — strikes accrue per user key inside one
  process, on every decision path — cached, coalesced and batch included —
  so one user's counter never rides on another's. Adapters namespace the
  key (platform + user, T864's linkage) before it reaches the accrual.
* **script routing** (T892) — with no explicit `lang`, the message's own
  script fills the hint: arabic/cyrillic/cjk text gets `ar`/`ru`/`zh`
  (T857's `detect_lang`, a routing hint — script-honest, not
  language-honest) and routes to the checkpoint that reads that script;
  latin stays unpinned.
  `--lang auto` (T893) says the detection out loud, and T901's sweep pins
  the mapping table — mixed-script batches tag per row (T902).
