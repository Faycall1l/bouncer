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


def test_config_ranges():  # T253+T254+T255
    from gatekeeper import moderate
    from gatekeeper.config import ConfigError, GateConfig
    with pytest.raises(ConfigError, match="E_CONFIG"):
        GateConfig(allow_threshold=1.5)
    with pytest.raises(ConfigError, match="E_CONFIG"):
        GateConfig(timeout_s=0)
    with pytest.raises(ConfigError, match="E_CONFIG"):
        moderate("hi", {"a": "rule a text"}, threshold=2.0)


def test_error_str_has_code():  # T257
    from gatekeeper import BouncerError, ModelError
    assert str(ModelError("boom")) == "E_MODEL: boom"
    assert BouncerError().code in str(BouncerError())
