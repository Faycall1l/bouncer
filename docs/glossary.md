# Glossary (T150)

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
