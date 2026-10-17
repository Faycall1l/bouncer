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
