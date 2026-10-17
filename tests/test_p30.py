"""P30 tests (T551-T570): demo helpers. No gradio, no weights."""
import sys

sys.path.insert(0, "src")

from gatekeeper.demo_app import (
    format_meters,
    format_trail,
    parse_severity,
    remember_thr,
)


def test_format_meters():  # T561
    r = {"harm": "safe", "jailbreak_p": 0.01, "escalate_p": 0.02, "abstained": False,
         "margin": 0.4, "script": "latin", "cause": "violation"}
    text = format_meters(r)
    assert "harm=safe" in text and "margin=0.4" in text and "cause=violation" in text
    with_st = format_meters(r, {"strikes": 2, "suggest_ban": False})
    assert "strikes=2" in with_st and "\nstrikes=2" in with_st


def test_format_trail():  # T562
    trail = [f"row{i}" for i in range(20)]
    text = format_trail(trail, [10.0, 20.0, 30.0])
    assert text.startswith("session: 3 decisions, p50 20.0ms")  # median index len//2
    assert "row19" in text and "row0" not in text  # last 8 only
    assert format_trail([], []).startswith("session: 0 decisions")


def test_remember_thr():  # T563
    mem: dict = {}
    assert remember_thr(mem, "", "gaming", 0.9, 0.9) == (0.85, 0.85)  # defaults
    got = remember_thr(mem, "gaming", "study", 0.91, 0.77)
    assert mem == {"gaming": (0.91, 0.77)} and got == (0.85, 0.85)
    got = remember_thr(mem, "study", "gaming", 0.6, 0.6)
    assert got == (0.91, 0.77)  # restored


def test_parse_severity():  # T564 (helper shipped with T559)
    assert parse_severity("no-scams=high\nplain-chat=low") == {
        "no-scams": "high", "plain-chat": "low"}
    assert parse_severity("junk line\n=high\nrule=banana\n") == {}  # junk skipped
    assert parse_severity("") == {} and parse_severity(None) == {}
