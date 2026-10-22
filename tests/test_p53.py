"""P53 receipts (T1011+): release 0.5.0 and the batch that ships it.

T1011 — pkg: version 0.5.0. The bump is a set of linked claims, each
falsifiable here: pyproject == __version__ == "0.5.0", the CHANGELOG
carries a dated 0.5.0 section (T624 also enforces presence; T819's
release sweep demands the dated heading shape, which forced the dating
to happen at this bump — T1016 owns the notes), every shipped docs
page's freshness marker reads v0.5.0 (T809/T1005 pin marker == pyproject
version — flipping all 23 is what keeps them green after the bump), and
the countable claims the T1011 per-page re-check spot-verified stay true
against source. drafts/ pages stay markerless by design (T809).
"""
import pathlib
import re

DOCS = sorted(pathlib.Path("docs").glob("*.md"))


def test_t1011_version_triplet_and_changelog_stub():
    m = re.search(r'^version = "([^"]+)"',
                  pathlib.Path("pyproject.toml").read_text(), re.MULTILINE)
    assert m and m.group(1) == "0.5.0", \
        "pyproject must read 0.5.0 at the T1011 bump"
    import gatekeeper
    assert gatekeeper.__version__ == "0.5.0", "__version__ drifts from bump"
    changelog = pathlib.Path("CHANGELOG.md").read_text()
    m = re.search(r"^## 0\.5\.0 — \d{4}-\d{2}-\d{2} \(T1016\)$",
                  changelog, re.MULTILINE)
    assert m, \
        "0.5.0 needs the dated heading T819 demands (T1016 owns its notes)"


def test_t1011_every_shipped_page_flipped_to_v050():
    for f in DOCS:
        text = f.read_text()
        n = text.count("_(Last checked against v0.5.0.)_")
        assert n == 1, f"{f}: expected exactly one v0.5.0 marker, got {n}"
    for f in pathlib.Path("docs/drafts").glob("*.md"):
        assert "Last checked against" not in f.read_text(), \
            f"{f}: drafts stay markerless by design"


def test_t1011_recheck_spotclaims_match_source():
    # the T1011 re-check read these countable claims page-by-page and
    # verified each against source; drift in either direction goes red here
    serve = pathlib.Path("src/gatekeeper/serve.py").read_text()
    m = re.search(r"^MAX_BATCH = (\d+)", serve, re.MULTILINE)
    assert m and m.group(1) == "32", "batch cap no longer 32"
    threat = pathlib.Path("docs/threat-model.md").read_text()
    assert "≤32 messages → 413" in threat, "threat-model batch claim drifts"
    config = pathlib.Path("src/gatekeeper/config.py").read_text()
    assert "max_rules: int = 12" in config, "rule cap no longer 12"
    guide = pathlib.Path("docs/rule-guide.md").read_text()
    assert "≤12 rules" in guide, "rule-guide cap claim drifts"
    arch = pathlib.Path("docs/architecture.md").read_text()
    assert "5 questions, 1 pass" in arch, "architecture pass claim drifts"
    versions = pathlib.Path("docs/versions.md").read_text()
    assert "**0.5.0** (`pyproject.toml`, `bouncer --version`)" in versions, \
        "versions.md current-version claim must track the bump"
