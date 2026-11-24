"""T1241-T1242: closed-outcome decision normalization and traces.

The engine has many exits: model, cache, fastpath, empty, breaker, fallback,
and coalescing. This harness wraps every exit and records the outcome as one
of a closed enum plus an explicit policy that says which sources and causes are
allowed. Every decision carries the fields that produced it; missing required
trace fields are an error, not a default.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gatekeeper import GateConfig, moderate

from .runner import path_for_cause
from .schema import (
    SchemaError,
    _dict,
    _keys,
    _number,
    _str,
    digest,
)

OUTCOMES = ("allow", "delete", "flag", "escalate", "abstain", "error")
SOURCES = ("model", "cache", "fastpath", "empty", "breaker", "fallback",
           "coalesced")
SCENARIO_OUTCOMES = tuple(o for o in OUTCOMES if o != "error")


def _fields(obj: dict[str, Any], where: str, required: tuple[str, ...]) -> None:
    _keys(obj, where, required)


@dataclass(frozen=True)
class DecisionPolicy:
    """The closed contract a decision must satisfy before it is accepted."""

    name: str
    outcomes: tuple[str, ...]
    sources: tuple[str, ...]
    require_cause: bool = True
    require_reason: bool = True
    require_source: bool = True

    def __post_init__(self) -> None:
        _str(self.name, "DecisionPolicy.name")
        if not self.name:
            raise SchemaError("DecisionPolicy.name: expected non-empty string")
        if not self.outcomes or any(o not in OUTCOMES for o in self.outcomes):
            raise SchemaError("DecisionPolicy.outcomes: closed outcome enum required")
        if len(set(self.outcomes)) != len(self.outcomes):
            raise SchemaError("DecisionPolicy.outcomes: duplicates not allowed")
        if "error" in self.outcomes:
            raise SchemaError("DecisionPolicy.outcomes: error is reserved for failures")
        if not self.sources or any(s not in SOURCES for s in self.sources):
            raise SchemaError("DecisionPolicy.sources: closed source enum required")
        if len(set(self.sources)) != len(self.sources):
            raise SchemaError("DecisionPolicy.sources: duplicates not allowed")
        for name in ("require_cause", "require_reason", "require_source"):
            if not isinstance(getattr(self, name), bool):
                raise SchemaError(f"DecisionPolicy.{name}: expected bool")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "outcomes": list(self.outcomes),
                "sources": list(self.sources), "require_cause": self.require_cause,
                "require_reason": self.require_reason,
                "require_source": self.require_source}

    @classmethod
    def from_dict(cls, value: Any) -> DecisionPolicy:
        obj = _dict(value, "DecisionPolicy")
        _fields(obj, "DecisionPolicy", ("name", "outcomes", "sources",
                                        "require_cause", "require_reason",
                                        "require_source"))
        return cls(
            name=_str(obj["name"], "DecisionPolicy.name"),
            outcomes=tuple(_str(x, "outcomes[]") for x in obj["outcomes"]),
            sources=tuple(_str(x, "sources[]") for x in obj["sources"]),
            require_cause=obj["require_cause"],
            require_reason=obj["require_reason"],
            require_source=obj["require_source"],
        )


@dataclass(frozen=True)
class DecisionConfig:
    """An explicitly named decision policy plus the exact engine thresholds."""

    name: str
    policy: DecisionPolicy
    gate: GateConfig

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise SchemaError("DecisionConfig.name: expected non-empty string")
        if not isinstance(self.gate, GateConfig):
            raise SchemaError("DecisionConfig.gate: expected GateConfig")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "policy": self.policy.to_dict(),
                "gate": {k: v for k, v in self.gate.to_dict().items()
                         if v is not None}}

    @classmethod
    def from_dict(cls, value: Any) -> DecisionConfig:
        obj = _dict(value, "DecisionConfig")
        _fields(obj, "DecisionConfig", ("name", "policy", "gate"))
        return cls(name=obj["name"], policy=DecisionPolicy.from_dict(obj["policy"]),
                   gate=GateConfig.from_dict(obj["gate"]))

    def fingerprint(self) -> str:
        return digest(self.to_dict())


@dataclass(frozen=True)
class Decision:
    """A normalized engine decision with a closed outcome and trace fields."""

    instance_id: str
    config_fingerprint: str
    action: str
    outcome: str
    rule: str
    confidence: float
    abstained: bool
    cause: str
    reason: str
    source: str
    latency_ms: float
    cached: bool
    coalesced: bool
    fallback_cause: str | None
    present_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _str(self.instance_id, "Decision.instance_id")
        if self.outcome not in OUTCOMES:
            raise SchemaError("Decision.outcome: not a closed outcome")
        _number(self.confidence, "Decision.confidence", 0.0, 1.0)
        _number(self.latency_ms, "Decision.latency_ms", 0.0, 1e9)
        for name in ("action", "rule", "cause", "reason", "source"):
            if not isinstance(getattr(self, name), str):
                raise SchemaError(f"Decision.{name}: expected string")
        if self.fallback_cause is not None and not isinstance(self.fallback_cause, str):
            raise SchemaError("Decision.fallback_cause: expected string or None")
        if any(not isinstance(x, str) for x in self.present_fields):
            raise SchemaError("Decision.present_fields: expected strings")

    @classmethod
    def from_engine(cls, instance_id: str, config: DecisionConfig,
                    result: dict[str, Any],
                    decision_path: str | None = None) -> Decision:
        obj = _dict(result, "engine result")
        missing = [k for k in ("action", "rule", "confidence", "abstained",
                               "reason", "latency_ms") if k not in obj]
        if missing:
            raise SchemaError(f"engine result missing {missing}")
        if config.policy.require_cause and "cause" not in obj:
            raise SchemaError("engine result missing cause; add typed trace paths")
        if config.policy.require_source and "source" not in obj:
            raise SchemaError("engine result missing source; add typed trace paths")
        action = obj["action"]
        source = obj["source"]
        cause = obj["cause"]
        if config.policy.outcomes and action not in config.policy.outcomes:
            raise SchemaError(f"engine action {action!r} outside closed enum")
        if config.policy.sources and source not in config.policy.sources:
            raise SchemaError(f"engine source {source!r} outside closed enum")
        abstained = obj["abstained"]
        outcome = "abstain" if abstained else action
        if decision_path is None:  # T1242: map closed causes to closed paths
            path_for_cause(cause)
        return cls(
            instance_id=instance_id, config_fingerprint=config.fingerprint(),
            action=action, outcome=outcome, rule=obj["rule"],
            confidence=obj["confidence"], abstained=abstained, cause=cause,
            reason=obj["reason"], source=source, latency_ms=obj["latency_ms"],
            cached=obj.get("cached", False), coalesced=obj.get("coalesced", False),
            fallback_cause=obj.get("fallback_cause"),
            present_fields=tuple(sorted(obj.keys())),
        )

    def fingerprint(self) -> str:
        return digest({
            "instance_id": self.instance_id, "config_fingerprint": self.config_fingerprint,
            "outcome": self.outcome, "action": self.action, "rule": self.rule,
            "cause": self.cause, "source": self.source,
            "abstained": self.abstained, "confidence": self.confidence,
        })

    def to_dict(self) -> dict[str, Any]:
        return {"instance_id": self.instance_id,
                "config_fingerprint": self.config_fingerprint, "action": self.action,
                "outcome": self.outcome, "rule": self.rule,
                "confidence": self.confidence, "abstained": self.abstained,
                "cause": self.cause, "reason": self.reason, "source": self.source,
                "latency_ms": self.latency_ms, "cached": self.cached,
                "coalesced": self.coalesced, "fallback_cause": self.fallback_cause,
                "present_fields": list(self.present_fields)}

    @classmethod
    def from_dict(cls, value: Any) -> Decision:
        obj = _dict(value, "Decision")
        _fields(obj, "Decision", ("instance_id", "config_fingerprint", "action",
                                  "outcome", "rule", "confidence", "abstained",
                                  "cause", "reason", "source", "latency_ms", "cached",
                                  "coalesced", "fallback_cause", "present_fields"))
        present = obj["present_fields"]
        if not isinstance(present, list):
            raise SchemaError("Decision.present_fields: expected list")
        return cls(
            instance_id=obj["instance_id"],
            config_fingerprint=obj["config_fingerprint"], action=obj["action"],
            outcome=obj["outcome"], rule=obj["rule"], confidence=obj["confidence"],
            abstained=obj["abstained"], cause=obj["cause"], reason=obj["reason"],
            source=obj["source"], latency_ms=obj["latency_ms"], cached=obj["cached"],
            coalesced=obj["coalesced"], fallback_cause=obj["fallback_cause"],
            present_fields=tuple(_str(x, "present_fields[]") for x in present),
        )


def moderate_decision(config: DecisionConfig, message: str, rules: dict[str, str],
                      router=None, *, instance_id: str,
                      **kwargs: Any) -> Decision:
    """Run one declared decision and normalize its result; no hidden defaults."""
    result = moderate(message, rules, config=config.gate, router=router, **kwargs)
    return Decision.from_engine(instance_id, config, result)


@dataclass(frozen=True)
class Scenario:
    """One explicit scripted input for the decision scenario runner."""

    name: str
    message: str
    rules: tuple[tuple[str, str], ...]
    expect_outcome: str | None = None

    def __post_init__(self) -> None:
        _str(self.name, "Scenario.name")
        if not self.name:
            raise SchemaError("Scenario.name: expected non-empty string")
        _str(self.message, "Scenario.message")
        if not isinstance(self.rules, tuple) or any(
                not isinstance(x, tuple) or len(x) != 2
                or any(not isinstance(y, str) for y in x) for x in self.rules):
            raise SchemaError("Scenario.rules: expected tuple of (name, text)")
        if self.expect_outcome is not None and self.expect_outcome not in SCENARIO_OUTCOMES:
            raise SchemaError("Scenario.expect_outcome: outside closed scenario enum")

    def rules_dict(self) -> dict[str, str]:
        return dict(self.rules)


@dataclass(frozen=True)
class RunDecisions:
    schema: int
    mode: str
    config_fingerprint: str
    decisions: tuple[Decision, ...]

    def __post_init__(self) -> None:
        if self.schema != 1:
            raise SchemaError("RunDecisions.schema: only 1 is supported")
        if self.mode != "decision":
            raise SchemaError("RunDecisions.mode: only decision is supported")
        if not isinstance(self.config_fingerprint, str) or len(self.config_fingerprint) != 64:
            raise SchemaError("RunDecisions.config_fingerprint: expected sha256")
        if not self.decisions:
            raise SchemaError("RunDecisions.decisions: empty run")
        if len({d.instance_id for d in self.decisions}) != len(self.decisions):
            raise SchemaError("RunDecisions.decisions: duplicate instance_id")

    def fingerprint(self) -> str:
        return digest([d.fingerprint() for d in self.decisions])

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "mode": self.mode,
                "config_fingerprint": self.config_fingerprint,
                "decisions": [d.to_dict() for d in self.decisions]}

    @classmethod
    def from_dict(cls, value: Any) -> RunDecisions:
        obj = _dict(value, "RunDecisions")
        _fields(obj, "RunDecisions", ("schema", "mode", "config_fingerprint", "decisions"))
        decisions = obj["decisions"]
        if not isinstance(decisions, list):
            raise SchemaError("RunDecisions.decisions: expected list")
        return cls(schema=obj["schema"], mode=obj["mode"],
                   config_fingerprint=obj["config_fingerprint"],
                   decisions=tuple(Decision.from_dict(d) for d in decisions))


def run_scenarios(scenarios: tuple[Scenario, ...], config: DecisionConfig,
                  router=None) -> RunDecisions:
    """Run explicit scenarios; names must be unique. No caching between them."""
    if not scenarios or any(s.name in {x.name for x in scenarios[:-1]}
                            for s in scenarios[1:]):
        raise SchemaError("run_scenarios: duplicate scenario names")
    decisions = tuple(
        moderate_decision(config, s.message, s.rules_dict(), router=router,
                          instance_id=s.name)
        for s in scenarios
    )
    return RunDecisions(schema=1, mode="decision",
                        config_fingerprint=config.fingerprint(), decisions=decisions)


@dataclass(frozen=True)
class PolicyComparisonReport:
    """Side-by-side policy comparison derived from two decision runs."""

    schema: int
    mode: str
    left: str
    right: str
    matches: tuple[str, ...]
    mismatches: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema != 1:
            raise SchemaError("PolicyComparisonReport.schema: only 1 is supported")
        if self.mode != "decision_policy":
            raise SchemaError("PolicyComparisonReport.mode: only decision_policy")

    def fingerprint(self) -> str:
        return digest({"left": self.left, "right": self.right,
                       "matches": list(self.matches), "mismatches": list(self.mismatches),
                       "added": list(self.added), "removed": list(self.removed)})

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "mode": self.mode, "left": self.left,
                "right": self.right, "matches": list(self.matches),
                "mismatches": list(self.mismatches), "added": list(self.added),
                "removed": list(self.removed)}

    @classmethod
    def from_dict(cls, value: Any) -> PolicyComparisonReport:
        obj = _dict(value, "PolicyComparisonReport")
        _fields(obj, "PolicyComparisonReport", ("schema", "mode", "left", "right",
                                                "matches", "mismatches", "added", "removed"))
        return cls(
            schema=obj["schema"], mode=obj["mode"],
            left=_str(obj["left"], "PolicyComparisonReport.left"),
            right=_str(obj["right"], "PolicyComparisonReport.right"),
            matches=tuple(_str(x, "matches[]") for x in obj["matches"]),
            mismatches=tuple(_str(x, "mismatches[]") for x in obj["mismatches"]),
            added=tuple(_str(x, "added[]") for x in obj["added"]),
            removed=tuple(_str(x, "removed[]") for x in obj["removed"]),
        )


def compare_runs(left: RunDecisions, right: RunDecisions) -> PolicyComparisonReport:
    """Compare two decision runs by instance_id; report identity of fingerprints."""
    a = {d.instance_id: d for d in left.decisions}
    b = {d.instance_id: d for d in right.decisions}
    common = set(a) & set(b)
    matches = tuple(sorted(k for k in common
                           if a[k].fingerprint() == b[k].fingerprint()))
    mismatches = tuple(sorted(k for k in common
                              if a[k].fingerprint() != b[k].fingerprint()))
    return PolicyComparisonReport(
        schema=1, mode="decision_policy", left=left.config_fingerprint,
        right=right.config_fingerprint, matches=matches, mismatches=mismatches,
        added=tuple(sorted(set(b) - set(a))),
        removed=tuple(sorted(set(a) - set(b))),
    )


__all__ = [
    "OUTCOMES", "SOURCES", "Decision", "DecisionConfig", "DecisionPolicy",
    "PolicyComparisonReport", "RunDecisions", "Scenario", "compare_runs",
    "moderate_decision", "run_scenarios",
]
