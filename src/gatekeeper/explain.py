"""Human-readable reasons for every decision (no LLM needed)."""
from __future__ import annotations

# Apache-2.0. See LICENSE.


def explain(res: dict, rules: dict) -> str:
    """T035: one-line reason citing the rule text; T036 includes text, T037 runner-up."""
    action, rule, conf = res["action"], res["rule"], res["confidence"]
    if res.get("forced"):  # T204: overrides lead, rule text follows
        base = f"{action}: override {res['forced']}"
        if rule != "ok":
            base += f"; rule '{rule}' — {rules.get(rule, '')}"
        base += f" (conf {conf:.2f})"
        return base
    if rule == "ok":
        base = f"{action}: no rule violated (conf {conf:.2f})"
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


def appeal_text(res: dict) -> str:
    """T183: copy-paste appeal helper (template, no LLM)."""
    return (f"Your message was {res['action']}d for '{res['rule']}' "
            f"(confidence {res['confidence']:.0%}). "
            "If this looks wrong, reply APPEAL and a human reviews it within a day.")


def announce_line(res: dict) -> str:
    """T184: pin-friendly one-liner for mod channels."""
    return f"[{res['action'].upper()}] {res['rule']} @ {res['confidence']:.0%}"


def lang_note(state: dict) -> str:
    """T186: script guess for the audit trail (heuristic, not a claim)."""
    t = state.get("message", "")
    if any("\u0600" <= c <= "\u06ff" for c in t):
        return "ar"
    if any("\u0400" <= c <= "\u04ff" for c in t):
        return "ru"
    if any("\u4e00" <= c <= "\u9fff" for c in t):
        return "zh"
    if any(ord(c) > 127 for c in t):
        return "non-latin"
    return "latin"
