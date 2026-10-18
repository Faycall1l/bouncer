"""P43 tests (T811-T830): the 0.4.0 release itself. Weightless."""
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")


def _pyproject_version() -> str:
    m = re.search(r'^version = "([^"]+)"',
                  Path("pyproject.toml").read_text(), re.MULTILINE)
    assert m, "no version in pyproject.toml"
    return m.group(1)


def test_version_strings_consistent_everywhere():  # T819
    """Every surface that claims the CURRENT version agrees with pyproject.

    T624 covers pkg == pyproject == CHANGELOG section; T809 covers the
    per-page freshness markers. This sweep takes the rest: the README
    doctor example, versions.md's "currently" claim, and the CHANGELOG
    heading shape (dated + ticket-suffixed, not just present).
    """
    import gatekeeper
    version = _pyproject_version()
    assert gatekeeper.__version__ == version, \
        "pyproject version drifts from __version__"
    # CHANGELOG: a DATED section for the current version (T816 format)
    changelog = Path("CHANGELOG.md").read_text()
    m = re.search(rf"^## {re.escape(version)} — (\d{{4}}-\d{{2}}-\d{{2}}) "
                  rf"\(T\d+\)$", changelog, re.MULTILINE)
    assert m, f"no dated `## {version} — YYYY-MM-DD (Txxx)` section"
    assert m.group(1) <= "2026-12-31", "section dated in the future?"
    # the Unreleased heading stays above every released section
    assert changelog.index("## Unreleased") < changelog.index(f"## {version}")
    # README doctor example: the env line prints the package version
    readme = Path("README.md").read_text()
    assert f"bouncer: {version}" in readme, \
        "README doctor example shows a stale version"
    # versions.md: the "currently package version" claim
    vnotes = Path("docs/versions.md").read_text()
    assert f"currently package version\n**{version}**" in vnotes, \
        "versions.md 'currently' claim drifted"
