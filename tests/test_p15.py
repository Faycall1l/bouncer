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


def test_error_paths():  # T258+T260+T261+T266+T267+T268
    import warnings

    import gatekeeper
    from gatekeeper import GateConfig, moderate
    from gatekeeper.rules import warn_overlapping
    gatekeeper._router = object()  # initialized: kwargs now warn
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            gatekeeper.get_router(checkpoint="nope")
        assert any("ignoring" in str(x.message) for x in w)
    finally:
        gatekeeper._router = None
    try:
        validate_rules({"a": 123})
    except RuleError as e:
        assert "int" in str(e)
    else:
        raise AssertionError("accepted int rule text")
    many = {f"r{i}": "shared words here always same text block" for i in range(8)}
    assert len(warn_overlapping(many)) <= 10
    cfg = GateConfig(timeout_s=0.05)

    class Slow:
        def predict(self, state, questions):
            import time as _t
            _t.sleep(0.4)
            raise AssertionError("unreachable")
    r = moderate("p15 slow timeout msg", {"plain-chat": "normal talk"},
                 config=cfg, router=Slow())
    assert r["action"] == "escalate" and "timed out" in r["reason"]
