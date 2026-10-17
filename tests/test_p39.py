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


def test_ci_has_dedicated_ruff_job():  # T733
    import re
    text = (WORKFLOWS / "ci.yml").read_text()

    def job(name):
        m = re.search(rf"^  {name}:(.*?)(?=^  \w)", text, re.MULTILINE | re.DOTALL)
        assert m, f"no {name} job"
        return m.group(1)
    # a lint job runs the repo-wide gate on its own — lint failures show
    # up as lint, not as a wall of red matrix legs
    lint = job("lint")
    assert "ruff check ." in lint and "pytest" not in lint
    # and the test matrix doesn't duplicate the work (T733 dedupe)
    assert "ruff" not in job("test")


def test_ci_weightless_docs_cli_job():  # T734
    import re
    text = (WORKFLOWS / "ci.yml").read_text()
    m = re.search(r"^  weightless:(.*?)(?=^  \w)", text, re.MULTILINE | re.DOTALL)
    assert m, "no weightless job"
    job = m.group(1)
    # the label names what it runs: docs-consistency + CLI tests
    for f in ("tests/test_p22.py", "tests/test_cli.py",
              "tests/test_p18.py", "tests/test_p29.py"):
        assert f in job, f
    # and it genuinely runs without weights: no laya, no full install —
    # just enough to import serve (fastapi/pydantic) alongside stdlib
    assert "laya" not in job and ".[dev]" not in job
    assert 'pip install pytest "fastapi>=0.110"' in job
    assert "PYTHONPATH=src" in job


def test_ci_wheel_artifact_on_tags():  # T735
    text = (WORKFLOWS / "publish.yml").read_text()
    # tags trigger the workflow, and the wheel is built and uploaded —
    # disjoint globs so the sdist artifact can't swallow the wheel
    assert 'tags: ["v*"]' in text
    assert "python -m build --wheel" in text
    assert "name: wheel" in text and "dist/*.whl" in text
    assert "dist/*.tar.gz" in text
    assert "path: dist/* }" not in text, "undifferentiated artifact glob"


def test_ci_release_attaches_wheel_and_sbom():  # T736
    import re
    text = (WORKFLOWS / "publish.yml").read_text()
    m = re.search(r"^  release:(.*?)(?=^  \w|\Z)", text, re.MULTILINE | re.DOTALL)
    assert m, "no release job"
    job = m.group(1)
    # it runs after the build and attaches exactly the box's two files
    assert "needs: sdist" in job
    assert "gh release create" in job
    assert "dist/*.whl" in job and "dist/sbom.json" in job
    # the write is explicitly permitted, and only for it
    assert "contents: write" in job
    # re-runs stay idempotent: an existing release gets --clobber uploads
    assert "--clobber" in job
    assert "GH_TOKEN" in job


def test_ci_tag_must_match_pyproject():  # T737
    import subprocess
    import sys

    import tomllib
    text = (WORKFLOWS / "publish.yml").read_text()
    assert 'python scripts/check_tag.py "$GITHUB_REF_NAME"' in text
    with open("pyproject.toml", "rb") as f:
        ver = tomllib.load(f)["project"]["version"]

    def run(*args):
        return subprocess.run([sys.executable, "scripts/check_tag.py", *args],
                              check=False, capture_output=True, text=True,
                              timeout=30)
    # the current version passes with and without the v prefix...
    assert run(f"v{ver}").returncode == 0
    assert run(ver).returncode == 0
    # ...a mismatch refuses the release, naming both sides...
    r = run("v9.9.9")
    assert r.returncode == 1
    assert "E_TAG" in r.stderr and "9.9.9" in r.stderr and ver in r.stderr
    # ...and a missing tag is a usage error, not a silent pass
    assert run().returncode == 2
