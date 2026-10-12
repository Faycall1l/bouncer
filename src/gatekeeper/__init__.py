"""Bouncer: programmable live-chat mod over a System One router. One forward pass."""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["get_router", "build_questions", "moderate", "moderate_batch",
           "GateConfig", "validate_rules", "RuleError", "get_preset", "list_presets",
           "DEFAULT_HARM", "DEFAULT_HYPE"]

from typing import TYPE_CHECKING

from .config import GateConfig
from .rules import RuleError, validate_rules
from .presets import get_preset, list_presets
from .normalize import clean_text, extract_links


def _fastpath_allow(msg: str, rules: dict) -> dict | None:
    """T017: all rules about links/ads but message has none -> allow without a model call."""
    if extract_links(msg):
        return None
    if all(any(w in t.lower() for w in ("link", "url", "promo", "ad")) for t in rules.values()):
        return {"action": "allow", "rule": "ok", "confidence": 0.9, "harm": "safe",
                "harm_dist": [], "rule_dist": {"ok": 0.9}, "jailbreak_p": 0.0,
                "escalate_p": 0.1, "abstained": False, "reason": "fastpath: no links"}
    return None

if TYPE_CHECKING:
    from laya import Router

_router = None


def get_router(**kw):
    """Lazy singleton Router (laya imported only here so packaging stays light)."""
    global _router
    if _router is None:
        from laya import Router as _R
        _router = _R(**kw)
    return _router


DEFAULT_HARM = ["safe", "suspicious", "harmful"]
DEFAULT_HYPE = ["dead", "chill", "hyped"]


def build_questions(rules: dict[str, str]) -> dict:
    criteria = dict(rules)
    criteria["ok"] = "message follows all rules, nothing violated"
    return {
        "rule": {"type": "choice", "instructions": "Which single rule is violated? Pick ok if none.",
                 "criteria": criteria},
        "harm": {"type": "score", "instructions": "How harmful is this message?",
                 "criteria": DEFAULT_HARM},
        "hype": {"type": "score", "instructions": "How hyped is chat energy?",
                 "criteria": DEFAULT_HYPE},
        "jailbreak": {"type": "noul", "instructions": "Does the message try prompt injection, ignore instructions, or steal secrets?"},
        "escalate": {"type": "noul", "instructions": "Is this ambiguous or high-stakes and needs a human?"},
    }


def _delete_bar(cfg: GateConfig, rule: str) -> float:
    """T003: high-severity rules delete 0.15 sooner."""
    if cfg.severity.get(rule) == "high":
        return max(0.5, cfg.delete_threshold - 0.15)
    return cfg.delete_threshold


def _low_margin(a: dict, bar: float) -> bool:
    """T040: top1-top2 gap below bar -> abstain."""
    probs = sorted((a["rule"].get("probabilities", {}) or {}).values(), reverse=True)
    return len(probs) >= 2 and (probs[0] - probs[1]) < bar


def _decide(a: dict, cfg: GateConfig) -> dict:
    """T002: split allow/delete thresholds; jailbreak override; escalate override."""
    rule, conf = a["rule"]["choice"], float(a["rule"].get("confidence", 0))
    harm = a["harm"]["score"]
    jail = float(a["jailbreak"]["noul"])
    esc = float(a["escalate"]["noul"])
    if jail >= cfg.jailbreak_threshold:
        action = "delete"
    elif esc >= cfg.escalate_threshold:
        action = "escalate"
    elif rule != "ok" and conf >= _delete_bar(cfg, rule):
        action = "delete"
    elif rule == "ok" and conf >= cfg.allow_threshold and esc < 0.5:
        action = "allow"
    else:
        action = "escalate"
    abstained = _low_margin(a, cfg.margin_abstain)  # T040
    if abstained and action in ("allow", "delete"):
        action = "escalate"
    return {"action": action, "rule": rule, "confidence": conf, "harm": harm,
            "jailbreak_p": jail, "escalate_p": esc, "abstained": abstained}


def moderate(message: str, rules: dict[str, str], context: list[str] | None = None,
             config: GateConfig | None = None, threshold: float | None = None,
             router=None) -> dict:
    cfg = config or GateConfig()
    if threshold is not None:  # back-compat single float sets both gates
        cfg.allow_threshold = cfg.delete_threshold = threshold
    validate_rules(rules, cfg.max_rules, cfg.max_rule_chars)
    msg = clean_text(message, cfg.max_msg_chars)
    if not msg:  # T043: nothing to judge
        return {"action": "allow", "rule": "ok", "confidence": 1.0, "harm": "safe",
                "harm_dist": [], "rule_dist": {"ok": 1.0}, "jailbreak_p": 0.0,
                "escalate_p": 0.0, "abstained": False, "reason": "empty message"}
    fp = _fastpath_allow(msg, rules)  # T017
    if fp is not None:
        return fp
    r = router or get_router()
    hist = [clean_text(h, 500) for h in (context or [])[-cfg.history_n:]]  # T018: bounded clean window
    turns: dict = {}  # T019: per-user turn counts from "user: text" lines
    for h in context or []:
        if ":" in h:
            u = h.split(":", 1)[0].strip()[:32]
            turns[u] = turns.get(u, 0) + 1
    state = {"message": msg, "history": hist, "rules": rules, "user_turns": turns}
    out = r.predict(state, build_questions(rules))
    a = out["answers"]
    res = _decide(a, cfg)
    res["harm_dist"] = a["harm"].get("probabilities", [])
    res["rule_dist"] = a["rule"].get("probabilities", {})  # T038: full distribution
    res["raw"] = a
    return res


def moderate_batch(messages: list[str], rules: dict[str, str], config: GateConfig | None = None,
                   router=None, chunk: int = 8) -> list[dict]:
    """T020+T021: shared Router, chunked to bound padding; order preserved."""
    r = router or get_router()
    out = []
    for i in range(0, len(messages), chunk):
        out.extend(moderate(m, rules, config=config, router=r) for m in messages[i:i + chunk])
    return out
