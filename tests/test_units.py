"""Unit tests, no weights. One stub router shared."""
import sys
sys.path.insert(0, "src")

from gatekeeper import GateConfig
from gatekeeper.rules import RuleError, validate_rules


def test_rejects_bad_ids():  # T112
    for bad in [{"BAD": "x"}, {"a b": "x"}, {"x" * 25: "y"}]:
        try:
            validate_rules(bad)
        except RuleError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_config_defaults():  # T111
    c = GateConfig()
    assert (c.allow_threshold, c.delete_threshold) == (0.85, 0.85)
    assert c.max_rules == 12 and c.history_n == 4
