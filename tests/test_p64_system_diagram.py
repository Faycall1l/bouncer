"""P65 tests (T1251): the README has a real system architecture diagram."""
from pathlib import Path


def test_system_architecture_is_present_and_linked():  # T1251
    svg = Path("docs/assets/system-architecture.svg").read_text()
    assert svg.startswith("<svg")
    components = ("User / HTTP", "Cache + fastpath", "Decision core",
                  "Audit + stats + appeal",
                  "Terminal: allow / delete / flag / escalate")
    for component in components:
        assert component in svg
    assert "<animate" in svg  # smooth movement, not a hand-drawn diagram
    readme = Path("README.md").read_text()
    assert "![System architecture](docs/assets/system-architecture.svg)" in readme


def test_system_diagram_does_not_claim_model_quality_evidence():  # T1251
    svg = Path("docs/assets/system-architecture.svg").read_text()
    for banned in ("calibrated", "state-of-the-art", "robust", "safer than", "Jev is fast"):
        assert banned.lower() not in svg.lower()
