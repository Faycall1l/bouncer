"""P65 tests (T1252-T1254): README modernization is test-pinned."""
from pathlib import Path


def test_readme_modernized_scope_and_stale_template_claims():  # T1252/T1253
    readme = Path("README.md").read_text()
    assert "![System architecture](docs/assets/system-architecture.svg)" in readme
    assert "TEMPLATE/STALE" in readme
    assert "0.305" in readme and "0.403" in readme
    assert "not live-chat results" in readme or "not live-chat claims" in readme
    assert "The 0.403 baseline is a template measurement" in readme


def test_readme_points_to_modernized_research_report():  # T1252/T1253
    readme = Path("README.md").read_text()
    assert "reports/Jev System One research.md" in readme
    assert "Evidence hierarchy" not in readme  # lives in the report, not a blurb
