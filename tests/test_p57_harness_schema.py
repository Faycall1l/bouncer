"""P57 tests (T1234-T1235): strict paired-evaluation records."""
import json

import pytest

from eval.harness.manifest import DatasetManifest, build_manifest
from eval.harness.schema import (
    DecisionTrace,
    GoldPolicy,
    Outcome,
    PairOutcome,
    SchemaError,
    TaskSpec,
    digest,
)

POLICY = GoldPolicy("delete", "allow", "delete", "escalate")
CONFIG = {"allow_threshold": 0.85, "delete_threshold": 0.85, "questions": 5}


def _row() -> dict:
    return {
        "v": 1,
        "state": {
            "message": "spoiler alert",
            "history": ["a: hi"],
            "rules": {"no-spam": "no ads", "no-spoiler": "no plot spoilers"},
        },
        "labels": {"rule": "no-spoiler", "harm": "suspicious", "hype": "chill",
                   "jailbreak": False, "escalate": False},
    }


def _outcome(router: str = "base") -> Outcome:
    return Outcome(
        router=router, action="delete", rule="no-spoiler", confidence=0.9,
        abstained=False, latency_ms=1.25,
        trace=DecisionTrace("model", "violation", "VIOLATION_DELETE", 1,
                            None, ()),
    )


def test_gold_policy_is_declared_and_ordered():  # T1234
    assert POLICY.gold_action({"rule": "ok", "jailbreak": False,
                               "escalate": False}) == "allow"
    assert POLICY.gold_action({"rule": "be-kind", "jailbreak": False,
                               "escalate": False}) == "delete"
    assert POLICY.gold_action({"rule": "ok", "jailbreak": True,
                               "escalate": True}) == "delete"
    strict = GoldPolicy("delete", "allow", "flag", "escalate",
                        ("escalate", "jailbreak", "violation", "ok"))
    assert strict.gold_action({"rule": "ok", "jailbreak": True,
                               "escalate": True}) == "escalate"
    with pytest.raises(SchemaError):
        GoldPolicy("maybe", "allow", "delete", "escalate")


def test_task_spec_from_row_is_strict_and_deterministic():  # T1234
    spec = TaskSpec.from_data_row(_row(), dataset="fixture", split="dev",
                                  policy=POLICY, config=CONFIG)
    assert spec.gold_action == "delete"
    assert spec.gold_rule == "no-spoiler"
    assert spec.lang is None  # declared, not inferred
    assert spec.fingerprint() == TaskSpec.from_dict(spec.to_dict()).fingerprint()
    assert spec.config_fingerprint() == digest(CONFIG)
    with pytest.raises(SchemaError, match="unknown keys"):
        TaskSpec.from_dict({**spec.to_dict(), "extra": 1})


def test_variant_reverses_order_without_changing_labels():  # T1234
    spec = TaskSpec.from_data_row(_row(), dataset="fixture", split="dev",
                                  policy=POLICY, config=CONFIG)
    flip = spec.with_variant("reversed_rules")
    assert list(flip.rules) == ["no-spoiler", "no-spam"]
    assert flip.gold_action == spec.gold_action
    assert flip.fingerprint() != spec.fingerprint()
    assert flip.instance_id == f"{spec.task_id}:reversed_rules"


def test_outcome_requires_every_field_including_cause():  # T1234
    result = {"action": "delete", "rule": "no-spoiler", "confidence": 0.9,
              "abstained": False, "latency_ms": 1.0, "cause": "violation"}
    out = Outcome.from_moderate("base", result, source="model",
                                decision_path="VIOLATION_DELETE", attempts=1)
    assert out.decision_digest() == Outcome.from_dict(out.to_dict()).decision_digest()
    del result["cause"]
    with pytest.raises(SchemaError, match="missing 'cause'"):
        Outcome.from_moderate("base", result, source="model",
                              decision_path="VIOLATION_DELETE", attempts=1)


def test_pair_outcome_pins_both_routers_and_spec():  # T1234
    spec = TaskSpec.from_data_row(_row(), dataset="fixture", split="dev",
                                  policy=POLICY, config=CONFIG)
    pair = PairOutcome(
        task_id=spec.task_id, instance_id=spec.instance_id, variant=spec.variant,
        spec_hash=spec.fingerprint(), config_hash=spec.config_fingerprint(),
        base=_outcome("base"), candidate=_outcome("candidate"),
    )
    clone = PairOutcome.from_dict(json.loads(json.dumps(pair.to_dict())))
    assert clone == pair
    with pytest.raises(SchemaError, match="instance_id"):
        PairOutcome.from_dict({**pair.to_dict(), "instance_id": "wrong"})


def test_manifest_pins_bytes_rows_and_context(tmp_path):  # T1235
    data = tmp_path / "fixture.jsonl"
    data.write_text(json.dumps(_row()) + "\n" + json.dumps(_row()) + "\n")
    man = build_manifest(
        data, dataset_id="fixture", split="dev", policy=POLICY.to_dict(),
        config=CONFIG, git_sha="abc123", seed=7,
    )
    assert man.split.n == 2
    assert man.fingerprint() == DatasetManifest.from_dict(
        json.loads(json.dumps(man.to_dict()))).fingerprint()
    # One byte of drift changes the file hash even when row count is unchanged.
    before = man.file_sha256
    data.write_text(data.read_text() + "\n")
    drifted = build_manifest(data, dataset_id="fixture", split="dev",
                             policy=POLICY.to_dict(), config=CONFIG,
                             git_sha="abc123", seed=7)
    assert drifted.file_sha256 != before
    assert drifted.split.rows_sha256 == man.split.rows_sha256  # blank line ignored

    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")
    with pytest.raises(SchemaError, match="empty dataset"):
        build_manifest(empty, dataset_id="fixture", split="dev",
                       policy=POLICY.to_dict(), config=CONFIG,
                       git_sha="abc123", seed=7)

    # A row-level split declaration must agree with the caller's provenance.
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({**_row(), "split": "test"}) + "\n")
    with pytest.raises(SchemaError, match="split does not match"):
        build_manifest(bad, dataset_id="fixture", split="dev",
                       policy=POLICY.to_dict(), config=CONFIG,
                       git_sha="abc123", seed=7)
