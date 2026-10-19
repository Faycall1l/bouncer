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


def test_adapter_matrix_matches_runnable_modules():  # T820
    """Every command the matrix's Setup column documents really runs.

    T703 checks files<->rows and SDK-helper existence; this closes the
    loop on the Setup column: each `python -m gatekeeper.adapters.X`
    names a real module that fails CLOSED (coded E_ADAPTER — naming the
    missing env var or the pip extra) under a scrubbed env, never with a
    raw KeyError/ModuleNotFoundError, and each `.[extra]` it advertises
    exists in pyproject.
    """
    import subprocess
    import sys
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11: the tomli backport (T814)
        import tomli as tomllib
    text = (Path("src/gatekeeper/adapters") / "README.md").read_text()
    mods = sorted(set(re.findall(
        r"python -m gatekeeper\.adapters\.(\w+)", text)))
    assert mods, "matrix documents no runnable adapter"
    files = sorted(p.stem for p in Path("src/gatekeeper/adapters").glob("*.py"))
    # every documented command names a real module...
    assert set(mods) <= set(files), sorted(set(mods) - set(files))
    # ...and every module is either runnable or explicitly not (by design)
    for stem in set(files) - set(mods):
        row = next(line for line in text.splitlines() if stem in line)
        assert "never run directly" in row or "from your receiver" in row, \
            f"{stem}.py is undocumented as runnable AND undocumented as not"
    # every advertised extra exists in pyproject
    with open("pyproject.toml", "rb") as f:
        extras = set(tomllib.load(f)["project"]["optional-dependencies"])
    for extra in sorted(set(re.findall(r"\.\[(\w+)\]", text))):
        assert extra in extras, f"matrix advertises .[{extra}] but pyproject has no such extra"
    # each runnable adapter fails closed with E_ADAPTER under a scrubbed env
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"}
    for mod in mods:
        r = subprocess.run([sys.executable, "-m", f"gatekeeper.adapters.{mod}"],
                           check=False, capture_output=True, text=True,
                           env=env, timeout=60)
        assert r.returncode != 0, f"adapter {mod} ran with no env at all"
        assert "E_ADAPTER" in r.stderr, f"{mod}: not coded — {r.stderr[-200:]}"
        # our error has the last word (T694 pattern: the raw ImportError may
        # ride along as __cause__ for diagnostics, but never ends the trace)
        last = r.stderr.strip().splitlines()[-1]
        assert last.startswith("gatekeeper.adapters.common.AdapterError"), \
            f"{mod}: raw traceback ended the run — {last}"
        assert "KeyError" not in r.stderr, \
            f"{mod}: raw KeyError leaked — {r.stderr[-200:]}"


def test_root_entry_files_link_checker_green():  # T821 (extends T798)
    """The T798 checker scans docs/*.md only — but the repo's entry files
    (README, SECURITY, CONTRIBUTING, BENCHMARKS, CHANGELOG, TODO) are the
    first thing a reader opens, and they link into docs/ and each other.
    Same rules, same helpers (imported from test_p42 — one implementation):
    dead relative links and dead anchors fail the box.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from test_p42 import _LINK_RE, _headings, _strip_code

    problems, checked = [], 0
    for p in sorted(Path(".").glob("*.md")):
        text = _strip_code(p.read_text())
        for _label, href in _LINK_RE.findall(text):
            if href.startswith(("http://", "https://", "mailto:", "//", "/")):
                continue
            checked += 1
            path, _, anchor = href.partition("#")
            if not path:
                target = p  # same-page anchor
            else:
                target = Path(path)
                if not target.exists():
                    problems.append(f"{p.name}: dead link {href}")
                    continue
            if anchor and anchor not in _headings(target.read_text()):
                problems.append(
                    f"{p.name}: dead anchor {href} — no heading slug "
                    f"{anchor!r} in {target.name}")
    assert not problems, "\n".join(problems)
    # floor: the README alone links into docs/ and BENCHMARKS many times
    assert checked >= 10, f"only {checked} relative links found — scanner broken?"


def test_packaging_smoke_release_tree(tmp_path):  # T822
    """Build wheel AND sdist on the release tree, install the wheel into a
    fresh venv, and hold `bouncer --version` against the pyproject version
    itself (the string the tag will carry).

    T713 builds the wheel and inspects contents; T721 installs and checks
    `--version` against `__version__`. This is the release-box superset:
    both artifacts must build, and the installed console script must agree
    with pyproject directly — no import chain in between.
    """
    import glob
    import os
    import shutil
    import subprocess

    import pytest
    uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if not os.path.exists(uv):
        pytest.skip("uv not available — the packaging smoke needs a builder")
    version = _pyproject_version()
    # one PEP 517 build produces both artifacts from the same tree
    r = subprocess.run([uv, "build", "-o", str(tmp_path)],
                       check=False, capture_output=True, text=True,
                       timeout=300, cwd=str(Path.cwd()))
    assert r.returncode == 0, r.stderr
    wheels = glob.glob(str(tmp_path / "*.whl"))
    sdists = glob.glob(str(tmp_path / "*.tar.gz"))
    assert len(wheels) == 1 and len(sdists) == 1, (wheels, sdists)
    # both artifacts are stamped with the release version
    assert f"-{version}-" in os.path.basename(wheels[0]), wheels[0]
    assert f"-{version}.tar.gz" in os.path.basename(sdists[0]), sdists[0]
    # install the wheel --no-deps: entry-point wiring must stand alone
    venv = tmp_path / "venv"
    r = subprocess.run([uv, "venv", str(venv)], check=False,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    r = subprocess.run([uv, "pip", "install", "--python", str(py),
                        "--no-deps", wheels[0]],
                       check=False, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    # the installed console script answers with the pyproject version
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    script = bin_dir / ("bouncer.exe" if os.name == "nt" else "bouncer")
    assert script.exists(), "console script not installed"
    r = subprocess.run([str(script), "--version"], check=False,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"bouncer {version}", r.stdout
    # and the installed package imports with the same version (no src/)
    r = subprocess.run([str(py), "-c",
                        "import gatekeeper; print(gatekeeper.__version__)"],
                       check=False, capture_output=True, text=True, timeout=60,
                       cwd=str(tmp_path))  # cwd away from the repo: no src/ shadow
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == version, (r.stdout, r.stderr)


def test_env_var_docs_coverage_ops_surfaces():  # T823 (extends T609/T807)
    """T609 swept four core files; T807 made environment.md the one true
    table over src/eval/scripts (and, since this box, docs/examples).
    The surfaces still outside every sweep: the container/CI files —
    Dockerfile, compose.yaml, the entrypoint script, and the workflows.
    They SET or READ BOUNCER_* vars too, and each one must have a row.
    """
    import glob

    surfaces = [Path(p) for p in (
        "Dockerfile", "compose.yaml", "scripts/docker-entrypoint.sh",
        *sorted(glob.glob(".github/workflows/*.yml")))]
    assert all(p.exists() for p in surfaces), "an ops surface moved — update this sweep"
    text = Path("docs/environment.md").read_text()
    used = set()
    for p in surfaces:
        used |= set(re.findall(r"BOUNCER_[A-Z_]+", p.read_text()))
    missing = sorted(v for v in used if v not in text)
    assert not missing, f"ops-surface env vars without a row: {missing}"
    # floor: the container self-test at least reads its preset override
    assert "BOUNCER_PRESET" in used, "entrypoint no longer reads BOUNCER_PRESET?"


def test_security_doc_covers_adapter_surface():  # T826
    """docs/SECURITY.md carried zero 0.4.0 surface before this box: the
    adapter posture (flag-only destructive actions, fail-closed startup,
    env-only tokens, signed webhooks) lived only in the adapters README.
    Every claim must name its T-box, and every opt-in flag the doc lists
    must be a real flag the code reads.
    """
    sec = Path("docs/SECURITY.md").read_text()
    # the section exists and claims the posture...
    assert "## Platform adapters" in sec and "T826" in sec
    for phrase in ("Flag-only default", "Fail-closed startup",
                   "Tokens stay env-only", "Signed webhooks are fail-closed"):
        assert phrase in sec, phrase
    # ...every destructive opt-in flag it names is real code (env table + src)
    env_doc = Path("docs/environment.md").read_text()
    src = "\n".join(p.read_text() for p in Path("src").rglob("*.py"))
    for flag in ("BOUNCER_TG_DELETE", "BOUNCER_MX_REDACT",
                 "BOUNCER_MM_DELETE", "BOUNCER_ZL_DELETE", "BOUNCER_DRY_RUN"):
        assert flag in sec, f"{flag} missing from the security doc"
        assert f"`{flag}`" in env_doc, f"{flag} has no environment.md row"
        assert flag in src, f"{flag} is not read by any code"
    # the cited T-boxes are ones TODO.md actually knows (citation integrity)
    todo = Path("TODO.md").read_text()
    for box in ("T691", "T697", "T700", "T704", "T785"):
        assert f"- [x] {box} " in todo, f"{box} cited but not a ticked box"
