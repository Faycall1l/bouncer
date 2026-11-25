"""P66 tests (T1258): SVG animation is smooth, template-based, and indefinite."""
from pathlib import Path


def test_animation_docs_and_templates_are_recorded():  # T1258
    text = Path("docs/animation.md").read_text()
    assert "Loop with hold phase" in text
    assert "repeatCount=\"indefinite\"" in text
    assert "MDN" in text and "WaterTian/svg-motion-cookbook" in text
    assert "Loop with hold phase" in text
    assert "docs/assets/system-architecture.svg" in text
    assert "docs/assets/gate-precedence.svg" in text
    readme = Path("README.md").read_text()
    assert "![System architecture](docs/assets/system-architecture.svg)" in readme


def test_system_architecture_is_smooth_and_not_one_shot():  # T1258
    svg = Path("docs/assets/system-architecture.svg").read_text()
    assert "<animateMotion" in svg
    assert 'repeatCount="indefinite"' in svg
    assert "<script" not in svg
    assert 'dur="9s"' in svg
    assert svg.index("<circle") < svg.index("<animateMotion")


def test_gate_precedence_uses_hold_phase_and_indefinite_loop():  # T1258
    svg = Path("docs/assets/gate-precedence.svg").read_text()
    assert 'keyTimes="0;0.45;0.85;1"' in svg
    assert 'repeatCount="indefinite"' in svg
    assert "<script" not in svg
