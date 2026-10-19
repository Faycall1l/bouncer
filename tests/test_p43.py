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
