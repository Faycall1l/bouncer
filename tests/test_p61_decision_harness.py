"""P61 tests (T1241-T1243): closed decision outcomes, traces, scenarios."""
from dataclasses import replace

import pytest

from eval.harness.decision import (
    Decision,
    DecisionConfig,
    DecisionPolicy,
    Scenario,
    compare_runs,
    moderate_decision,
    run_scenarios,
)
from eval.harness.schema import SchemaError
from gatekeeper import GateConfig

POLICY = DecisionPolicy(
    name="test-policy", outcomes=("allow", "delete", "flag", "escalate", "abstain"),
    sources=("model", "cache", "fastpath", "empty", "breaker", "fallback", "coalesced"),
)
CONFIG = DecisionConfig(name="test-config", policy=POLICY,
                        gate=GateConfig(allow_threshold=0.85, delete_threshold=0.85,
                                        questions=5))


class OkRouter:
    def predict(self, state, questions):
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95,
                     "probabilities": {"ok": 0.95, "no-spam": 0.05}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0},
        }}


def test_decision_policy_is_closed_and_explicit():  # T1241
    assert POLICY.outcomes and "error" not in POLICY.outcomes
    assert POLICY.sources and "unknown" not in POLICY.sources
    assert POLICY.to_dict() == DecisionPolicy.from_dict(POLICY.to_dict()).to_dict()
    with pytest.raises(SchemaError, match="error is reserved for failures"):
        DecisionPolicy(name="x", outcomes=("error",), sources=("model",))
    with pytest.raises(SchemaError, match="duplicates"):
        DecisionPolicy(name="x", outcomes=("allow", "allow"), sources=("model",))
    with pytest.raises(SchemaError, match="unknown keys"):
        DecisionPolicy.from_dict({**POLICY.to_dict(), "extra": 1})


def test_decision_config_is_explicit():  # T1241
    assert DecisionConfig.from_dict(CONFIG.to_dict()) == CONFIG
    assert CONFIG.fingerprint() == DecisionConfig.from_dict(CONFIG.to_dict()).fingerprint()
    bad = CONFIG.to_dict()
    bad.pop("gate")
    with pytest.raises(SchemaError, match="missing keys"):
        DecisionConfig.from_dict(bad)


def test_moderate_decision_records_closed_outcome_and_trace():  # T1242
    d = moderate_decision(CONFIG, "hello there", {"no-spam": "no links"}, router=OkRouter(),
                          instance_id="benign")
    assert d.outcome == "allow"
    assert d.source in POLICY.sources
    assert d.cause and d.reason
    assert {"action", "rule", "confidence", "abstained", "cause", "reason", "source",
            "latency_ms"}.issubset(set(d.present_fields))
    assert d.fingerprint() == Decision.from_dict(d.to_dict()).fingerprint()


def test_decision_rejects_engine_result_without_cause():  # T1242
    result = {"action": "allow", "rule": "ok", "confidence": 0.95, "abstained": False,
              "reason": "ok", "latency_ms": 0.1, "source": "model"}
    with pytest.raises(SchemaError, match="missing cause"):
        Decision.from_engine("x", CONFIG, result)
    with pytest.raises(SchemaError, match="outside closed enum"):
        Decision.from_engine("x", CONFIG, {**result, "action": "weird",
                                           "cause": "ok", "source": "model"})


def test_scenario_runner_and_policy_comparison_are_explicit():  # T1241-T1243
    a = Scenario(name="a", message="hello", rules=(("no-spam", "no links"),))
    b = Scenario(name="b", message="spam now",
                 rules=(("no-spam", "no links"),), expect_outcome="allow")
    run = run_scenarios((a, b), CONFIG, router=OkRouter())
    assert [d.instance_id for d in run.decisions] == ["a", "b"]
    assert run.fingerprint() == type(run).from_dict(run.to_dict()).fingerprint()
    other = replace(run, decisions=(run.decisions[0],
                                    replace(run.decisions[1], outcome="delete")))
    report = compare_runs(run, other)
    assert report.matches == ("a",)
    assert report.mismatches == ("b",)
    assert report.fingerprint() == type(report).from_dict(report.to_dict()).fingerprint()
    with pytest.raises(SchemaError, match="duplicate scenario names"):
        run_scenarios((a, Scenario(name="a", message="x", rules=())), CONFIG,
                      router=OkRouter())
    with pytest.raises(SchemaError, match="outside closed scenario enum"):
        Scenario(name="c", message="x", rules=(), expect_outcome="error")
