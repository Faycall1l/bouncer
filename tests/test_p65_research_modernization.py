"""P65 tests (T1252-T1254): research modernization is test-pinned."""
from pathlib import Path


def test_research_report_has_provenance_limits_and_agenda():  # T1252
    text = Path("reports/Jev System One research.md").read_text()
    assert "Evidence hierarchy" in text
    assert "STALE" in text
    assert "real receipt" in text.lower()
    assert "mode:\"real\"" in text or "mode: \"real\"" in text or "real receipt" in text.lower()
    assert "9 of 11 agent decision points" in text
    assert "+10.8 to +46.0 percentage points" in text
    assert "30.3% of Laya's answers flipped" in text


def test_research_report_is_honest_about_limits():  # T1252
    text = Path("reports/Jev System One research.md").read_text()
    for banned in ("state-of-the-art", "robust", "Jev is calibrated", "Jev is faster"):
        assert banned.lower() not in text.lower(), banned


def test_readme_points_to_modernized_research_and_system_diagram():  # T1253
    readme = Path("README.md").read_text()
    assert "![System architecture](docs/assets/system-architecture.svg)" in readme
    assert "modernized" in readme.lower()
    assert "reports/Jev System One research.md" in readme
