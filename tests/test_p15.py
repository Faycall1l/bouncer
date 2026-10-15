"""P15 tests (T251-T270): robustness + errors. No weights."""
import sys

sys.path.insert(0, "src")

import pytest

from gatekeeper.rules import RuleError, validate_rules


def test_severity_values():  # T251
    validate_rules({"a": "rule a text"}, severity={"a": "high"})
    with pytest.raises(RuleError, match="E_RULES_SEVERITY"):
        validate_rules({"a": "rule a text"}, severity={"a": "medium"})


def test_severity_unknown_rule():  # T252
    with pytest.raises(RuleError, match="unknown rule"):
        validate_rules({"a": "rule a text"}, severity={"zzz": "high"})
