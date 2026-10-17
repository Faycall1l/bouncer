# Gate precedence (T334)

Decisions run one ordered ladder. First match wins; later demotions apply after.

| order | condition | action | cause |
|---|---|---|---|
| 1 | `jailbreak_p >= jailbreak_threshold` (0.8) | delete | `jailbreak` |
| 2 | `escalate_p >= escalate_threshold` (0.7) | escalate | `needs-human` |
| 3 | violation conf `>= delete_bar` | delete | `violation` |
| 4 | violation conf `>= delete_bar - flag_margin` | flag | `suspected` |
| 5 | `ok` conf `>= allow_threshold` and calm | allow | `ok` |
| 6 | otherwise | escalate | `low-conf` |

Overrides (before the ladder even runs):

* **Breaker open** — while the circuit breaker is tripped, cache and fastpath
  still answer, but any request that needs the model short-circuits to escalate
  (`cause=breaker-open`) instead of timing out. It sits before the ladder
  because there are no fresh probabilities to ladder on; see
  [thresholds](thresholds.md#reliability-knobs-t602). Closes via a half-open
  trial after `breaker_cool_s`.

Demotions (after the ladder):

* **Margin abstention** — top1-top2 gap `< margin_abstain` (0.15) demotes
  allow/delete to escalate (`cause=margin`). Forced overrides (1, 2) survive.
* **Quiet hours** — inside `quiet_hours`, delete becomes escalate (`cause=quiet`).

Knobs: `delete_bar = delete_threshold - severity_offset` (0.15) for
`severity == "high"` rules. `require_calm` additionally demands `harm == safe`
for allow. See [thresholds](thresholds.md).
