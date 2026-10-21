"""Human-readable reasons for every decision (no LLM needed)."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
from .normalize import strip_controls


def explain(res: dict, rules: dict) -> str:
    """T035: one-line reason citing the rule text; T036 includes text, T037
    runner-up. T779: the assembled line is scrubbed HERE, at the source —
    CLI output, logs and API responses all get a reason that can't carry
    control chars, whatever the rule text contained."""
    return strip_controls(_explain(res, rules))


def _explain(res: dict, rules: dict) -> str:
    """T035: one-line reason citing the rule text; T036 includes text, T037 runner-up."""
    action, rule, conf = res["action"], res["rule"], res["confidence"]
    if res.get("forced"):  # T204+T276: overrides lead; ok-forced touches no dists
        base = f"{action}: override {res['forced']}"
        if rule != "ok":
            base += f"; rule '{rule}' — {rules.get(rule, '')}"
        base += f" (conf {conf:.2f})"
        return base
    if rule == "ok":
        base = f"{action}: no rule violated (conf {conf:.2f})"
    else:
        base = f"{action}: violates '{rule}' — {rules.get(rule, '')} (conf {conf:.2f})"
    if res.get("harm"):  # T241
        base += f" [harm={res['harm']}]"
    if res.get("lang"):  # T491
        base += f" [lang={res['lang']}]"
    probs = res.get("rule_dist") or {}
    if probs and conf < 0.9:
        top2 = sorted(probs.items(), key=lambda kv: -kv[1])[:2]
        if len(top2) == 2:
            base += (f"; runner-up '{top2[1][0]}' @ {top2[1][1]:.2f}"
                     f" (margin {top2[0][1]-top2[1][1]:.2f})")
    if res.get("abstained"):
        base += " [abstained: low margin]"
    return base


def appeal_text(res: dict, rules: dict | None = None) -> str:
    """T183: copy-paste appeal helper (template, no LLM). T242 cites rule text."""
    text = (rules or {}).get(res["rule"], "")
    cite = f" Rule: '{res['rule']}' — {text}" if text else f" Rule: '{res['rule']}'"
    past = {"flag": "flagged", "delete": "deleted",  # T864: no "flagd"
            "escalate": "escalated"}.get(res["action"], res["action"])
    return (f"Your message was {past} for '{res['rule']}'"
            f" (confidence {res['confidence']:.0%}).{cite} "
            "If this looks wrong, reply APPEAL and a human reviews it within a day.")


# T896: lang_note (T186) is gone — detect_script (T492) / detect_lang (T857)
# do the same job with a dominant-script tally instead of any-char hits, and
# everything that wanted the note already calls those. No dead twins.
# T954: announce_line (T184) is gone the same way — dead since introduction:
# no caller in src, tests or docs ever appeared, and the decision announces
# itself where it happens (the shared moderate_action line, T953). Removed
# rather than wired: inventing a mod-channel consumer would be the feature
# nobody asked for. No dead twins.
