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
    # matrix legs list every supported version (T732 pins them equal to
    # the classifiers; T741 pins fail-fast off so they all report)
    for v in ("3.10", "3.11", "3.12", "3.13"):
        assert f'"{v}"' in text, v


def test_ci_python_matrix_tracks_classifiers():  # T732
    import re

    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11: the tomli backport (T814)
        import tomli as tomllib
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
    # it runs after the build job and attaches exactly the box's two files
    assert "needs: build" in job  # T750: the job builds both, not just sdist
    assert "gh release create" in job
    assert "dist/*.whl" in job and "dist/sbom.json" in job
    # the write is explicitly permitted, and only for it
    assert "contents: write" in job
    # T830: gh release create needs a git repo (--verify-tag,
    # --generate-notes diffs tags) — the job must check out first
    assert "actions/checkout" in job, "release job has no checkout (T830 bug)"
    assert "fetch-depth: 0" in job, "generate-notes needs full tag history"
    # re-runs stay idempotent: an existing release gets --clobber uploads
    assert "--clobber" in job
    assert "GH_TOKEN" in job


def test_ci_tag_must_match_pyproject():  # T737
    import subprocess
    import sys

    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11: the tomli backport (T814)
        import tomli as tomllib
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


def test_ci_benchmark_job_posts_summary(tmp_path):  # T738
    import json
    import re
    import subprocess
    import sys
    ci = (WORKFLOWS / "ci.yml").read_text()
    m = re.search(r"^  bench:(.*?)(?=^  \w|\Z)", ci, re.MULTILINE | re.DOTALL)
    assert m, "no bench job"
    job = m.group(1)
    # weightless by construction: the stub benches, never the model, and
    # results are POSTED (step summary) — no thresholds to flake on
    assert "bench_stub.py" in job and "bench_pool.py" in job
    assert "GITHUB_STEP_SUMMARY" in job
    # optional: manual dispatch exists, and PRs don't run it unfiltered
    assert "workflow_dispatch" in ci
    assert "github.event_name == 'workflow_dispatch'" in job
    # the job's exact commands really run weightless — this env has no
    # model stack at all, and a tmp cwd keeps tracked reports untouched
    src = str(Path("src").resolve())
    for cmd in ([sys.executable, str(Path("eval/bench_stub.py").resolve()), "20"],
                [sys.executable, str(Path("eval/bench_pool.py").resolve()),
                 "--json"]):
        r = subprocess.run(cmd, check=False, capture_output=True, text=True,
                           timeout=120, cwd=str(tmp_path),
                           env={"PATH": "/usr/bin:/bin", "PYTHONPATH": src})
        assert r.returncode == 0, r.stderr
        assert isinstance(json.loads(r.stdout), dict), r.stdout


def test_ci_eval_gate_job_replays_weightless(tmp_path):  # T739
    import re
    import subprocess
    import sys
    ci = (WORKFLOWS / "ci.yml").read_text()
    m = re.search(r"^  eval-gate:(.*?)(?=^  \w|\Z)", ci, re.MULTILINE | re.DOTALL)
    assert m, "no eval-gate job"
    job = m.group(1)
    # the job regenerates the weightless report set (reports are gitignored
    # — nothing canonical is committed), then gates it with the box's exact
    # flag: one line of verdict JSON, stable exits
    assert "gate.py --all --ci" in job
    assert "bench_pool.py" in job and "breaker_sim.py" in job
    # replay the job's commands for real in a tmp cwd: the gate must PASS
    # exit 0 on that weightless set (a fresh CI checkout sees only this)
    src = str(Path("src").resolve())
    root = str(Path.cwd())
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": src}
    for script in ("eval/bench_pool.py", "eval/breaker_sim.py"):
        r = subprocess.run([sys.executable, f"{root}/{script}"],
                           check=False, capture_output=True, text=True,
                           timeout=120, cwd=str(tmp_path), env=env)
        assert r.returncode == 0, r.stderr
    reports = tmp_path / "eval" / "reports"
    assert sorted(p.name for p in reports.glob("*.json")) == \
        ["breaker.json", "pool.json"]
    r = subprocess.run(
        [sys.executable, f"{root}/eval/gate.py", "--all", "--ci",
         "--reports-dir", str(reports)],
        check=False, capture_output=True, text=True, timeout=120,
        cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "GATE all: PASS" in r.stdout


def test_ci_caches_pip_and_uv():  # T740
    import re
    ci = (WORKFLOWS / "ci.yml").read_text()
    jobs = re.findall(r"^  (\w[\w-]*):", ci, re.MULTILINE)
    assert len(jobs) >= 6, jobs
    # every job that pip-installs lets setup-python cache the wheelhouse...
    for name in jobs:
        m = re.search(rf"^  {re.escape(name)}:(.*?)(?=^  \w|\Z)",
                      ci, re.MULTILINE | re.DOTALL)
        assert m, name
        if "pip install" in m.group(1):
            assert 'cache: "pip"' in m.group(1), name
    # ...and uv — the same uvx the local gate runs — is set up with its
    # own cache keyed on pyproject.toml (T740)
    assert "astral-sh/setup-uv" in ci
    assert "enable-cache: true" in ci
    assert 'cache-dependency-glob: "pyproject.toml"' in ci


def test_ci_matrix_reports_every_leg():  # T741
    import re
    ci = (WORKFLOWS / "ci.yml").read_text()
    m = re.search(r"^  test:(.*?)(?=^  \w|\Z)", ci, re.MULTILINE | re.DOTALL)
    assert m, "no test job"
    job = m.group(1)
    # fail-fast off: one red leg never cancels the rest, so you always
    # learn whether a failure is version-specific
    assert "fail-fast: false" in job
    # only the matrix needs it — single-leg jobs can't cancel each other
    assert ci.count("fail-fast") == 1


def test_workflow_badge_in_readme():  # T742
    import re
    import subprocess
    readme = Path("README.md").read_text()
    # the badge exists, links back to the runs page, and names a workflow
    # that actually lives in .github/workflows/ (a renamed file would
    # otherwise ship a silently dead image)
    m = re.search(
        r"\[!\[ci\]\(https://github\.com/([\w.-]+/[\w.-]+)/actions/workflows/"
        r"([\w.-]+)/badge\.svg\)\]"
        r"\(https://github\.com/\1/actions/workflows/\2\)", readme)
    assert m, "no ci workflow badge (or malformed) in README"
    slug, workflow = m.group(1), m.group(2)
    assert (WORKFLOWS / workflow).exists(), f"badge names missing {workflow}"
    # and the slug matches this repo's origin — the badge doesn't go stale
    # after a rename or move
    r = subprocess.run(["git", "remote", "get-url", "origin"],
                       check=False, capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        u = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$",
                      r.stdout.strip())
        if u:  # only github origins make a badge claim
            assert u.group(1) == slug, (u.group(1), slug)


def test_pr_template_checklist():  # T743
    # the tracked name is lowercase (GitHub's canonical filename); macOS's
    # case-insensitive FS hid the mismatch that failed Linux CI (T814)
    t = Path(".github/pull_request_template.md").read_text()
    # the box's three questions — tests? docs? boxes ticked? — all have a
    # checkbox, plus the repo's standing gates (lint, secrets)
    assert "pytest" in t and "ruff" in t
    assert "Docs updated" in t
    assert "TODO.md" in t and "its own commit" in t
    assert "secrets" in t
    assert t.count("- [ ]") >= 6, "checklist too thin"


def test_issue_template_bug_report():  # T744
    t = Path(".github/ISSUE_TEMPLATE/bug_report.yml").read_text()
    # the box's three fields — version, rid (request id from server logs,
    # rule id when a decision is implicated), config — all exist...
    for fid in ("version", "rid", "config"):
        assert f"id: {fid}" in t, fid
    # ...version and rid gate triage, so they are required...
    assert t.count("required: true") >= 3
    # ...and the form demands redaction: no tokens ever land in issues
    assert "Redaction" in t and "Tokens" in t


def test_codeowners_and_branch_protection_notes():  # T745
    co = Path(".github/CODEOWNERS").read_text()
    # every path routes through the maintainer
    assert "* @Faycall1l" in co
    con = Path("CONTRIBUTING.md").read_text()
    # branch protection lives in GitHub settings — the notes must name the
    # checks to require, and the file that routes reviews
    assert "branch protection" in con.lower()
    assert "CODEOWNERS" in con
    for check in ("lint", "test", "weightless", "eval-gate"):
        assert check in con, check
    # the documented verify gate matches what the repo actually lints with
    # (the stale "ruff check src tests" wording died here, at T745)
    assert "ruff check ." in con and "ruff check src tests" not in con


def test_ci_secret_scan_job(tmp_path):  # T746
    import re
    import subprocess
    import sys
    ci = (WORKFLOWS / "ci.yml").read_text()
    m = re.search(r"^  secret-scan:(.*?)(?=^  \w|\Z)", ci, re.MULTILINE | re.DOTALL)
    assert m, "no secret-scan job"
    assert "secret_scan.py" in m.group(1)
    # the scan runs green on the tracked tree right now...
    r = subprocess.run([sys.executable, "scripts/secret_scan.py"],
                       check=False, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "clean" in r.stdout
    # ...and really catches what it claims: a planted fake github token in
    # a throwaway repo trips it — reported as file:line:LABEL, and the
    # credential itself never appears in the output
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    (tmp_path / "leak.txt").write_text(f"token = {secret!r}\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "leak.txt"],
                   check=True)
    scanner = str(Path("scripts/secret_scan.py").resolve())
    r = subprocess.run([sys.executable, scanner], check=False,
                       capture_output=True, text=True, timeout=60,
                       cwd=str(tmp_path))
    assert r.returncode == 1, r.stdout
    assert "github token" in r.stdout and "leak.txt:1" in r.stdout
    assert secret not in r.stdout + r.stderr, "scanner leaked the secret"


def test_ci_coverage_job_posts_number(tmp_path):  # T747
    import importlib.util
    import json
    import os
    import re
    import subprocess
    import sys

    import pytest
    ci = (WORKFLOWS / "ci.yml").read_text()
    m = re.search(r"^  coverage:(.*?)(?=^  \w|\Z)", ci, re.MULTILINE | re.DOTALL)
    assert m, "no coverage job"
    job = m.group(1)
    # the box: a run + the number posted + an artifact — and explicitly
    # NO floor yet (nothing fail-under anywhere)
    assert "--cov=gatekeeper" in job and "--cov-report=json" in job
    assert "GITHUB_STEP_SUMMARY" in job and "upload-artifact" in job
    assert "--cov-fail" not in job
    assert "pytest-cov" in job  # rides in the dev extra (T747)
    if importlib.util.find_spec("pytest_cov") is None:
        pytest.skip("pytest-cov absent (CI installs it via .[dev])")
    # the wiring really runs: a file that imports gatekeeper in-process,
    # measured under coverage, yields a totals block the summary prints
    out = tmp_path / "cov.json"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_cli.py",
         "--cov=gatekeeper", f"--cov-report=json:{out}"],
        check=False, capture_output=True, text=True, timeout=300,
        # COVERAGE_FILE keeps the sqlite data file in tmp — the repo root
        # must stay clean even when the gate commits everything changed
        env={**os.environ, "PYTHONPATH": "src",
             "COVERAGE_FILE": str(tmp_path / ".coverage")})
    assert r.returncode == 0, r.stderr
    totals = json.loads(out.read_text())["totals"]
    assert totals["percent_covered"] >= 0.0
    assert totals["num_statements"] > 100, "coverage measured nothing"


def test_nightly_stub_suite_workflow():  # T748
    import re
    text = (WORKFLOWS / "nightly.yml").read_text()
    header, _, body = text.partition("jobs:")
    # scheduled + manually runnable — no push trigger (that's ci.yml's job)
    assert "schedule" in header and "cron" in header
    assert "workflow_dispatch" in header
    assert "push" not in header, "nightly must not double ci.yml"
    m = re.search(r"^  stub-suite:(.*?)(?=^  \w|\Z)", body, re.MULTILINE | re.DOTALL)
    assert m, "no stub-suite job"
    job = m.group(1)
    # the whole weightless suite — deterministic by construction (stubs,
    # no network), so red means upstream drift, not flake
    assert "pytest -q" in job
    assert '.[dev]' in job  # open floors resolve the latest deps, on purpose


def test_release_notes_check(tmp_path):  # T749
    import subprocess
    import sys
    text = (WORKFLOWS / "publish.yml").read_text()
    # the release guards run in order: tag == version, version documented,
    # and only then does anything build
    assert text.index("check_tag.py") < \
        text.index("check_changelog.py") < \
        text.index("python -m build")

    def run(*args, cwd=None):
        return subprocess.run(
            [sys.executable, str(Path("scripts/check_changelog.py").resolve()),
             *args],
            check=False, capture_output=True, text=True, timeout=30,
            cwd=cwd or str(Path.cwd()))
    # the current version IS documented → the gate passes...
    r = run()
    assert r.returncode == 0, r.stderr
    # ...an undocumented version refuses the release by name...
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n')
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n")
    r = run(cwd=str(tmp_path))
    assert r.returncode == 1
    assert "E_CHANGELOG" in r.stderr and "9.9.9" in r.stderr
    # ...and stray arguments are a usage error, not a silent pass
    assert run("extra").returncode == 2


def test_p39_workflow_yaml_parses_and_key_jobs_exist():  # T750
    import json
    import shutil
    import subprocess

    import pytest
    ruby = shutil.which("ruby")
    if ruby is None:
        pytest.skip("no ruby — macOS and GH runners both ship one, "
                    "but a box without a YAML parser can't prove parsing")

    def jobs_of(path):
        # Psych (YAML 1.1) rewrites the `on:` key to boolean true — so
        # assert on jobs, which is exactly what this box is about
        r = subprocess.run(
            [ruby, "-ryaml", "-rjson", "-e",
             'print JSON.generate(YAML.load_file(ARGV[0])["jobs"].keys)',
             path],
            check=False, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{path}: {r.stderr}"
        return json.loads(r.stdout)
    # every workflow parses as real YAML (not just string-matched)...
    ci = jobs_of(str(WORKFLOWS / "ci.yml"))
    pub = jobs_of(str(WORKFLOWS / "publish.yml"))
    nightly = jobs_of(str(WORKFLOWS / "nightly.yml"))
    # ...and the key jobs of each P39 stage exist: T731-T734/T738/T740,
    # T739, T746, T747, T781 (dependency audit) in ci.yml; T735+T749 build
    # and T736 release here; T748's one scheduled job
    for job in ("lint", "test", "weightless", "bench", "smoke",
                "eval-gate", "secret-scan", "coverage", "audit"):
        assert job in ci, f"ci.yml lost job {job}"
    assert "build" in pub and "release" in pub
    assert nightly == ["stub-suite"], nightly
    # the whole set is stable enough to pin — order included (readability
    # of the pipeline: lint/test first, reporting at the tail)
    assert ci == ["lint", "test", "weightless", "bench", "smoke",
                  "eval-gate", "secret-scan", "coverage", "audit"], ci
