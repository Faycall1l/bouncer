"""P42 tests (T791-T810): docs site. mkdocs.yml is parsed with a real
YAML parser where one exists (ruby Psych — same deal as T750)."""
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

MKDOCS = Path("mkdocs.yml")


def _mkdocs_yaml(expr: str, path: Path = MKDOCS):
    """Run a ruby expression over parsed mkdocs.yml, return stdout."""
    ruby = shutil.which("ruby")
    if ruby is None:
        pytest.skip("no ruby — macOS and GH runners both ship one, "
                    "but a box without a YAML parser can't prove parsing")
    r = subprocess.run(
        [ruby, "-ryaml", "-rjson", "-e", expr, str(path)],
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


# Pages that teach or reference concepts link the glossary. The four
# operational documents are deliberately out of scope: runbooks and the
# release checklist point at SECURITY, not at a glossary.
_OPS_DOCS = {"SECURITY.md", "threat-model.md", "runbook.md",
             "RELEASE-CHECKLIST.md"}


def test_glossary_linked_from_every_relevant_page():  # T796
    pages = {p.name for p in Path("docs").glob("*.md")} - _OPS_DOCS - {
        "glossary.md"}
    missing = sorted(
        n for n in pages
        if "](glossary.md)" not in (Path("docs") / n).read_text())
    assert not missing, f"pages missing a glossary link: {missing}"
    # the definition page itself is reachable: nav (T792) + landing page
    assert "glossary.md" in _nav_paths()


def test_version_switcher_note():  # T797
    vp = Path("docs/versions.md")
    assert vp.exists(), "versions.md missing"
    text = vp.read_text()
    assert text.startswith("# Version notes")
    # covers all three tagged generations the box asks about
    for v in ("0.1", "0.2", "0.3"):
        assert v in text, v
    # switcher framing: why this page exists (older readers vs main)
    assert "switcher" in text.lower() and "CHANGELOG" in text
    # real behavior deltas, needles straight from the CHANGELOG entries
    for needle in ("E_PRESET", "--allow-threshold", "breaker-open",
                   "E_SNAPSHOT", "Stale-verdict"):
        assert needle in text, needle
    # drift guard: the page names the CURRENT package version, so the
    # 0.4.0 release box must come back and update this page on bump
    version = re.search(r'^version = "([^"]+)"',
                        Path("pyproject.toml").read_text(), re.MULTILINE).group(1)
    assert version in text, f"versions.md must mention current {version}"
    # reachable: nav entry + landing page link
    assert "versions.md" in _nav_paths()
    assert "](versions.md)" in Path("docs/index.md").read_text()


# --- T798: internal link checker -------------------------------------
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def _strip_code(text: str) -> str:
    """Drop fenced blocks and inline spans — links there aren't links."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return re.sub(r"`[^`]*`", "", text)


def _slug(heading: str) -> str:
    """GitHub/markdown-toc heading slug (parens stripped, spaces→hyphens)."""
    h = heading.strip().lower()
    h = re.sub(r"[^\w\s-]", "", h)
    return re.sub(r"\s+", "-", h.strip())


def _headings(text: str) -> set:
    return {_slug(m.group(1))
            for m in re.finditer(r"^#{1,6}\s+(.+)$", _strip_code(text), re.MULTILINE)}


def test_internal_link_checker():  # T798
    problems = []
    for p in sorted(Path("docs").glob("*.md")):
        text = _strip_code(p.read_text())
        for _label, href in _LINK_RE.findall(text):
            # external schemes and absolute paths are out of scope here
            if href.startswith(("http://", "https://", "mailto:", "//", "/")):
                continue
            path, _, anchor = href.partition("#")
            if not path:
                target = p  # same-page anchor
            else:
                cands = [p.parent / path]
                if path.endswith("/"):
                    cands.append(p.parent / path / "index.md")
                elif not path.endswith(".md"):
                    cands.append(p.parent / (path + ".md"))
                target = next((c for c in cands if c.exists()), None)
                if target is None:
                    problems.append(f"{p.name}: dead link {href}")
                    continue
            if anchor and anchor not in _headings(target.read_text()):
                problems.append(
                    f"{p.name}: dead anchor {href} — no heading slugs to "
                    f"{anchor!r} in {target.name}")
    assert not problems, "\n".join(problems)


def test_code_blocks_language_tagged():  # T799
    untagged, tagged = [], 0
    for p in sorted(Path("docs").glob("*.md")):
        in_fence = False
        for i, line in enumerate(p.read_text().splitlines(), 1):
            s = line.strip()
            if not s.startswith("```"):
                continue
            info = s[3:].strip()
            if not in_fence:
                in_fence = True
                if info:
                    tagged += 1
                else:
                    untagged.append(f"{p.name}:{i}")  # opener with no language
            else:
                if info:
                    # a tagged ``` inside a fence is a malformed nested
                    # opener — the closer must be bare
                    untagged.append(f"{p.name}:{i} (nested opener)")
                in_fence = False
    assert not untagged, f"unlanguage-tagged fences: {untagged}"
    # floor so a scanner that reads nothing can't pass vacuously
    assert tagged >= 10, f"only {tagged} tagged fences found — scanner broken?"


def _fence_info(lines, i):
    """Info string of a fence line at index i, or None if not a fence."""
    s = lines[i].strip()
    return s[3:].strip() if s.startswith("```") else None


def test_mermaid_has_ascii_fallback():  # T800
    problems, found = [], 0
    for p in sorted(Path("docs").glob("*.md")):
        lines = p.read_text().splitlines()
        mermaids = [i for i in range(len(lines))
                    if _fence_info(lines, i) == "mermaid"]
        texts = [i for i in range(len(lines))
                 if _fence_info(lines, i) == "text"]
        headings = [i for i, l in enumerate(lines) if re.match(r"^#{1,6} ", l)]
        for mi in mermaids:
            found += 1
            # a plain-text block in the SAME section (no heading between
            # either fence and the other) serves as the fallback
            same_section = any(
                not any(min(mi, ti) < h < max(mi, ti) for h in headings)
                for ti in texts)
            if not same_section:
                problems.append(
                    f"{p.name}:{mi + 1} mermaid block has no same-section "
                    "ascii fallback")
    assert not problems, problems
    # the two architecture diagrams exist today — pin the floor so a
    # scanner regression can't pass vacuously
    assert found >= 2, f"expected >= 2 mermaid diagrams, found {found}"


def test_docs_deploy_workflow_behind_flag():  # T801
    wf = Path(".github/workflows/docs.yml")
    assert wf.exists(), "docs workflow missing"
    text = wf.read_text()
    # triggers: docs-touching PRs (build check), main pushes, manual runs
    assert "pull_request" in text and "workflow_dispatch" in text
    # the build is the same strict command that must pass locally...
    assert "mkdocs build --strict" in text
    # ...with mkdocs 2.0 excluded (material depends on 1.x systems)
    assert 'mkdocs>=1.6,<2' in text and "mkdocs-material" in text
    # THE FLAG: publish steps gated on the DOCS_DEPLOY repo variable —
    # unset (default) means nothing ever reaches Pages
    flag = "vars.DOCS_DEPLOY == 'true'"
    assert text.count(flag) == 2, "artifact upload and deploy both gated"
    assert "DOCS_DEPLOY" in text.split("jobs:")[0], \
        "flag must be documented in the workflow header"
    # no secret-based alternate publish path
    assert "secrets." not in text
    # Pages plumbing: artifact, deploy action, OIDC perms, the env
    for needle in ("actions/upload-pages-artifact", "actions/deploy-pages",
                   "pages: write", "id-token: write", "github-pages"):
        assert needle in text, needle
    # and the whole file is real YAML with build before deploy, deploy
    # needing build, and the flag expression inside the deploy job itself
    jobs = json.loads(_mkdocs_yaml(
        'print JSON.generate(YAML.load_file(ARGV[0])["jobs"]'
        '.transform_values { |j| {"if" => j["if"], "needs" => j["needs"]} })',
        wf))
    assert list(jobs) == ["build", "deploy"], jobs
    assert jobs["deploy"]["needs"] == "build"
    assert flag in jobs["deploy"]["if"]


def test_search_friendly_headings():  # T802
    problems = []
    for p in sorted(Path("docs").glob("*.md")):
        lines = _strip_code(p.read_text()).splitlines()
        heads = [(len(m.group(1)), m.group(2), i)
                 for i, l in enumerate(lines)
                 if (m := re.match(r"^(#{1,6})\s+(.+)$", l))]
        # exactly one H1 per page: it is the page's title in search
        # results and in the rendered toc — six (T149 demo-script had
        # '#' comment lines that markdown reads as headings) broke that
        h1s = [h for h in heads if h[0] == 1]
        if len(h1s) != 1:
            problems.append(f"{p.name}: {len(h1s)} H1 headings (want exactly 1)")
        # unique heading slugs within a page — duplicate anchors get
        # -1 suffixes and search can't tell the sections apart
        slugs = Counter(_slug(h[1]) for h in heads)
        dups = sorted(s for s, c in slugs.items() if c > 1)
        if dups:
            problems.append(f"{p.name}: duplicate headings {dups}")
        # no skipped levels (h2 -> h4): the toc tree must nest honestly
        for j in range(1, len(heads)):
            if heads[j][0] > heads[j - 1][0] + 1:
                problems.append(
                    f"{p.name}:{heads[j][2] + 1} skips a heading level "
                    f"(h{heads[j - 1][0]} -> h{heads[j][0]})")
    assert not problems, "\n".join(problems)
