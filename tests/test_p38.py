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
            assert "gatekeeper/py.typed" in names  # T725: PEP 561 ships
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


def test_compose_snapshot_volumes_and_secrets():  # T717
    import re
    import shutil
    import subprocess
    text = Path("compose.yaml").read_text()
    # secrets never live in the file: compose interpolates them from .env...
    assert "BOUNCER_KEY: ${BOUNCER_KEY:-}" in text
    assert "BOUNCER_KEY: " in text and "change-me" not in text
    gitignore = Path(".gitignore").read_text().splitlines()
    assert ".env" in gitignore, ".env must stay gitignored"
    # ...and .env.example documents what an operator fills in
    env_ex = Path(".env.example").read_text()
    assert "BOUNCER_KEY" in env_ex and "copy to .env" in env_ex
    # both persisted dirs are named volumes, declared top-level...
    m = re.search(r"^volumes:\n((?:  \S.*\n)+)", text, re.MULTILINE)
    assert m, "no top-level volumes section"
    declared = set(re.findall(r"^  (\S+?):", m.group(1), re.MULTILINE))
    assert declared == {"hf-cache", "snapshots"}, declared
    # ...and every service mounts them under the T716 non-root paths —
    # the old /root/.cache bind is gone with the root user
    assert text.count("- hf-cache:/home/bouncer/.cache") == 2
    assert text.count("- snapshots:/app/snapshots") == 2
    assert "/root" not in text, "compose still targets the root user's home"
    # when docker is present, the real parser validates the structure
    docker = shutil.which("docker")
    if docker:
        r = subprocess.run([docker, "compose", "-f", "compose.yaml",
                            "config", "--quiet"],
                           check=False, capture_output=True, text=True,
                           timeout=60)
        assert r.returncode == 0, r.stderr


def _docker_ignored(path: str, rules: list) -> bool:  # T718: tiny matcher
    from fnmatch import fnmatch
    first = path.split("/")[0]
    for r in rules:
        r = r.strip()
        if not r or r.startswith("#"):
            continue
        if r.endswith("/"):
            if path.startswith(r) or first == r.rstrip("/"):
                return True
        elif fnmatch(path, r) or fnmatch(first, r) or first == r:
            return True
    return False


def test_dockerignore_keeps_context_tiny():  # T718
    rules = Path(".dockerignore").read_text().splitlines()
    # the box's contract: models, data dumps, git — plus the usual suspects
    must = ("models/", "data/", "*.jsonl", ".git", ".env", "hf-cache/")
    for rule in must:
        assert rule in rules, f".dockerignore lost {rule}"
    # every path that must never reach the build context stays out...
    heavy = [".git/objects/pack/x", "models/laya-30ms.bin",
             "hf-cache/models--x/blob", ".env", "bouncer-audit.jsonl",
             "data/examples.jsonl", "src/gatekeeper/__pycache__/m.pyc",
             "bouncer-stats.json"]
    for p in heavy:
        assert _docker_ignored(p, rules), p
    # ...while everything the Dockerfile COPYs is still in the context
    for p in ("src/gatekeeper/__init__.py", "src/gatekeeper/adapters/common.py",
              "pyproject.toml", "README.md", "LICENSE", "MANIFEST.in"):
        assert not _docker_ignored(p, rules), f"context would lose {p}"


def test_container_entrypoint_runs_self_test(monkeypatch, tmp_path):  # T719
    import os
    import subprocess
    script = Path("scripts/docker-entrypoint.sh")
    assert script.exists() and os.access(script, os.X_OK), "entrypoint not executable"
    # shell syntax must be valid before anything else claims it works
    r = subprocess.run(["sh", "-n", str(script)], capture_output=True,
                       text=True, check=False)
    assert r.returncode == 0, r.stderr
    # the Dockerfile gates startup on it
    dockerfile = Path("Dockerfile").read_text()
    assert 'ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]' in dockerfile
    assert "docker-entrypoint.sh" in dockerfile
    # behavior: a stub bouncer returns each documented exit code and the
    # entrypoint must hand off only on the tolerated ones (T719 contract)
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "bouncer"
    stub.write_text('#!/bin/sh\nexit "$STUB_RC"\n')
    stub.chmod(0o755)

    def run_entry(rc, *cmd):
        e = {"PATH": f"{stub_dir}:/usr/bin:/bin", "STUB_RC": str(rc)}
        return subprocess.run(["sh", str(script), *cmd], capture_output=True,
                              text=True, env=e, timeout=30, check=False)

    # tolerated exits hand off to the CMD and it really runs
    r0 = run_entry(0, "echo", "handed-off")
    assert r0.returncode == 0 and "handed-off" in r0.stdout
    assert run_entry(3, "true").returncode == 0  # escalate: degraded but alive
    for rc in (1, 2):                         # crash / delete-flag: kill boot
        r = run_entry(rc, "true")
        assert r.returncode == 1, rc
        assert "self-test failed" in r.stderr, rc


def test_dockerfile_oci_labels_are_honest():  # T720
    import re
    text = Path("Dockerfile").read_text()
    py = _pyproject()
    labels = dict(re.findall(
        r"^\s*(?:LABEL\s+)?org\.opencontainers\.image\.([\w.]+)=\"([^\"]*)\""
        r"\s*\\?\s*$",
        text, re.MULTILINE))
    for key in ("title", "description", "authors", "source", "url",
                "licenses", "base.name"):
        assert key in labels, f"missing OCI label: {key}"
    # every value agrees with the shipped metadata — no free-hand marketing
    assert labels["title"] == py["project"]["name"]
    assert labels["description"] == py["project"]["description"]
    assert labels["authors"] == py["project"]["authors"][0]["name"]
    assert labels["source"] == py["project"]["urls"]["Homepage"]
    assert labels["licenses"] == py["project"]["license"]["text"]
    from_line = next(l for l in text.splitlines() if l.startswith("FROM "))
    assert labels["base.name"].endswith(from_line.split()[1])
    # version/created stay CI-stamped: a static one would rot (T720 decision)
    assert "version" not in labels and "created" not in labels
    assert "CI stamps them at build time" in text


def test_pip_install_produces_working_bouncer(tmp_path):  # T721
    import glob
    import os
    import shutil
    import subprocess

    import pytest
    uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if not os.path.exists(uv):
        pytest.skip("uv not available — the install smoke needs a builder")
    # build the wheel, install it --no-deps into a throwaway venv: the
    # entry-point wiring must stand on its own, without pulling the world
    r = subprocess.run([uv, "build", "--wheel", "-o", str(tmp_path)],
                       check=False, capture_output=True, text=True,
                       timeout=300, cwd=str(Path.cwd()))
    assert r.returncode == 0, r.stderr
    wheels = glob.glob(str(tmp_path / "*.whl"))
    assert len(wheels) == 1, wheels
    venv = tmp_path / "venv"
    r = subprocess.run([uv, "venv", str(venv)], check=False,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    r = subprocess.run([uv, "pip", "install", "--python", str(py),
                        "--no-deps", wheels[0]],
                       check=False, capture_output=True, text=True,
                       timeout=300)
    assert r.returncode == 0, r.stderr
    # the console script exists and answers `--version` with the packaged
    # version — exactly what a wheel user gets after pip install
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    script = bin_dir / ("bouncer.exe" if os.name == "nt" else "bouncer")
    assert script.exists(), "console script not installed"
    r = subprocess.run([str(script), "--version"], check=False,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    sys.path.insert(0, "src")
    from gatekeeper import __version__
    assert r.stdout.strip() == f"bouncer {__version__}"


def test_dependency_floor_pins():  # T722
    import re
    py = _pyproject()
    deps = py["project"]["dependencies"]
    # every core dep carries a lower bound (the T216 promise, re-audited)
    for d in deps:
        assert re.match(r"^[\w.-]+>=\d[\w.]*$", d), f"no clean floor: {d}"
    # the box's three all have floors...
    floors = {_floor(d)[0]: _floor(d)[1] for d in deps}
    for pkg in ("fastapi", "gradio", "pydantic"):
        assert floors.get(pkg, "").startswith(">="), pkg
    # ...and pydantic's floor is the v2 stack serve.py actually runs on
    assert floors["pydantic"] == ">=2"


def test_core_import_is_weightless(tmp_path):  # T723
    import subprocess
    # empirical: numpy and laya are shadowed by modules that raise on
    # import — a core import that touches either dies loudly here
    for mod in ("numpy", "laya"):
        (tmp_path / f"{mod}.py").write_text('raise ImportError("T723")\n')
    code = ("import gatekeeper\n"
            "from gatekeeper import moderate, GateConfig, get_preset\n"
            "import gatekeeper.cli\n"
            "import gatekeeper.adapters.common\n"
            "print('ok', gatekeeper.__version__)\n")
    r = subprocess.run([sys.executable, "-c", code], check=False,
                       capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin",
                            "PYTHONPATH": f"{tmp_path}:src"})
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout
    # static: no core module imports numpy/laya at module level — lazy is
    # the only allowed shape, so a bare `import gatekeeper` stays cheap
    for path in Path("src/gatekeeper").glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [(node.module or "").split(".")[0]]
            else:
                continue
            assert "numpy" not in mods and "laya" not in mods, (
                path.name, "imports weights at module level")


def test_pip_index_metadata_filled():  # T724
    import re
    py = _pyproject()
    kws = py["project"]["keywords"]
    # pip-index-searchable: one lowercase hyphenated vocabulary, no phrases
    assert all(re.fullmatch(r"[a-z0-9-]+", k) for k in kws), kws
    assert {"moderation", "chat-moderation", "content-moderation"} <= set(kws)
    cls = py["project"]["classifiers"]
    assert all(" :: " in c and not c.startswith(" :: ") for c in cls)
    # the fill: maturity, audience, platform, environments, topics
    for want in ("Development Status :: 4 - Beta",
                 "Operating System :: OS Independent",
                 "Intended Audience :: Developers",
                 "Environment :: Console",
                 "Environment :: Web Environment",
                 "Topic :: Communications :: Chat",
                 "Topic :: Security"):
        assert want in cls, want
    # classifier minors track the requires-python floor (no drift below it)
    floor = py["project"]["requires-python"].split(">=")[1]
    minors = sorted(c.rsplit(" ", 1)[1] for c in cls
                    if c.startswith("Programming Language :: Python :: 3."))
    assert minors and minors[0] == floor, (minors, floor)


def test_py_typed_marker_and_typed_public_api():  # T725
    # the PEP 561 marker exists and is declared as package data...
    assert Path("src/gatekeeper/py.typed").exists(), "marker file missing"
    py = _pyproject()
    pkg_data = py["tool"]["setuptools"].get("package-data", {})
    assert "py.typed" in pkg_data.get("gatekeeper", []), pkg_data
    manifest = Path("MANIFEST.in").read_text()
    assert "src/gatekeeper/py.typed" in manifest, "marker would miss the sdist"
    # ...and every public function in the package root is fully typed:
    # return annotation plus every parameter annotated (the imported
    # siblings — get_preset, validate_rules, explain — are typed at their
    # own definitions; this pins the __init__ surface, whose shipping in
    # the wheel alongside py.typed is asserted in the T713 wheel test)
    tree = ast.parse(Path("src/gatekeeper/__init__.py").read_text())
    public = [n for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and not n.name.startswith("_")]
    assert public, "no public functions found at the package root"
    for fn in public:
        assert fn.returns is not None, f"{fn.name}(): no return annotation"
        params = fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs
        for a in params:
            if a.arg in ("self", "cls"):
                continue
            assert a.annotation is not None, f"{fn.name}({a.arg}): untyped"
