"""Bouncer: programmable live-chat mod over a System One router. One forward pass.

Apache-2.0. See LICENSE.
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.

__version__ = "0.1.2"
__all__ = [
    "DEFAULT_HARM",
    "DEFAULT_HYPE",
    "BouncerError",
    "GateConfig",
    "ModelError",
    "RuleError",
    "build_questions",
    "get_preset",
    "get_router",
    "list_presets",
    "moderate",
    "moderate_batch",
    "validate_rules",
]

from functools import lru_cache  # T274
from typing import TYPE_CHECKING

from .audit import log_decision  # T273: stdlib-only modules, no import cycle
from .cache import CACHE  # T023/T024 decision cache
from .config import GateConfig
from .explain import explain as _explain  # T273
from .normalize import clean_text, extract_links
from .presets import get_preset, list_presets
from .review import add as _qadd  # T273
from .rules import RuleError, validate_rules
from .stats import record  # T273

_INFLIGHT: dict = {}  # T180: key -> [event, result]
import threading as _th

_FLY_LOCK = _th.Lock()


def _fastpath_allow(msg: str, rules: dict) -> dict | None:
    """T017: all rules about links/ads but message has none -> allow without a model call."""
    if extract_links(msg):
        return None
    import re as _re  # T228: word boundaries — "ad" must not match "raid"/"ready"
    if all(_re.search(r"\b(link|url|promo|ads?)\b", t.lower()) for t in rules.values()):
        return {"action": "allow", "rule": "ok", "confidence": 0.9, "harm": "safe",
                "harm_dist": [], "rule_dist": {"ok": 0.9}, "jailbreak_p": 0.0,
                "escalate_p": 0.1, "abstained": False, "reason": "fastpath: no links"}
    return None

if TYPE_CHECKING:
    from laya import Router  # noqa: F401 — annotation-only import

_router = None


def get_router(**kw):
    """Lazy singleton Router (laya imported only here so packaging stays light)."""
    global _router
    if _router is None:
        from laya import Router as _R
        _router = _R(**kw)
    elif kw:  # T268: silent kwarg-drop is a debugging trap
        import warnings
        warnings.warn(f"get_router() already initialized; ignoring {sorted(kw)}",
                      RuntimeWarning, stacklevel=2)
    return _router


DEFAULT_HARM = ["safe", "suspicious", "harmful"]
DEFAULT_HYPE = ["dead", "chill", "hyped"]


def build_questions(rules: dict[str, str]) -> dict:
    """Read-only result (backed by an lru_cache): pass to predict, do not mutate."""
    return _cached_questions(tuple(sorted(rules.items())))


@lru_cache(maxsize=128)  # T274: same rule-set rebuilds no dicts per message
def _cached_questions(items: tuple) -> dict:
    criteria = dict(items)
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


def _quiet_active(cfg: GateConfig) -> bool:
    """T221: is a delete->escalate quiet window in effect right now?"""
    if not cfg.quiet_hours:
        return False
    import datetime
    h = datetime.datetime.now(datetime.timezone.utc).hour
    lo, hi = cfg.quiet_hours
    return (lo <= h < hi) if lo < hi else (h >= lo or h < hi)


def _observe(msg: str, action: str, rule: str, conf: float, cause: str) -> None:
    """T222: cheap paths (empty/fastpath) still count in stats + audit."""
    record(action, rule, 0.0, cheap=True, cause=cause)  # T232+T233+T234
    log_decision(msg, rule, conf, action, 0.0)


def _low_margin(a: dict, bar: float) -> bool:
    """T040: top1-top2 gap below bar -> abstain."""
    probs = sorted((a["rule"].get("probabilities", {}) or {}).values(), reverse=True)
    return len(probs) >= 2 and (probs[0] - probs[1]) < bar


def _executor():
    """T259: one shared pool for timeout-guarded predicts (no per-call alloc)."""
    global _EXEC
    if _EXEC is None:
        import concurrent.futures as cf
        _EXEC = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="bouncer-inf")
    return _EXEC


_EXEC = None


def _predict_safe(router, state: dict, questions: dict, timeout_s: float) -> dict:
    """T025+T026: timeout guard, one retry, escalate-shaped fallback on failure."""
    import concurrent.futures as cf
    last = None
    timed_out = False  # T258
    for _ in range(2):
        try:
            return _executor().submit(router.predict, state, questions).result(timeout_s)
        except cf.TimeoutError:
            timed_out, last = True, f"predict exceeded {timeout_s}s"
        except Exception as e:  # noqa: BLE001
            last = e
    if timed_out:  # T258: name the timeout so operators see a slow model, not a crash
        raise ModelError(f"timed out after {timeout_s}s (one retry)")
    raise ModelError(f"inference failed twice ({last})")  # T197


class BouncerError(Exception):
    """T197: every error carries a machine-readable code."""

    code = "E_BOUNCER"

    def __str__(self) -> str:  # T257: code always visible in logs/messages
        base = super().__str__()
        return f"{self.code}: {base}" if base else self.code


class ModelError(BouncerError):
    code = "E_MODEL"


def _fallback(action_note: str) -> dict:
    return {"action": "escalate", "rule": "ok", "confidence": 0.0, "harm": "suspicious",
            "harm_dist": [], "rule_dist": {}, "jailbreak_p": 0.0, "escalate_p": 1.0,
            "abstained": True, "reason": action_note}


def _level(score_val, levels: list) -> str:
    """T203: real score answers are floats (expected level); snap to nearest label."""
    try:
        idx = min(len(levels) - 1, max(0, round(float(score_val))))
    except (TypeError, ValueError):
        return str(score_val)
    if isinstance(score_val, str) and score_val in levels:
        return score_val
    return levels[idx]


def _decide(a: dict, cfg: GateConfig) -> dict:
    """T002: split allow/delete thresholds; jailbreak override; escalate override."""
    rule, conf = a["rule"]["choice"], float(a["rule"].get("confidence", 0))
    harm = _level(a["harm"]["score"], DEFAULT_HARM)  # T203
    jail = float(a["jailbreak"]["noul"])
    esc = float(a["escalate"]["noul"])
    forced = None  # T204: overrides survive margin abstention
    if jail >= cfg.jailbreak_threshold:
        action, forced = "delete", f"jailbreak {jail:.2f}"
        cause = "jailbreak"  # T234
    elif esc >= cfg.escalate_threshold:
        action, forced = "escalate", f"needs-human {esc:.2f}"
        cause = "needs-human"  # T234
    elif rule != "ok" and conf >= _delete_bar(cfg, rule):
        action, cause = "delete", "violation"
    elif rule != "ok" and conf >= _delete_bar(cfg, rule) - 0.15:
        action, cause = "flag", "suspected"  # T031: suspected violation, visible but needs review
    elif rule == "ok" and conf >= cfg.allow_threshold and esc < 0.5:
        action, cause = "allow", "ok"
    else:
        action, cause = "escalate", "low-conf"
    abstained = _low_margin(a, cfg.margin_abstain)  # T040
    if abstained and forced is None and action in ("allow", "delete"):
        action, cause = "escalate", "margin"  # T234
    if action == "delete" and _quiet_active(cfg):  # T185
        action, cause = "escalate", "quiet"  # T234
    return {"action": action, "rule": rule, "confidence": conf, "harm": harm,
            "jailbreak_p": jail, "escalate_p": esc, "abstained": abstained, "forced": forced,
            "cause": cause}


def moderate(message: str, rules: dict[str, str], context: list[str] | None = None,
             config: GateConfig | None = None, threshold: float | None = None,
             lang: str | None = None, router=None, _prevalidated: bool = False) -> dict:
    cfg = config or GateConfig()
    if threshold is not None:  # back-compat single float sets both gates
        cfg.allow_threshold = cfg.delete_threshold = threshold
        cfg.validate()  # T255: mutation bypasses __post_init__; re-check ranges
    if not _prevalidated:
        validate_rules(rules, cfg.max_rules, cfg.max_rule_chars, cfg.severity)
    msg = clean_text(message, cfg.max_msg_chars)
    if not msg:  # T043: nothing to judge
        res = {"action": "allow", "rule": "ok", "confidence": 1.0, "harm": "safe",
               "harm_dist": [], "rule_dist": {"ok": 1.0}, "jailbreak_p": 0.0,
               "escalate_p": 0.0, "abstained": False, "reason": "empty message",
               "latency_ms": 0.0}
        _observe(msg, "allow", "ok", 1.0, "empty")  # T222
        return res
    fp = _fastpath_allow(msg, rules)  # T017
    if fp is not None:
        fp["latency_ms"] = 0.0
        _observe(msg, fp["action"], fp["rule"], fp["confidence"], "fastpath")  # T222
        return fp
    key = CACHE.key(msg, rules, cfg.allow_threshold, cfg.delete_threshold,  # T221
                    cfg.severity, lang, context or (), cfg.history_n,
                    _quiet_active(cfg))
    hit = CACHE.get(key)
    if hit is not None:
        return dict(hit, cached=True)
    with _FLY_LOCK:  # T180: join identical in-flight call instead of doubling work
        if key in _INFLIGHT:
            ev, box = _INFLIGHT[key]
            joined = True
        else:
            ev, box = _th.Event(), {}
            _INFLIGHT[key] = (ev, box)
            joined = False
    if joined:
        ev.wait(timeout=cfg.timeout_s + 5)
        if box:
            return dict(box["res"], coalesced=True)
    r = router or get_router()
    import time as _t
    t0 = _t.time()
    hist = [clean_text(h, 500) for h in (context or [])[-cfg.history_n:]]  # T018: bounded clean window
    turns: dict = {}  # T019: per-user turn counts from "user: text" lines
    for h in list(context or [])[:200]:  # T262: bound the scan, not just the window
        if ":" in h:
            u = h.split(":", 1)[0].strip()[:32]
            turns[u] = turns.get(u, 0) + 1
    state = {"message": msg, "history": hist, "rules": rules, "user_turns": turns}
    if lang:
        state["lang_hint"] = lang  # T041: nudge multilingual routing
    try:
        out = _predict_safe(r, state, build_questions(rules), cfg.timeout_s)
    except ModelError as e:
        fb = _fallback(f"{e}")  # T257: str already carries E_MODEL
        record("escalate", "ok", 0.0, cause="fallback")  # T260: failures are visible
        log_decision(msg, "ok", 0.0, "escalate", 0.0)
        try:
            _qadd(msg, {"action": "escalate", "rule": "ok", "confidence": 0.0,
                        "latency_ms": 0.0})
        except OSError:
            pass
        with _FLY_LOCK:
            if key in _INFLIGHT:
                _INFLIGHT[key][1]["res"] = fb
                _INFLIGHT[key][0].set()
                del _INFLIGHT[key]
        return fb
    a = out["answers"]
    res = _decide(a, cfg)
    res["harm_dist"] = a["harm"].get("probabilities", [])
    res["harm"] = _level(a["harm"]["score"], DEFAULT_HARM)  # T203: float->label (already in _decide)
    res["hype"] = _level(a["hype"]["score"], DEFAULT_HYPE)  # T039+T203
    res["hype_dist"] = a["hype"].get("probabilities", [])  # T039
    res["rule_dist"] = a["rule"].get("probabilities", {})  # T038: full distribution
    res["latency_ms"] = round((_t.time() - t0) * 1000, 1)
    res["raw"] = a
    record(res["action"], res["rule"], res["latency_ms"], cause=res.get("cause"))
    log_decision(msg, res["rule"], res["confidence"], res["action"], res["latency_ms"],
                 lang, len(hist), (cfg.allow_threshold, cfg.delete_threshold))
    if res["action"] in ("flag", "escalate"):  # T207: humans work the queue
        try:
            _qadd(msg, res)
        except OSError:
            pass
    res["reason"] = _explain(res, rules)  # T213: reason ships in every result
    res["cached"] = False  # T247: explicit miss marker (hits override to True)
    CACHE.set(key, {k: v for k, v in res.items() if k != "raw"})
    with _FLY_LOCK:  # T180: publish to joiners
        if key in _INFLIGHT:
            _INFLIGHT[key][1]["res"] = {k: v for k, v in res.items() if k != "raw"}
            _INFLIGHT[key][0].set()
            del _INFLIGHT[key]
    return res


def moderate_batch(messages: list[str], rules: dict[str, str], config: GateConfig | None = None,
                   router=None, chunk: int = 8) -> list[dict]:
    """T020+T021: shared Router, chunked to bound padding; order preserved."""
    cfg = config or GateConfig()
    validate_rules(rules, cfg.max_rules, cfg.max_rule_chars,  # T196: once, not per message
                   cfg.severity)
    r = router or get_router()
    out = []
    for i in range(0, len(messages), chunk):
        out.extend(moderate(m, rules, config=config, router=r, _prevalidated=True)
                   for m in messages[i:i + chunk])
    return out


async def amoderate(message: str, rules: dict[str, str], **kw) -> dict:
    """T022: async wrapper for bots/servers."""
    import asyncio
    return await asyncio.to_thread(moderate, message, rules, **kw)
