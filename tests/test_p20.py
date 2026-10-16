"""P20 tests (T351-T370): demo logic without gradio installed."""
import sys

sys.path.insert(0, "src")


def _space_body():
    with open("app/app.py") as f:
        text = f.read()
    assert text.startswith("---")  # HF frontmatter first
    _, _, body = text.split("---", 2)
    return compile(body, "app/app.py", "exec")


def test_space_entry_import_safe():  # T364: frontmatter + __main__ guard, no gradio import
    from gatekeeper.demo_app import launch, parse_rules, review_entry
    assert callable(launch) and parse_rules("a: rule a\nbad line") == {"a": "rule a"}
    assert review_entry("m", {"action": "flag", "rule": "r", "confidence": 0.81}) == {
        "message": "m", "action": "flag", "rule": "r", "conf": 0.81, "ms": 0.0}
    _space_body()  # compiles: import line + __main__ guard only


def test_badge_mapping():  # T370
    from gatekeeper.demo_app import action_badge
    assert action_badge("allow") == "🟢 ALLOW"
    assert action_badge("escalate") == "⚪ ESCALATE"
    try:
        action_badge("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown action needs a loud failure")
