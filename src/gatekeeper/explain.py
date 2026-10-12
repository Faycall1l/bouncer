"""Human-readable reasons for every decision (no LLM needed)."""
from __future__ import annotations


def explain(res: dict, rules: dict) -> str:
    """T035: one-line reason citing the rule text; T036 includes text, T037 runner-up."""
    action, rule, conf = res["action"], res["rule"], res["confidence"]
    if rule == "ok":
        base = f"allow: no rule violated (conf {conf:.2f})"
    else:
        base = f"{action}: violates '{rule}' — {rules.get(rule, '')} (conf {conf:.2f})"
    probs = res.get("rule_dist") or {}
    if probs and conf < 0.9:
        top2 = sorted(probs.items(), key=lambda kv: -kv[1])[:2]
        if len(top2) == 2:
            base += f"; runner-up '{top2[1][0]}' @ {top2[1][1]:.2f} (margin {top2[0][1]-top2[1][1]:.2f})"
    if res.get("abstained"):
        base += " [abstained: low margin]"
    return base
