"""P42 tests (T791-T810): docs site. mkdocs.yml is parsed with a real
YAML parser where one exists (ruby Psych — same deal as T750)."""
import json
import re
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


def test_nav_covers_every_doc_file():  # T792
    nav = set(_nav_paths())
    files = {p.name for p in Path("docs").glob("*.md")}
    # every published page is reachable from the nav — no orphans
    assert files <= nav, sorted(files - nav)
    # every nav entry is a real file, drafts excluded (T791's direction,
    # pinned once more so a broken nav can't land with this test green)
    assert nav <= files, sorted(nav - files)
    drafts = {str(p.relative_to("docs")) for p in Path("docs").rglob("*.md")
              if "drafts" in p.parts}
    assert not (nav & drafts), sorted(nav & drafts)


def test_getting_started_page():  # T793
    gs = Path("docs/getting-started.md").read_text()
    assert gs.startswith("# Getting started")
    # the three stages, in order: install → first decision → serve
    stages = [gs.index("## 1. Install"), gs.index("## 2. First decision"),
              gs.index("## 3. Serve")]
    assert stages == sorted(stages), "stages out of order"
    assert 'pip install -e ".[server,demo]"' in gs
    assert "3.10" in gs and "3.13" in gs  # the CI matrix, stated
    assert "bouncer check" in gs and "bouncer serve" in gs
    assert "x-api-key" in gs and "/predict" in gs
    # exit codes match the CLI contract (0/2/3/4)
    for row in ("| 0 | allow |", "| 2 | delete", "| 3 | escalate",
                "| 4 | configuration"):
        assert row in gs, row
    # honesty lint: no invented confidence numbers on this page — the
    # format shows 0.NN placeholders, measured values live in BENCHMARKS
    assert not re.search(r"conf 0\.\d\d", gs), "invented confidence?"
    assert "BENCHMARKS" in gs
    # discoverable: linked from the landing page, present in the nav
    assert "getting-started.md" in Path("docs/index.md").read_text()
    assert "getting-started.md" in _nav_paths()


def test_cookbook_five_recipes():  # T794
    cb = Path("docs/cookbook.md").read_text()
    assert cb.startswith("# Cookbook")
    # exactly five recipes, each verified against the code it names
    recipes = re.findall(r"^## \d\. (.+)$", cb, re.MULTILINE)
    assert len(recipes) == 5, recipes
    for want in ("Discord", "Self-host", "gates", "multilingual", "Back up"):
        assert any(want.lower() in r.lower() for r in recipes), want
    # recipe 1: the real adapter command + the real dry-run switch (T697)
    assert "DISCORD_TOKEN" in cb and "discord_bot" in cb
    assert "BOUNCER_DRY_RUN" in cb
    # recipe 2: real compose facts (services, volumes, env-driven secrets)
    assert "docker compose up" in cb and ".env.example" in cb
    assert "hf-cache" in cb and ":8000" in cb and ":7860" in cb
    # recipe 3: both gate flags, both JSON keys, the strike knob
    for needle in ("--allow-threshold", "--delete-threshold",
                   "allow_threshold", "BOUNCER_BAN_AT"):
        assert needle in cb, needle
    # recipe 4: language-tagged presets + the routing claim from README
    assert "--preset es" in cb and "--preset ar" in cb and "PRESET_LANG" in cb
    # recipe 5: the runbook does the heavy lifting — linked, not duplicated
    assert "runbook.md" in cb and "snapshot save" in cb and "E_SNAPSHOT" in cb
    # honesty lint: no invented confidence numbers
    assert not re.search(r"conf 0\.\d\d", cb), "invented confidence?"
    # discoverable: nav + landing page
    assert "cookbook.md" in _nav_paths()
    assert "cookbook.md" in Path("docs/index.md").read_text()


def test_api_reference_renders_api_md_unchanged():  # T795
    # the site's API page is docs/api.md itself — the same file the
    # contract tests pin (T141/T394, test_p22), served verbatim
    nav = json.loads(_mkdocs_yaml(
        'print JSON.generate(YAML.load_file(ARGV[0])["nav"])'))

    def pairs(items):
        out = []
        for it in items:
            if isinstance(it, dict):
                for k, v in it.items():
                    out.append((k, v))
                    if isinstance(v, list):
                        out += pairs(v)
        return out

    assert ("API", "api.md") in pairs(nav), "API nav entry must be api.md itself"
    # no generated or duplicated reference page anywhere under docs/
    assert not Path("docs/api-reference.md").exists()
    assert not Path("docs/api").exists()
    for p in Path("docs").rglob("*.md"):
        if p.name == "api.md" or "drafts" in p.parts:
            continue
        assert not p.read_text().startswith("# API reference"), \
            f"{p} duplicates the API reference H1"
    # no build hooks — mkdocs serves docs/ byte-for-byte
    raw = MKDOCS.read_text()
    assert "hooks:" not in raw, "page-rewriting hook would break 'unchanged'"
    # the page itself is still the standalone reference doc
    assert Path("docs/api.md").read_text().startswith("# API reference")
