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


def test_rejects_empty_text():  # T113
    try:
        validate_rules({"a": "   "})
    except RuleError:
        return
    raise AssertionError("accepted empty text")


def test_rejects_too_many():  # T114
    try:
        validate_rules({f"r{i}": "some rule text" for i in range(13)})
    except RuleError as e:
        assert "13 rules" in str(e)
        return
    raise AssertionError("accepted 13 rules")


def test_rejects_ok():  # T115
    try:
        validate_rules({"ok": "whatever"})
    except RuleError as e:
        assert "reserved" in str(e)
        return
    raise AssertionError("accepted ok")


def test_presets():  # T116
    from gatekeeper import get_preset, list_presets
    for name in list_presets():
        assert len(get_preset(name)) >= 3, name


def test_detectors():  # T117+T118+T119
    from gatekeeper.normalize import caps_flood, emoji_flood, extract_links
    assert caps_flood("STOP DOING THAT RIGHT NOW OK")
    assert not caps_flood("Good game all")
    assert emoji_flood("🔥" * 12)
    assert extract_links("click http://x.gg/abc now") == ["http://x.gg/abc"]


def test_config_defaults():  # T111
    c = GateConfig()
    assert (c.allow_threshold, c.delete_threshold) == (0.85, 0.85)
    assert c.max_rules == 12 and c.history_n == 4
