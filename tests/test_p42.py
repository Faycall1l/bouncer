"""P42 tests (T791-T810): docs site. mkdocs.yml is parsed with a real
YAML parser where one exists (ruby Psych — same deal as T750)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MKDOCS = Path("mkdocs.yml")


def _mkdocs_yaml(expr: str):
    """Run a ruby expression over parsed mkdocs.yml, return stdout."""
    ruby = shutil.which("ruby")
    if ruby is None:
        pytest.skip("no ruby — macOS and GH runners both ship one, "
                    "but a box without a YAML parser can't prove parsing")
    r = subprocess.run(
        [ruby, "-ryaml", "-rjson", "-e", expr, str(MKDOCS)],
        check=False, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _nav_paths() -> list:
    out = _mkdocs_yaml(
        'print JSON.generate(YAML.load_file(ARGV[0])["nav"] || [])')
    paths = []

    def walk(items):
        for it in items:
            if isinstance(it, dict):
                for v in it.values():
                    if isinstance(v, str):
                        paths.append(v)
                    elif isinstance(v, list):
                        walk(v)

    walk(json.loads(out))
    return paths


def test_mkdocs_material_skeleton():  # T791
    assert MKDOCS.exists(), "mkdocs.yml missing"
    cfg = _mkdocs_yaml(
        'c = YAML.load_file(ARGV[0]); print JSON.generate('
        '[c["theme"]["name"], c["docs_dir"], c["site_name"],'
        ' (c["nav"] ? 1 : 0)])')
    theme, docs_dir, site, has_nav = json.loads(cfg)
    assert theme == "material", theme
    assert docs_dir == "docs", docs_dir
    assert site == "bouncer", site
    assert has_nav == 1, "no nav"
    # drafts never ship: the config excludes them explicitly
    raw = MKDOCS.read_text()
    assert "exclude_docs" in raw and "drafts/" in raw
    # every nav entry points at a file that exists — the other direction
    # (files covered by nav) is T792's box
    for p in _nav_paths():
        assert (Path("docs") / p).exists(), p
    # the landing page ships with the skeleton
    assert Path("docs/index.md").exists()
