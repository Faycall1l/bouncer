"""P29 tests (T531-T550): CLI. No weights."""
import subprocess
import sys

sys.path.insert(0, "src")


def test_models_and_presets_commands():  # T538+T539
    r = subprocess.run([sys.executable, "-m", "gatekeeper.cli", "models"],
                       check=False, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"})
    assert r.returncode == 0 and "multilingual" in r.stdout and "pool:" in r.stdout
    r = subprocess.run([sys.executable, "-m", "gatekeeper.cli", "presets"],
                       check=False, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"})
    assert r.returncode == 0 and "gaming" in r.stdout and "study" in r.stdout
