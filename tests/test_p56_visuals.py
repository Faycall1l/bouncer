"""P64 tests (T1233): README figures are generated, not hand-drawn claims."""
import subprocess
import sys
from pathlib import Path


def test_visual_manifest_reproduces_exactly():  # T1233
    """The committed GIF is byte-for-byte reproducible from the engine path.

    `--check` rebuilds the frames from synthetic-router calls through moderate()
    and compares both the GIF hash and the generator hash. A drift in the gate
    that changes a rendered decision therefore fails here instead of leaving a
    README figure that describes old behavior.
    """
    proc = subprocess.run(
        [sys.executable, "scripts/make_readme_visuals.py", "--check"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '"check": true' in proc.stdout

    readme = Path("README.md").read_text()
    for asset in ("docs/assets/decision-trace.gif", "docs/assets/gate-precedence.svg"):
        assert asset in readme
        assert Path(asset).exists()
