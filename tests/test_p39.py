"""P39 tests (T731-T750): CI/CD. Workflow wiring is pinned textually — no
PyYAML in the weightless test env; T750 runs the real parser where one
exists."""
from pathlib import Path

WORKFLOWS = Path(".github/workflows")


def test_ci_workflow_runs_pytest_and_ruff_on_push_and_pr():  # T731
    text = (WORKFLOWS / "ci.yml").read_text()
    # triggers: every push and every PR gets the gate
    assert "push" in text and "pull_request" in text
    # the box's contract: pytest and ruff both run...
    assert "pytest -q" in text
    assert "ruff check ." in text
    # ...and only once — the repo-wide gate supersedes the old src/tests
    # subset (T731 found the duplicate step and removed it)
    assert "ruff check src tests" not in text
    # matrix legs report independently (T741 makes it explicit later; the
    # default fail-fast is on, so pin the current legs at least)
    for v in ("3.10", "3.11", "3.12", "3.13"):
        assert f'"{v}"' in text, v


def test_ci_python_matrix_tracks_classifiers():  # T732
    import re

    import tomllib
    text = (WORKFLOWS / "ci.yml").read_text()
    m = re.search(r"python-version:\s*\[([^\]]+)\]", text)
    assert m, "no python matrix in ci.yml"
    legs = sorted(x.strip().strip('"') for x in m.group(1).split(","))
    with open("pyproject.toml", "rb") as f:
        py = tomllib.load(f)
    minors = sorted(c.rsplit(" ", 1)[1] for c in py["project"]["classifiers"]
                    if c.startswith("Programming Language :: Python :: 3."))
    # the CI legs and the trove classifiers are the same claim — adding a
    # version to one without the other is drift, and fails here (T732)
    assert legs == minors, (legs, minors)
