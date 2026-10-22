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


def test_t1018_readme_version_sensitive_claims_match_source():  # T1018
    """T1018: README's release-sensitive claims re-checked against source.

    What a release changes: the version stamp in the doctor sample (T819
    sweeps this too — re-asserted here as the box's own receipt), the
    commands P46-P51 added to the quickstart, and the request limits a
    server upgrade makes observable. Out of scope, checked and left
    alone: `K=3-12` and the T4-era benchmark rows are byte-identical at
    v0.4.0 (`git show v0.4.0:README.md`), so they are model-era claims,
    not version claims."""
    readme = pathlib.Path("README.md").read_text()
    assert "bouncer: 0.5.0" in readme, "doctor sample lost the bump"
    assert "bouncer: 0.4.0" not in readme, "stale version in doctor sample"
    serve = pathlib.Path("src/gatekeeper/serve.py").read_text()
    config = pathlib.Path("src/gatekeeper/config.py").read_text()
    cli = pathlib.Path("src/gatekeeper/cli.py").read_text()
    # request limits the README states, each against its constant
    assert "≤32 messages" in readme and "MAX_BATCH = 32" in serve
    assert "≤8000 chars" in readme and "len(req.message) > 8000" in serve
    assert "cap at 20 items" in readme and "MAX_CONTEXT = 20" in serve
    assert "over 1 MB are 413" in readme and "MAX_BODY = 1_000_000" in serve
    assert "`Retry-After: 60`" in readme and '"Retry-After": "60"' in serve
    # gate defaults the README's example decision quotes
    assert "conf≥0.85" in readme
    assert "allow_threshold: float = 0.85" in config
    assert "delete_threshold: float = 0.85" in config
    # the K upper bound in the qid table is the enforced rule cap
    assert "K=3-12" in readme and "max_rules: int = 12" in config
    # P46-P51 quickstart lines — every one a real subparser or flag
    for shown, source in (
            ("bouncer adjudicate ROW_ID", 'add_parser("adjudicate"'),
            ("bouncer amnesty USER", 'add_parser("amnesty"'),
            ("bouncer config validate", 'add_parser("validate"'),
            ("bouncer completion bash", 'add_parser("completion"'),
            ("bouncer check --file", '"--file"'),
            ("bouncer export --queue", '"--queue"'),
    ):
        assert shown in readme, f"README dropped {shown!r}"
        assert source in cli, f"source lost {source!r} README shows"
