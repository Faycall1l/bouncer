"""T1234: typed task and outcome contracts for paired evaluation.

A task is a fully specified decision request: the state, the gate config, the
rule ordering variant, and the adjudicated gold labels. An outcome is the
engine's answer plus the path that produced it. Both are frozen dataclasses
with strict readers; an unknown key or a missing required field is an error,
never a default. This is what makes a paired comparison falsifiable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

ACTION_NAMES = ("allow", "delete", "flag", "escalate")
SOURCE_NAMES = ("model", "cache", "fastpath", "empty", "breaker", "fallback",
                "coalesced")
VARIANTS = ("identity", "reversed_rules")
_GOLD_KEYS = ("rule", "harm", "hype", "jailbreak", "escalate")


class SchemaError(ValueError):
    """Raised when a record does not match the declared harness contract."""


def canonical(obj: Any) -> str:
    """Stable JSON encoding used for every hash in the harness."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def _dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError(f"{where}: expected object")
    return value


def _keys(obj: dict[str, Any], where: str, required: tuple[str, ...],
          optional: tuple[str, ...] = ()) -> None:
    unknown = sorted(set(obj) - set(required) - set(optional))
    if unknown:
        raise SchemaError(f"{where}: unknown keys {unknown}")
    missing = sorted(set(required) - set(obj))
    if missing:
        raise SchemaError(f"{where}: missing keys {missing}")


def _str(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{where}: expected string")
    return value


def _bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise SchemaError(f"{where}: expected bool")
    return value


def _number(value: Any, where: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{where}: expected number")
    v = float(value)
    if not lo <= v <= hi:
        raise SchemaError(f"{where}: expected value in [{lo}, {hi}]")
    return v


@dataclass(frozen=True)
class GoldPolicy:
    """Declared mapping from adjudicated labels to a terminal action.

    This is a policy choice, not a learned result. It is recorded in every
    manifest so a reader can see exactly how gold actions were derived.
    """

    violation_action: str
    ok_action: str
    jailbreak_action: str
    escalate_action: str
    precedence: tuple[str, ...] = ("jailbreak", "escalate", "violation", "ok")

    def __post_init__(self) -> None:
        for name in ("violation_action", "ok_action", "jailbreak_action",
                     "escalate_action"):
            if getattr(self, name) not in ACTION_NAMES:
                raise SchemaError(f"GoldPolicy.{name}: not a terminal action")
        if set(self.precedence) != {"jailbreak", "escalate", "violation", "ok"}:
            raise SchemaError("GoldPolicy.precedence: must name all four paths")
        if len(self.precedence) != 4:
            raise SchemaError("GoldPolicy.precedence: duplicate path")

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_action": self.violation_action,
            "ok_action": self.ok_action,
            "jailbreak_action": self.jailbreak_action,
            "escalate_action": self.escalate_action,
            "precedence": list(self.precedence),
        }

    @classmethod
    def from_dict(cls, value: Any) -> GoldPolicy:
        obj = _dict(value, "GoldPolicy")
        _keys(obj, "GoldPolicy", (
            "violation_action", "ok_action", "jailbreak_action",
            "escalate_action", "precedence"))
        prec = obj["precedence"]
        if not isinstance(prec, list) or any(not isinstance(x, str) for x in prec):
            raise SchemaError("GoldPolicy.precedence: expected list of strings")
        return cls(
            violation_action=_str(obj["violation_action"], "GoldPolicy.violation_action"),
            ok_action=_str(obj["ok_action"], "GoldPolicy.ok_action"),
            jailbreak_action=_str(obj["jailbreak_action"], "GoldPolicy.jailbreak_action"),
            escalate_action=_str(obj["escalate_action"], "GoldPolicy.escalate_action"),
            precedence=tuple(prec),
        )

    def gold_action(self, labels: dict[str, Any]) -> str:
        jet = _bool(labels.get("jailbreak"), "labels.jailbreak")
        esc = _bool(labels.get("escalate"), "labels.escalate")
        rule = labels.get("rule")
        if not isinstance(rule, str):
            raise SchemaError("labels.rule: expected string")
        by_path = {
            "jailbreak": (jet, self.jailbreak_action),
            "escalate": (esc, self.escalate_action),
            "violation": (rule != "ok", self.violation_action),
            "ok": (rule == "ok", self.ok_action),
        }
        for path in self.precedence:
            hit, action = by_path[path]
            if hit:
                return action
        raise SchemaError("GoldPolicy: no path matched (unreachable)")


@dataclass(frozen=True)
class TaskSpec:
    """One fully specified request plus its adjudicated reference labels."""

    task_id: str
    dataset: str
    split: str
    message: str
    rules: dict[str, str]
    history: tuple[str, ...]
    lang: str | None
    config: dict[str, Any]
    gold_action: str
    gold_rule: str
    gold_harm: str
    gold_hype: str
    gold_jailbreak: bool
    gold_escalate: bool
    variant: str

    def __post_init__(self) -> None:
        if self.gold_action not in ACTION_NAMES:
            raise SchemaError("TaskSpec.gold_action: not a terminal action")
        if self.variant not in VARIANTS:
            raise SchemaError("TaskSpec.variant: not a declared variant")
        if not isinstance(self.rules, dict) or not self.rules:
            raise SchemaError("TaskSpec.rules: expected non-empty object")
        if any(not isinstance(k, str) or not isinstance(v, str)
               for k, v in self.rules.items()):
            raise SchemaError("TaskSpec.rules: keys and texts must be strings")
        if self.gold_rule != "ok" and self.gold_rule not in self.rules:
            raise SchemaError("TaskSpec.gold_rule: unknown rule id")
        if not isinstance(self.history, tuple) or any(
                not isinstance(x, str) for x in self.history):
            raise SchemaError("TaskSpec.history: expected tuple of strings")
        if self.lang is not None and not isinstance(self.lang, str):
            raise SchemaError("TaskSpec.lang: expected string or None")
        _dict(self.config, "TaskSpec.config")

    @property
    def instance_id(self) -> str:
        return f"{self.task_id}:{self.variant}"

    def state(self) -> dict[str, Any]:
        return {"message": self.message, "history": list(self.history),
                "rules": dict(self.rules)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "dataset": self.dataset, "split": self.split,
            "message": self.message, "rules": dict(self.rules),
            "history": list(self.history), "lang": self.lang,
            "config": dict(self.config), "gold_action": self.gold_action,
            "gold_rule": self.gold_rule, "gold_harm": self.gold_harm,
            "gold_hype": self.gold_hype, "gold_jailbreak": self.gold_jailbreak,
            "gold_escalate": self.gold_escalate, "variant": self.variant,
        }

    @classmethod
    def from_dict(cls, value: Any) -> TaskSpec:
        obj = _dict(value, "TaskSpec")
        _keys(obj, "TaskSpec", (
            "task_id", "dataset", "split", "message", "rules", "history",
            "lang", "config", "gold_action", "gold_rule", "gold_harm",
            "gold_hype", "gold_jailbreak", "gold_escalate", "variant"))
        hist = obj["history"]
        if not isinstance(hist, list):
            raise SchemaError("TaskSpec.history: expected list")
        return cls(
            task_id=_str(obj["task_id"], "TaskSpec.task_id"),
            dataset=_str(obj["dataset"], "TaskSpec.dataset"),
            split=_str(obj["split"], "TaskSpec.split"),
            message=_str(obj["message"], "TaskSpec.message"),
            rules=_dict(obj["rules"], "TaskSpec.rules"),
            history=tuple(_str(x, "TaskSpec.history[]") for x in hist),
            lang=obj["lang"],
            config=_dict(obj["config"], "TaskSpec.config"),
            gold_action=_str(obj["gold_action"], "TaskSpec.gold_action"),
            gold_rule=_str(obj["gold_rule"], "TaskSpec.gold_rule"),
            gold_harm=_str(obj["gold_harm"], "TaskSpec.gold_harm"),
            gold_hype=_str(obj["gold_hype"], "TaskSpec.gold_hype"),
            gold_jailbreak=_bool(obj["gold_jailbreak"], "TaskSpec.gold_jailbreak"),
            gold_escalate=_bool(obj["gold_escalate"], "TaskSpec.gold_escalate"),
            variant=_str(obj["variant"], "TaskSpec.variant"),
        )

    @classmethod
    def from_data_row(cls, row: Any, *, dataset: str, split: str,
                      policy: GoldPolicy, config: dict[str, Any],
                      task_id: str | None = None) -> TaskSpec:
        obj = _dict(row, "data row")
        _keys(obj, "data row", ("v", "state", "labels"), ("id", "split"))
        if "split" in obj and obj["split"] != split:
            raise SchemaError("data row.split: does not match declared split")
        if obj["v"] != 1:
            raise SchemaError("data row.v: only schema 1 is supported")
        state = _dict(obj["state"], "state")
        _keys(state, "state", ("message", "history", "rules"))
        labels = _dict(obj["labels"], "labels")
        _keys(labels, "labels", _GOLD_KEYS)
        rules = _dict(state["rules"], "state.rules")
        hist = state["history"]
        if not isinstance(hist, list):
            raise SchemaError("state.history: expected list")
        tid = task_id or f"{dataset}:{split}:{digest(state)[:16]}"
        return cls(
            task_id=_str(tid, "task_id"), dataset=dataset, split=split,
            message=_str(state["message"], "state.message"), rules=rules,
            history=tuple(_str(x, "state.history[]") for x in hist),
            lang=None,  # no undeclared language inference in the harness
            config=dict(config), gold_action=policy.gold_action(labels),
            gold_rule=_str(labels["rule"], "labels.rule"),
            gold_harm=_str(labels["harm"], "labels.harm"),
            gold_hype=_str(labels["hype"], "labels.hype"),
            gold_jailbreak=_bool(labels["jailbreak"], "labels.jailbreak"),
            gold_escalate=_bool(labels["escalate"], "labels.escalate"),
            variant="identity",
        )

    def with_variant(self, variant: str) -> TaskSpec:
        if variant not in VARIANTS:
            raise SchemaError(f"unknown variant {variant!r}")
        if variant == "identity":
            return replace(self, variant=variant)
        # Rule order is part of the request. Reversing it tests order sensitivity
        # without changing the rule set or the gold label.
        reversed_rules = dict(reversed(list(self.rules.items())))
        return replace(self, variant=variant, rules=reversed_rules)

    def fingerprint(self) -> str:
        return digest(self.to_dict())

    def config_fingerprint(self) -> str:
        return digest(self.config)


@dataclass(frozen=True)
class DecisionTrace:
    """The non-numeric path metadata attached to an outcome."""

    source: str
    cause: str
    decision_path: str
    attempts: int
    fallback_cause: str | None
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.source not in SOURCE_NAMES:
            raise SchemaError("DecisionTrace.source: unknown decision source")
        if not isinstance(self.cause, str) or not self.cause:
            raise SchemaError("DecisionTrace.cause: required non-empty string")
        if not isinstance(self.decision_path, str):
            raise SchemaError("DecisionTrace.decision_path: expected string")
        if isinstance(self.attempts, bool) or self.attempts < 1:
            raise SchemaError("DecisionTrace.attempts: expected positive int")
        if self.fallback_cause is not None and not isinstance(self.fallback_cause, str):
            raise SchemaError("DecisionTrace.fallback_cause: expected string or None")
        if any(not isinstance(x, str) for x in self.notes):
            raise SchemaError("DecisionTrace.notes: expected strings")

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "cause": self.cause,
                "decision_path": self.decision_path, "attempts": self.attempts,
                "fallback_cause": self.fallback_cause, "notes": list(self.notes)}

    @classmethod
    def from_dict(cls, value: Any) -> DecisionTrace:
        obj = _dict(value, "DecisionTrace")
        _keys(obj, "DecisionTrace", ("source", "cause", "decision_path",
                                     "attempts", "fallback_cause", "notes"))
        notes = obj["notes"]
        if not isinstance(notes, list):
            raise SchemaError("DecisionTrace.notes: expected list")
        return cls(
            source=_str(obj["source"], "DecisionTrace.source"),
            cause=_str(obj["cause"], "DecisionTrace.cause"),
            decision_path=_str(obj["decision_path"], "DecisionTrace.decision_path"),
            attempts=obj["attempts"], fallback_cause=obj["fallback_cause"],
            notes=tuple(_str(x, "DecisionTrace.notes[]") for x in notes),
        )


@dataclass(frozen=True)
class Outcome:
    """One terminal decision by one router on one task."""

    router: str
    action: str
    rule: str
    confidence: float
    abstained: bool
    latency_ms: float
    trace: DecisionTrace

    def __post_init__(self) -> None:
        if self.action not in ACTION_NAMES:
            raise SchemaError("Outcome.action: not a terminal action")
        _str(self.router, "Outcome.router")
        _str(self.rule, "Outcome.rule")
        _number(self.confidence, "Outcome.confidence", 0.0, 1.0)
        _number(self.latency_ms, "Outcome.latency_ms", 0.0, 1e9)
        _bool(self.abstained, "Outcome.abstained")

    def to_dict(self) -> dict[str, Any]:
        return {"router": self.router, "action": self.action, "rule": self.rule,
                "confidence": self.confidence, "abstained": self.abstained,
                "latency_ms": self.latency_ms, "trace": self.trace.to_dict()}

    @classmethod
    def from_dict(cls, value: Any) -> Outcome:
        obj = _dict(value, "Outcome")
        _keys(obj, "Outcome", ("router", "action", "rule", "confidence",
                               "abstained", "latency_ms", "trace"))
        return cls(
            router=_str(obj["router"], "Outcome.router"),
            action=_str(obj["action"], "Outcome.action"),
            rule=_str(obj["rule"], "Outcome.rule"),
            confidence=obj["confidence"], abstained=obj["abstained"],
            latency_ms=obj["latency_ms"],
            trace=DecisionTrace.from_dict(obj["trace"]),
        )

    @classmethod
    def from_moderate(cls, router: str, result: dict[str, Any], *,
                      source: str, decision_path: str, attempts: int,
                      fallback_cause: str | None = None,
                      notes: tuple[str, ...] = ()) -> Outcome:
        """Wrap an engine result without supplying any missing field."""
        obj = _dict(result, "moderate result")
        for key in ("action", "rule", "confidence", "abstained", "latency_ms", "cause"):
            if key not in obj:
                raise SchemaError(f"moderate result: missing {key!r}")
        trace = DecisionTrace(
            source=source, cause=_str(obj["cause"], "moderate result.cause"),
            decision_path=decision_path, attempts=attempts,
            fallback_cause=fallback_cause, notes=notes,
        )
        return cls(
            router=_str(router, "router"), action=_str(obj["action"], "action"),
            rule=_str(obj["rule"], "rule"), confidence=obj["confidence"],
            abstained=obj["abstained"], latency_ms=obj["latency_ms"], trace=trace,
        )

    def decision_digest(self) -> str:
        """Hash of everything except timing: stability gate compares this."""
        return digest({"router": self.router, "action": self.action,
                       "rule": self.rule, "confidence": self.confidence,
                       "abstained": self.abstained,
                       "trace": self.trace.to_dict()})


@dataclass(frozen=True)
class PairOutcome:
    """Base and candidate answers to the same task instance."""

    task_id: str
    instance_id: str
    variant: str
    spec_hash: str
    config_hash: str
    base: Outcome
    candidate: Outcome

    def __post_init__(self) -> None:
        if self.instance_id != f"{self.task_id}:{self.variant}":
            raise SchemaError("PairOutcome.instance_id: does not match task/variant")
        if self.variant not in VARIANTS:
            raise SchemaError("PairOutcome.variant: not a declared variant")
        if not all(isinstance(x, str) and len(x) == 64
                   for x in (self.spec_hash, self.config_hash)):
            raise SchemaError("PairOutcome: expected sha256 digests")

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "instance_id": self.instance_id,
                "variant": self.variant, "spec_hash": self.spec_hash,
                "config_hash": self.config_hash,
                "base": self.base.to_dict(), "candidate": self.candidate.to_dict()}

    @classmethod
    def from_dict(cls, value: Any) -> PairOutcome:
        obj = _dict(value, "PairOutcome")
        _keys(obj, "PairOutcome", ("task_id", "instance_id", "variant",
                                   "spec_hash", "config_hash", "base", "candidate"))
        return cls(
            task_id=_str(obj["task_id"], "PairOutcome.task_id"),
            instance_id=_str(obj["instance_id"], "PairOutcome.instance_id"),
            variant=_str(obj["variant"], "PairOutcome.variant"),
            spec_hash=_str(obj["spec_hash"], "PairOutcome.spec_hash"),
            config_hash=_str(obj["config_hash"], "PairOutcome.config_hash"),
            base=Outcome.from_dict(obj["base"]),
            candidate=Outcome.from_dict(obj["candidate"]),
        )
