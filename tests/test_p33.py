"""P33 tests (T611-T630): release gates. No weights."""
import os
import subprocess
import sys

sys.path.insert(0, "src")

ENV = {**os.environ, "PATH": "/usr/bin:/bin", "PYTHONPATH": "src"}


def _run(*args):
    return subprocess.run([sys.executable, "-m", "gatekeeper.cli", *args],
                          check=False, capture_output=True, text=True, env=ENV,
                          timeout=60)


def test_new_cli_commands_help():  # T614
    for cmd in ("snapshot", "models", "presets", "export", "review", "pack"):
        r = _run(cmd, "--help")
        assert r.returncode == 0, f"{cmd}: {r.stderr}"
        assert "usage: bouncer" in r.stdout
    r = _run("snapshot", "--help")
    assert "save" in r.stdout and "load" in r.stdout  # actions listed
    r = _run("pack", "--help")
    assert "init" in r.stdout
    r = _run("--version")
    assert r.returncode == 0 and "0.3.0" in r.stdout  # T611+T624: via --version
