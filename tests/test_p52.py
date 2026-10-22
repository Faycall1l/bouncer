"""P52 tests: docs & versioned site (T991–T1010)."""
# Apache-2.0. See LICENSE.

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _load_build_script():
    spec = importlib.util.spec_from_file_location(
        "bouncer_build_docs_version", "scripts/build_docs_version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_t991_versioned_docs_build_script_per_tag_snapshot(tmp_path,
                                                           monkeypatch):  # T991
    """T991: per-tag site snapshots — the script, its fidelity, and its
    honest failure modes, all pinned where fidelity actually lives: a
    throwaway repository whose HEAD, annotated tag, and pre-docs tag
    each hold different bytes. Pins: the wiring (strict mkdocs build of
    the EXTRACTED config into <site-dir>/<ref>, default root `site`),
    the no-mutation guarantee (no git worktree/checkout/stash/reset —
    extraction is git archive into a temp dir, so a snapshot can never
    see an edited working tree), unknown refs fail named and friendly
    (exit 1) before any build machinery, no args is a usage error
    (exit 2), --help exits 0, and the docs-era guard: a ref with no
    mkdocs.yml exits 1 saying so instead of shipping a half-site (every
    real tag before v0.4.0 is one of those). The tag's bytes beat HEAD
    through the module's own extract_snapshot — annotated-tag peeling
    (`^{commit}`) included."""
    mod = _load_build_script()
    script = Path("scripts/build_docs_version.py")
    src = script.read_text()
    script_abs = script.resolve()  # before chdir into the throwaway repo

    # the wiring: strict build, extracted config, per-ref dir, site root
    assert "T991" in src
    assert '"mkdocs", "build", "--strict"' in src
    assert '"--config-file"' in src and '"--site-dir"' in src
    assert 'default="site"' in src and '"git", "archive"' in src
    # the repo is never mutated — extraction only
    for banned in ("git worktree", "git checkout", "git stash",
                   "git reset"):
        assert banned not in src, f"snapshot must not mutate: {banned}"

    # unknown ref: friendly named failure before any build (mkdocs-free)
    r = subprocess.run(
        [sys.executable, "scripts/build_docs_version.py", "v9.9.9-nope"],
        check=False, capture_output=True, text=True)
    assert r.returncode == 1, r.stdout
    assert "v9.9.9-nope" in r.stderr and "unknown ref" in r.stderr

    # usage contracts: --help exits 0, no args is a usage error (2)
    r = subprocess.run(
        [sys.executable, "scripts/build_docs_version.py", "--help"],
        check=False, capture_output=True, text=True)
    assert r.returncode == 0 and "--site-dir" in r.stdout
    r = subprocess.run([sys.executable,
                        "scripts/build_docs_version.py"],
                       check=False, capture_output=True, text=True)
    assert r.returncode == 2, "no args must be a usage error"

    # fidelity on a repo where the refs disagree with each other
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    def git(*args):  # the throwaway repo's own commits and tags
        return subprocess.run(
            ["git", "-C", str(repo), "-c", "user.email=t@t",
             "-c", "user.name=t", *args],
            check=True, capture_output=True)

    (repo / "README.md").write_text("nothing to snapshot here\n")
    git("add", ".")
    git("commit", "-qm", "pre-docs")
    git("tag", "pre-docs")  # lightweight tag, no mkdocs.yml at it
    old_yaml, old_index = "site_name: OLDTAG\n", "# old tag docs\n"
    (repo / "mkdocs.yml").write_text(old_yaml)
    (repo / "docs").mkdir()
    (repo / "docs" / "index.md").write_text(old_index)
    git("add", ".")
    git("commit", "-qm", "docs land")
    old_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             check=True, capture_output=True,
                             text=True).stdout.strip()
    git("tag", "-a", "v0.0.0", "-m", "snapshot me")  # annotated
    (repo / "mkdocs.yml").write_text("site_name: HEADTREE\n")
    (repo / "docs" / "index.md").write_text("# head docs\n")
    git("add", ".")
    git("commit", "-qm", "docs move on")

    monkeypatch.chdir(repo)  # the module's git calls inherit this cwd
    snap = mod.extract_snapshot("v0.0.0", tmp_path / "snap")
    assert snap == old_sha, "annotated tag peeled to the wrong commit"
    assert (tmp_path / "snap" / "mkdocs.yml").read_text() == old_yaml
    assert (tmp_path / "snap" / "docs" / "index.md").read_text() == old_index
    mod.extract_snapshot("HEAD", tmp_path / "snap-head")
    assert (tmp_path / "snap-head" / "mkdocs.yml").read_text() \
        == "site_name: HEADTREE\n", "ref is ignored — working tree leaked"

    # docs-era guard: a pre-docs ref names its own problem, exit 1 —
    # exercised through the CLI (stderr carries the message)
    r = subprocess.run(
        [sys.executable, str(script_abs), "pre-docs"],
        check=False, capture_output=True, text=True)
    assert r.returncode == 1, r.stdout
    assert "mkdocs.yml" in r.stderr and "did not exist" in r.stderr


def test_t991_snapshot_build_strict_where_mkdocs_exists(tmp_path):  # T991
    """T991: the real build path, end to end — where mkdocs-material
    exists (the docs workflow, and any dev machine after pip installing
    it; the CI test job never installs docs tooling, so this one skips
    there by design), a HEAD snapshot builds --strict into
    <site-dir>/<ref>/ with a real index.html, and site-dir isolation
    holds: building a snapshot cleans only its own directory — a sibling
    tag's files under the same root survive untouched (that is what lets
    CI publish root site + many tag snapshots side by side)."""
    import importlib.util as _ilu

    if not all(_ilu.find_spec(m) for m in ("mkdocs", "pymdownx")):
        pytest.skip("mkdocs-material not installed here — the docs "
                    "workflow (and dev machines) run this path")
    root = tmp_path / "site"
    sibling = root / "v0.0.0" / "keep.txt"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("must survive the sibling build\n")
    r = subprocess.run(
        [sys.executable, "scripts/build_docs_version.py", "HEAD",
         "--site-dir", str(root)],
        check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    snap = root / "HEAD"
    assert (snap / "index.html").exists(), "strict build produced no site"
    assert "bouncer" in (snap / "index.html").read_text().lower()
    # directory URLs: pages land as <name>/index.html in the snapshot
    assert (snap / "versions" / "index.html").exists(), \
        "docs page missing from snapshot"
    assert sibling.read_text() == "must survive the sibling build\n", \
        "mkdocs cleaned outside its site-dir"
    assert "HEAD" in r.stdout and "-> " in r.stdout, "no receipt line"
