"""Unit tests, no weights. One stub router shared."""
import sys
sys.path.insert(0, "src")

from gatekeeper import GateConfig


def test_config_defaults():  # T111
    c = GateConfig()
    assert (c.allow_threshold, c.delete_threshold) == (0.85, 0.85)
    assert c.max_rules == 12 and c.history_n == 4
