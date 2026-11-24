"""P63 tests (T1249): harness docs and fixtures have real receipts."""
import json
from pathlib import Path

import pytest

from eval.harness.decision import DecisionPolicy
from eval.harness.manifest import build_manifest
from eval.harness.schema import SchemaError
from gatekeeper import GateConfig


def test_docs_and_fixtures_are_real_not_stubs():  # T1249
    docs = Path("docs/harness.md").read_text()
    assert "Closed outcome enum" in docs
    assert "eval/reports/fixture-manifest.json" in docs
    policy_path = Path("eval/harness/fixtures/policy.json")
    cfg_path = Path("eval/harness/fixtures/config.json")
    policy = DecisionPolicy.from_dict(json.loads(policy_path.read_text()))
    assert policy.name == "prod"
    cfg = GateConfig.from_dict(json.loads(cfg_path.read_text()))
    assert cfg.allow_threshold == 0.85


def test_manifest_fixture_builds(tmp_path):  # T1249 smoke
    row = {
        "v": 1,
        "state": {"message": "hi", "history": [], "rules": {"no-spam": "no links"}},
        "labels": {"rule": "ok", "harm": "safe", "hype": "chill",
                   "jailbreak": False, "escalate": False},
    }
    data = tmp_path / "row.jsonl"
    data.write_text(json.dumps(row) + "\n")
    man = build_manifest(data, dataset_id="fixture", split="dev", policy={},
                         config=GateConfig().to_dict(), git_sha="abc123", seed=7)
    assert man.split.n == 1


def test_decision_policy_fixture_is_strict():  # T1249
    with pytest.raises(SchemaError, match="error is reserved"):
        DecisionPolicy.from_dict({
            "name": "x", "outcomes": ["error"], "sources": ["model"],
            "require_cause": True, "require_reason": True, "require_source": True,
        })
