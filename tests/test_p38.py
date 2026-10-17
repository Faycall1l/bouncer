"""P38 tests (T711-T730): packaging. Weightless — metadata, files, imports;
`build`/`pip install` boxes shell out only where the box demands it."""
import ast
import sys
from pathlib import Path

ADAPTERS = Path("src/gatekeeper/adapters")


def _pyproject():
    import tomllib
    with open("pyproject.toml", "rb") as f:
        return tomllib.load(f)


def _floor(dep: str) -> tuple:
    """('fastapi', '>=0.110') for a pinned dep; ('pytest', None) bare."""
    for op in (">=", "==", "~="):
        if op in dep:
            name, ver = dep.split(op, 1)
            return name, op + ver
    return dep, None


def test_optional_dep_groups_audited():  # T711
    py = _pyproject()
    opt = py["project"]["optional-dependencies"]
    # the documented groups exist...
    for group in ("dev", "server", "demo", "discord", "mattermost", "adapters"):
        assert group in opt, f"missing optional-deps group: {group}"
    # ...server/demo floor-pin the same versions core does (T711: no bare
    # duplicates that could drift below a smoke-tested floor)
    core = {_floor(d)[0]: _floor(d)[1] for d in py["project"]["dependencies"]}
    for group in ("server", "demo"):
        for dep in opt[group]:
            name, pin = _floor(dep)
            if name in core:
                assert pin == core[name], (group, name, pin, core[name])
    # the adapters umbrella is exactly the union of the per-adapter extras
    # — a new adapter dep must land in both places or the audit fails
    per_adapter = sorted(set(opt["discord"]) | set(opt["mattermost"]))
    assert sorted(opt["adapters"]) == per_adapter


def test_adapter_extras_cover_every_third_party_import():  # T711
    py = _pyproject()
    opt = py["project"]["optional-dependencies"]
    dists = {name for group in opt.values() for name, _ in map(_floor, group)}
    stdlib = set(sys.stdlib_module_names)
    # dist name != import name only where it differs
    to_dist = {"discord": "discord.py", "websockets": "websockets"}
    found = set()
    for path in ADAPTERS.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [(node.module or "").split(".")[0]]
            else:
                continue
            for m in mods:
                if m in stdlib or m in ("__future__", "gatekeeper"):
                    continue
                found.add((m, path.name))
    assert found, "the scan found no third-party adapter imports"
    for mod, src in found:
        assert to_dist[mod] in dists, (src, mod, "no extra installs it")


def test_console_script_entry_point():  # T712
    import subprocess
    sys.path.insert(0, "src")
    py = _pyproject()
    # exactly one console script, wired to the CLI entry the docs invoke
    scripts = py["project"]["scripts"]
    assert scripts == {"bouncer": "gatekeeper.cli:main"}
    # the declared target is importable and callable without installing
    from gatekeeper.cli import main
    assert callable(main)
    # and it behaves like the console script: `bouncer --version` answers
    # with the packaged version, exit 0 — the same contract wheel users get
    from gatekeeper import __version__
    r = subprocess.run(
        [sys.executable, "-c",
         "from gatekeeper.cli import main; raise SystemExit(main(['--version']))"],
        check=False, capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"})
    assert r.returncode == 0, r.stderr
    assert f"bouncer {__version__}" in r.stdout


def test_wheel_builds_clean():  # T713
    import glob
    import os
    import shutil
    import subprocess
    import sys
    import tempfile
    import zipfile

    import pytest
    sys.path.insert(0, "src")
    uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if not os.path.exists(uv):
        pytest.skip("uv not available — the wheel smoke needs a PEP 517 builder")
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([uv, "build", "--wheel", "-o", td],
                           check=False, capture_output=True, text=True,
                           timeout=300, cwd=str(Path.cwd()))
        assert r.returncode == 0, r.stderr  # T713: the build is clean
        wheels = glob.glob(os.path.join(td, "*.whl"))
        assert len(wheels) == 1, wheels
        with zipfile.ZipFile(wheels[0]) as z:
            names = z.namelist()
            # the package and the adapter SDK made it into the wheel...
            assert "gatekeeper/__init__.py" in names
            assert "gatekeeper/adapters/common.py" in names
            # ...the console script is in the wheel metadata...
            ep = [n for n in names if n.endswith("entry_points.txt")]
            assert ep, "no entry_points.txt in the wheel"
            body = z.read(ep[0])
            assert b"bouncer" in body and b"gatekeeper.cli:main" in body
            # ...and the version metadata matches the running package
            md = [n for n in names if n.endswith("dist-info/METADATA")]
            assert md, "no METADATA in the wheel"
            from gatekeeper import __version__
            meta = z.read(md[0])
            assert b"Name: gatekeeper-1" in meta
            assert f"Version: {__version__}".encode() in meta
            # nothing heavy leaked in: tests, weights, VCS stay out (T713+T718)
            assert not any(n.startswith(("tests/", ".git/", "model"))
                           for n in names), "heavy paths leaked into the wheel"


def test_sdist_includes_license_readme_and_data_examples():  # T714
    import glob
    import os
    import shutil
    import subprocess
    import tarfile
    import tempfile

    import pytest
    uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if not os.path.exists(uv):
        pytest.skip("uv not available — the sdist smoke needs a PEP 517 builder")
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([uv, "build", "--sdist", "-o", td],
                           check=False, capture_output=True, text=True,
                           timeout=300, cwd=str(Path.cwd()))
        assert r.returncode == 0, r.stderr
        sdists = glob.glob(os.path.join(td, "*.tar.gz"))
        assert len(sdists) == 1, sdists
        with tarfile.open(sdists[0]) as tf:
            members = {m.name.split("/", 1)[-1] for m in tf.getmembers()
                       if m.isfile()}
        # the box's contract: license, readme, data examples...
        for req in ("LICENSE", "README.md", "pyproject.toml", "MANIFEST.in",
                    "data/examples.jsonl", "data/CARD.md"):
            assert req in members, f"{req} missing from the sdist"
        # ...the importable package, and nothing heavy (weights/VCS)
        assert "src/gatekeeper/__init__.py" in members
        assert not any(m.startswith((".git/", "model", "build/"))
                       for m in members), "heavy paths leaked into the sdist"


def test_license_year_and_holder():  # T715
    import re
    text = Path("LICENSE").read_text()
    # the copyright line names a sane year: project start (2026) to now —
    # no future-dated claim, no pre-project drift
    from datetime import datetime
    m = re.search(r"Copyright (\d{4}) (.+?)\. ", text)
    assert m, "LICENSE has no 'Copyright <year> <holder>.' line"
    year, holder = int(m.group(1)), m.group(2).strip()
    assert 2026 <= year <= datetime.now().year, year
    # the holder is the same one pyproject.toml ships
    py = _pyproject()
    assert holder == py["project"]["authors"][0]["name"], (holder,
                                                           py["project"])
    # and the license pointer agrees with the metadata (Apache-2.0 everywhere)
    assert "apache.org/licenses/LICENSE-2.0" in text
    assert py["project"]["license"]["text"] == "Apache-2.0"
    assert any("Apache Software License" in c
               for c in py["project"]["classifiers"])


def test_dockerfile_slim_nonroot_healthcheck():  # T716
    text = Path("Dockerfile").read_text()
    # slim base, pinned to a minor so rebuilds don't silently jump distros
    from_lines = [l for l in text.splitlines() if l.startswith("FROM ")]
    assert from_lines == ["FROM python:3.12-slim"], from_lines
    # non-root: a dedicated user is created and switched to
    assert "useradd" in text and "USER bouncer" in text
    # a healthcheck exists and probes the real liveness route (T046),
    # not /ready — weights downloading must not mark the container sick
    assert "HEALTHCHECK" in text and "/health" in text
    assert "start-period" in text  # cold start downloads weights
    # production image ships runtime deps only: no dev extra, no editable
    # install that would need the source tree to stay put
    assert ".[dev]" not in text and " -e " not in text and '-e "' not in text
    # and it still serves the same app the compose file expects
    assert 'CMD ["uvicorn", "gatekeeper.serve:app"' in text
    assert "EXPOSE 8000" in text
