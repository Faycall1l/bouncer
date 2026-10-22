"""P52 tests: docs & versioned site (T991–T1010)."""
# Apache-2.0. See LICENSE.

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


def _slug(heading: str) -> str:
    """python-markdown's toc slugify, as material renders heading ids:
    strip non-word chars, then collapse dash/space runs to one dash."""
    return re.sub(r"[-\s]+", "-",
                  re.sub(r"[^\w\s-]", "", heading).strip().lower())


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


def test_t992_docs_workflow_builds_versioned_artifacts_behind_flag():  # T992
    """T992: the docs workflow builds per-tag site snapshots behind the
    same DOCS_DEPLOY flag as publishing — pinned at the wiring level,
    because the flag is a repo variable no test can flip: where it is
    off nothing versioned is built or uploaded, where it is on the loop
    runs T991's script (whose mechanics test_p52 pins elsewhere).
    Pins: the checkout fetches full history (a shallow clone carries no
    tags, so the loop would silently build nothing), the ROOT build
    runs before the snapshot loop and the upload after it (mkdocs
    cleans its site-dir — snapshots written earlier would be wiped from
    the artifact), the step's gate matches the upload gate byte for
    byte, and the loop walks git tag filtering pre-docs refs via
    cat-file instead of letting the script fail on them — skipped tags
    still say why in the log."""
    text = Path(".github/workflows/docs.yml").read_text()
    assert "T992" in text
    assert "fetch-depth: 0" in text, "shallow clones carry no tags"
    root_i = text.index("mkdocs build --strict")
    snap_i = text.index("Build versioned tag snapshots")
    up_i = text.index("Upload Pages artifact")
    assert root_i < snap_i < up_i, "order must be root, tags, upload"
    step = text[snap_i:up_i]  # exactly the snapshot step's own block

    def gate_of(chunk: str) -> str:
        return next(ln.strip() for ln in chunk.splitlines()
                    if ln.strip().startswith("if:"))

    # gated exactly like publishing, down to the byte
    assert gate_of(step) == gate_of(text[up_i:]), \
        "snapshots must gate exactly like the upload"
    assert "pull_request" in gate_of(step), "PRs must not build snapshots"
    assert "for tag in $(git tag)" in step
    assert 'git cat-file -e "$tag:mkdocs.yml"' in step, "pre-docs filter"
    assert 'python scripts/build_docs_version.py "$tag" --site-dir site' \
        in step, "the loop must call T991's script, not mkdocs directly"
    assert "skip" in step, "filtered tags must say why in the CI log"


def test_t993_versions_page_resolves_every_entry_to_its_delta():  # T993
    """T993: the switcher story catches up with T991/T992 — versions.md
    stops saying 'once versioned builds ship' and every version a reader
    can be on resolves through one table to its delta section. Pins:
    every git tag in the repo is named in the table (docs-era tags with
    their snapshot path, pre-docs tags with the honest no-snapshot
    gap), every local anchor the page hands out resolves to a real
    heading slug on the same page (the table's links can't rot), the
    T809 freshness marker still stands exactly once, and the stale
    conditional language is gone. A future docs-era tag without a row
    fails here on purpose — an entry that resolves to nothing is the
    bug this box exists to prevent."""
    text = Path("docs/versions.md").read_text()
    assert "T993" in text
    assert "once versioned builds ship" not in text, "stale conditional"
    assert text.count("_(Last checked against v0.4.0.)_") == 1, \
        "T809's freshness marker must stand exactly once"

    tags = [t for t in subprocess.run(
        ["git", "tag"], check=False, capture_output=True,
        text=True).stdout.split() if t]
    docs_era, pre_docs = [], []
    for t in tags:
        has_docs = subprocess.run(
            ["git", "cat-file", "-e", f"{t}:mkdocs.yml"],
            check=False, capture_output=True).returncode == 0
        (docs_era if has_docs else pre_docs).append(t)
    assert docs_era and pre_docs, "the split this page tells must exist"
    for t in docs_era:
        assert f"`{t}`" in text, f"{t} has no table row"
        assert f"/{t}/" in text, f"{t} row doesn't name its snapshot dir"
    for t in pre_docs:
        assert f"`{t}`" in text, f"{t} missing from the no-snapshot rows"

    # every anchor handed out on the page resolves to a real heading
    # slug (the toc rule, via _slug — material's id generator)
    headings = re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
    slugs = {_slug(h) for h in headings}
    for anchor in re.findall(r"\]\(#([^)]+)\)", text):
        assert anchor in slugs, f"anchor #{anchor} resolves to nothing"


def test_t994_api_route_table_covers_every_endpoint():  # T994
    """T994: api.md gains the full route table — every endpoint the
    server serves in one place, each row carrying its P44–P49-era
    behavior. Completeness is pinned against the SOURCE, not prose: the
    test parses serve.py's route decorators (the only place routes are
    declared) and asserts set equality with the table's rows, so an
    endpoint without a row — or a row without an endpoint — fails here
    in both directions. Also pins: /ready and /presets/{name} are IN
    the table (they used to live only in prose sections), the floor of
    eleven routes holds, and every details-link anchor in the table
    resolves to a real heading slug on the page."""
    text = Path("docs/api.md").read_text()
    assert "T994" in text
    src = Path("src/gatekeeper/serve.py").read_text()
    routes = {f"{m.upper()} {p}" for m, p in re.findall(
        r'@app\.(get|post)\("([^"]+)"\)', src)}
    assert len(routes) >= 11, f"serve.py route set changed: {sorted(routes)}"
    for buried in ("GET /ready", "GET /presets/{name}"):
        assert buried in routes, f"{buried} left serve.py — update this test"
    table = {f"{m} {p}" for m, p in re.findall(
        r"^\| (GET|POST) \| `(/[^`]+)` \|", text, re.MULTILINE)}
    assert table == routes, (
        f"rows missing: {sorted(routes - table)}; "
        f"stale rows: {sorted(table - routes)}")

    # the table's details links resolve to real headings on this page
    block = text.split("## Route table (T994)")[1].split("\n## ")[0]
    headings = re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
    slugs = {_slug(h) for h in headings}
    anchors = re.findall(r"\]\(#([^)]+)\)", block)
    assert len(anchors) >= 8, "every covered row must link its details"
    for anchor in anchors:
        assert anchor in slugs, f"#{anchor} resolves to nothing"


def test_t995_error_code_index_refresh_covers_p44_p50():  # T995
    """T995: the error-code index gets its P44-P50 audit. T808's test
    already pins set-coverage both ways (every emitted code has a row,
    every row has an emitter) — this pins what coverage can't: the
    semantics P44-P50 hardening added. E_MODEL gained a second surface
    (a dead model is a coded 503 on the /v1/systemone passthrough,
    T833 — never a fabricated answer, never a hung socket) and the row
    that described only the pre-hardening server would still pass T808.
    Also pins: each P44-P50-era row carries the T-number of the work
    that created or changed it (E_VERDICT T865, E_PACK_SIG T873,
    E_RULES_TEXT's zero-width expansion T879), and the heading carries
    the refresh cite so the next audit knows this pass happened."""
    text = Path("docs/error-codes.md").read_text()
    assert "T995" in text
    assert text.splitlines()[0].endswith("(T808, refreshed at T995)")

    def row(code: str) -> str:
        return next(ln for ln in text.splitlines()
                    if ln.startswith(f"| `{code}` |"))

    # E_MODEL: both surfaces live in one row, the 503 one is T833's
    emodel = row("E_MODEL")
    assert "503" in emodel and "T833" in emodel, \
        "the passthrough's 503 E_MODEL surface is undocumented"
    assert "/v1/systemone" in emodel
    assert "escalate" in emodel, "the scored-route surface must stay"

    # the P44-P50 rows each cite the work that made them
    for code, cite in (("E_VERDICT", "T865"), ("E_PACK_SIG", "T873"),
                       ("E_RULES_TEXT", "T879")):
        assert cite in row(code), f"{code} lost its {cite} cite"


def test_t996_environment_sweep_reverified_with_honest_qualifiers():  # T996
    """T996: the environment.md sweep, re-run for P52. T807's test IS
    the both-directions inventory gate (every var the code reads has a
    row — dynamic prefixes and example scripts included — and every
    row has a reader) and it stays green: nothing was added or removed
    since T979's P44-P50 pass. What that sweep cannot see, this pins:
    the two rows the SERVER never reads keep their honest qualifiers
    (BOUNCER_URL is the shipped client example's convenience,
    BOUNCER_PRESET the container self-test's — a reader who exports
    them expecting server behavior must be told otherwise), the
    freshness marker stands exactly once with the refresh history
    riding its own lines beneath it (T809's rule), and both refresh
    notes — T979's and this re-verification — are on the page."""
    text = Path("docs/environment.md").read_text()
    assert "T996" in text
    assert text.startswith("# Environment variables (T807)")
    # T809's marker stands exactly once; refresh notes are separate
    # lines under it, never replacing it
    assert text.count("_(Last checked against v0.4.0.)_") == 1

    def row(var: str) -> str:
        return next(ln for ln in text.splitlines()
                    if ln.startswith(f"| `{var}` |"))

    url, preset = row("BOUNCER_URL"), row("BOUNCER_PRESET")
    assert "not read by the server" in url, \
        "BOUNCER_URL must keep its client-side-only qualifier"
    assert "self-test" in preset and "docker-entrypoint" in preset, \
        "BOUNCER_PRESET must keep its container-self-test qualifier"
    # the refresh history: T979's pass and this re-verification both
    # stand, each on its own _( ... )_ note
    assert "_(Refreshed at T979" in text, "T979's note went missing"
    assert "_(Re-verified at T996" in text, "this pass must record itself"


def test_t997_cookbook_recipes_use_only_real_commands():  # T997
    """T997: four cookbook recipes — batch scoring, appeals, metrics
    scrape, pack signing. The completeness half (they exist, numbered,
    each citing T997) is pinned here; the honesty half is pinned
    against the CLI source itself: every `bouncer <cmd>` the new
    recipes run must be a real argparse subparser in cli.py — a
    cookbook that invents a flag is worse than no cookbook. The API
    recipe's endpoint is checked against serve.py's routes the same
    way, and the pack recipe's sign/verify claims are pinned against
    the commands T872/T873 actually built."""
    text = Path("docs/cookbook.md").read_text()
    assert "T997" in text
    for heading in ("## 6. Score a whole batch in one request (recipe T997)",
                    "## 7. Work an appeal (recipe T997)",
                    "## 8. Scrape metrics into Prometheus (recipe T997)",
                    "## 9. Sign and verify a rules pack (recipe T997)"):
        assert heading in text, heading

    # everything the four recipes execute must exist in the real CLI
    cli = Path("src/gatekeeper/cli.py").read_text()
    subparsers = set(re.findall(r'add_parser\("([a-z-]+)"', cli))
    new_recipes = text.split("## 6. Score a whole batch")[1]
    used = set(re.findall(r"\bbouncer ([a-z]+)\b", new_recipes))
    invented = sorted(c for c in used if c not in subparsers)
    assert not invented, f"recipes invent CLI commands: {invented}"
    for needed in ("review", "adjudicate", "amnesty", "export", "pack"):
        assert needed in used, f"recipe set stopped exercising {needed}"

    # the batch recipe's endpoint is a real route (T994's source)
    routes = {f"{m.upper()} {p}" for m, p in re.findall(
        r'@app\.(get|post)\("([^"]+)"\)',
        Path("src/gatekeeper/serve.py").read_text())}
    assert "POST /predict/batch" in routes
    assert "predict/batch" in new_recipes
    # the signing claims: the commands and the failure code are real
    assert '"sign"' in cli and '"verify"' in cli and '"diff"' in cli
    assert "E_PACK_SIG" in new_recipes


def test_t998_getting_started_covers_the_050_surface():  # T998
    """T998: getting-started catches up with the surface 0.5.0 will
    ship — what a NEW reader needs from P44-P51, pinned against the
    sources each claim comes from: `bouncer doctor` is a real
    subparser (cli.py) and the page describes it weightlessly (no
    model, no network — that's its T727 contract), GET /metrics is a
    real route (serve.py) and the page puts /stats and /metrics behind
    the correct key gate (T778), the P44 hardening claims match
    api.md's (1 MB refused before auth, T843; unknown fields 422,
    T835), --lang auto exists (cli.py's T893 handling), the cookbook
    and api reference are linked from Next, and the freshness marker
    still stands exactly once (T1005 flips it at release)."""
    text = Path("docs/getting-started.md").read_text()
    assert "T998" in text
    assert text.splitlines()[0] == "# Getting started (T793, refreshed at T998)"
    assert text.count("_(Last checked against v0.4.0.)_") == 1

    cli = Path("src/gatekeeper/cli.py").read_text()
    assert 'add_parser("doctor' in cli, "doctor left the CLI"
    assert "bouncer doctor" in text and "T727" in text
    assert "network" in text, "doctor's weightless contract belongs here"

    routes = {p for _, p in re.findall(
        r'@app\.(get|post)\("([^"]+)"\)', Path("src/gatekeeper/serve.py").read_text())}
    for route in ("/metrics", "/stats", "/ready"):
        assert route in routes, f"{route} left serve.py"
    assert "GET /metrics" in text and "Prometheus" in text
    assert "T778" in text, "the key-gate cite is the point of the line"

    # the P44 hardening claims, same wording api.md commits to
    api = Path("docs/api.md").read_text()
    assert "1 MB" in text and "before auth" in text and "T843" in text
    assert "413" in api and "T843" in api
    assert "T835" in text and "422" in text

    assert '"auto"' in cli and "--lang auto" in text  # T893's surface
    for link in ("cookbook.md", "api.md"):
        assert f"]({link})" in text, f"Next lost its {link} link"


def test_t999_release_checklist_gains_the_new_gates():  # T999
    """T999: the release checklist gains the gates P44-P52 added —
    the metrics report (T948) and i18n routing (T898). Pinned against
    the sources the commands come from: both runner files exist and
    are named verbatim, gate.py really dispatches the metrics kind and
    the all/--ci flags it advertises, and the checklist's regeneration
    warning names the CI job (T739) whose runner set --all actually
    gates — a checklist naming a command that doesn't exist is worse
    than a missing step."""
    text = Path("docs/RELEASE-CHECKLIST.md").read_text()
    assert "T999" in text
    assert text.splitlines()[0] == "# Release checklist (T669, updated at T999)"
    assert text.count("_(Last checked against v0.4.0.)_") == 1

    # the commands exist, verbatim
    for runner in ("eval/bench_metrics.py", "eval/eval_i18n.py",
                   "eval/gate.py"):
        assert Path(runner).exists(), runner
        assert runner in text, f"checklist must name {runner}"
    assert "gate.py --all --ci" in text

    # gate.py really dispatches what the checklist promises it gates
    gate = Path("eval/gate.py").read_text()
    assert 'return "metrics"' in gate, "the metrics kind left gate.py"
    assert '"metrics": collect_metrics' in gate
    bench = Path("eval/bench_metrics.py").read_text()
    assert "bench_metrics" in bench and "TestClient" in bench, \
        "the checklist's in-process claim must stay true"

    # the regeneration warning names T739's runner set
    assert "T739" in text
    ci = Path(".github/workflows/ci.yml").read_text()
    for runner in ("bench_pool.py", "breaker_sim.py", "bench_stub.py",
                   "bench_warm.py", "bench_stats.py", "bench_import.py",
                   "bench_questions.py", "bench_batch.py"):
        assert runner in ci and runner in text, f"{runner} drift"


def test_t1000_roadmap_sections_honest_about_p44_p50():  # T1000
    """T1000: two ROADMAP sections catch up with reality. The plugin
    section keeps its T805 status string (planned — design not started;
    P44-P50 built NO plugin surface and the page now says so instead of
    letting the era's hardening read as progress toward plugins) and
    names the seams the future design inherits — signed packs (T873),
    per-adapter passthrough + BOUNCER_ADAPTER_LANG (T897), P48's
    fine-tune pipeline, bounded /metrics families (T945). The versioned
    docs section graduates from promised to shipped, pinned against the
    receipts themselves: the script exists and is named, the workflow
    wires it behind the flag, versions.md resolves entries to deltas —
    and the honest remainder stands: DOCS_DEPLOY still gates publishing,
    so nothing reaches readers yet. T805's pins (the exact plugin
    status heading, DOCS_DEPLOY, the versions.md link) are restated
    here because this commit edits the very lines they check."""
    text = Path("docs/ROADMAP.md").read_text()
    assert "T1000" in text

    plug = text.split("## Plugins")[1].split("\n## ")[0]
    assert "Plugins (status: planned — design not started)" in text, \
        "T805's status heading must stand — no dishonest graduation"
    assert "built *no plugin surface*" in plug, \
        "the page must say plainly what the era did not build"
    for seam in ("T873", "BOUNCER_ADAPTER_LANG", "T897", "T945"):
        assert seam in plug, f"inherited seam {seam} unnamed"

    ver = text.split("## Versioned docs site")[1].split("\n## ")[0]
    assert "(status: shipped — builds wired, flag gates publishing)" in ver
    for cite in ("T991", "T992", "T993"):
        assert cite in ver, f"{cite}'s receipt missing from the section"
    # the receipts are the graduation evidence, not prose
    assert Path("scripts/build_docs_version.py").exists()
    assert "scripts/build_docs_version.py" in ver
    assert "scripts/build_docs_version.py" in Path(
        ".github/workflows/docs.yml").read_text(), "T992 wires the script"
    assert "T993" in Path("docs/versions.md").read_text()
    assert "DOCS_DEPLOY" in ver and "publishing is" in ver, \
        "the honest remainder: builds wired, publishing still off"

    # T805's pins this commit edits around
    assert "DOCS_DEPLOY" in text and "](versions.md)" in text


def test_t1001_glossary_terms_pin_what_they_define():  # T1001
    """T1001: the glossary gains the four terms P44-P50 introduced —
    appeal, amnesty, namespaced strike, script routing. Each definition
    is pinned against the source it describes, so the entry can't drift
    into vibes: the appeal linkage really is a T864 queue-row uuid in
    review.py and adapters really carry the APPEAL command; amnesty's
    CLI, its T974 audit row and T341's weight table (delete=2,
    flag=1, everything else 0 — the definition quotes those numbers,
    so the numbers are re-read from strikes.py here); the namespaced
    strike accrual really sits in _accrue on every path (T858); and
    script routing's ar/ru/zh claim is checked against detect_lang's
    own block (T857) with the serve-side autofill (T892) and --lang
    auto (T893) present. Every T-number the four entries cite must be
    a real box."""
    text = Path("docs/glossary.md").read_text()
    assert "T1001" in text
    assert text.count("_(Last checked against v0.4.0.)_") == 1

    def entry(term: str) -> str:
        lines = text.splitlines()
        start = next(i for i, ln in enumerate(lines)
                     if ln.startswith(f"* **{term}**"))
        rest = [ln for ln in lines[start + 1:] if not ln.startswith("* **")]
        return " ".join(lines[start:start + 1] + rest)

    appeal, amnesty = entry("appeal"), entry("amnesty")
    namespaced, routing = entry("namespaced strike"), entry("script routing")

    review = Path("src/gatekeeper/review.py").read_text()
    assert "T864" in appeal and "uuid.uuid4" in review and "T864" in review
    assert "queue-row id" in appeal or "queue row" in appeal
    explain = Path("src/gatekeeper/explain.py").read_text()
    assert "APPEAL" in review and "APPEAL" in explain, \
        "the command word lives in the review/explain surfaces"

    cli = Path("src/gatekeeper/cli.py").read_text()
    assert "T881" in amnesty and 'add_parser("amnesty' in cli
    assert "T974" in amnesty and "T881+T974" in cli, "the audit cite"
    assert "T341" in amnesty and "T865" in amnesty
    weights = Path("src/gatekeeper/strikes.py").read_text()
    wt = weights.split("def weight_for_action")[1].split("\ndef ")[0]
    assert '"delete": 2' in wt and '"flag": 1' in wt, \
        "the definition's numbers must match the table"

    init = Path("src/gatekeeper/__init__.py").read_text()
    assert "T858" in namespaced and "_accrue" in init and "T340+T858" in init

    common = Path("src/gatekeeper/adapters/common.py").read_text()
    block = common.split("def detect_lang")[1].split("\ndef ")[0]
    for tag in ("ar", "ru", "zh"):
        assert tag in block, f"detect_lang lost the {tag} tag"
    assert "T892" in routing and "T892" in Path(
        "src/gatekeeper/serve.py").read_text()
    assert "T893" in routing and '"--lang"' in cli

    # every T-number these entries cite is a real box
    todo = Path("TODO.md").read_text()
    for line in (appeal, amnesty, namespaced, routing):
        for t in set(re.findall(r"\bT\d{3,4}\b", line)):
            assert t in todo, f"glossary entry cites unknown box {t}"


def test_t1002_examples_rerun_green_on_current_surface(tmp_path,
                                                       monkeypatch):  # T1002
    """T1002: the three shipped example scripts re-run green against the
    surface P44-P51 left behind. 01 and 03 run their real mains on the
    stub-router protocol (the T806 harness) and their current-surface
    outputs are asserted, not just their exit codes: 03 must print the
    strikes field the T341-era accrual returns and render explain()
    without error, 01 must keep rule attribution in its line. 02 can't
    run without a server, so its wire contract is pinned against the
    server itself instead: the payload keys it POSTs must be fields
    ModReq actually declares (extra=forbid since T835 — a renamed
    field would 422 every copy-paster), and its error-shape and
    0/2/3/4 exit mapping must match what api.md commits to. Drift in
    any of those is the silent-staleness this box exists to catch."""
    repo = Path.cwd()  # pytest runs from the repo root; chdir comes below
    ex = repo / "docs/examples"
    sys.path.insert(0, "src")
    import gatekeeper

    class Stub:
        def __init__(self):
            self.a = {"rule": {"choice": "ok", "confidence": 0.95,
                               "probabilities": {"ok": 0.95}},
                      "harm": {"score": "safe"}, "hype": {"score": "chill"},
                      "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}

        def predict(self, state, questions):
            return {"answers": self.a}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gatekeeper, "_router", Stub())

    def load(name: str):
        spec = importlib.util.spec_from_file_location(
            f"bouncer_t1002_{name}", ex / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    m1 = load("01_in_process")
    assert m1.main() in (0, 2, 3)
    m3 = load("03_custom_rules")
    assert m3.main() in (0, 2, 3)
    pack = (tmp_path / "my-pack.json")
    assert pack.exists(), "03 stopped writing the pack file"
    assert json.loads(pack.read_text()) == m3.RULES
    assert hasattr(m3, "GATES") and m3.GATES.delete_threshold is not None

    # 02's wire contract vs the server's own request model
    api = (ex / "02_api_client.py").read_text()
    body = re.search(r"json\.dumps\((\{[^)]*\})\)", api).group(1)
    sent = set(re.findall(r'"(\w+)":', body))
    src = (repo / "src/gatekeeper/serve.py").read_text()
    modreq = src.split("class ModReq(BaseModel):")[1].split("\nclass ")[0]
    fields = set(re.findall(r"^    (\w+):", modreq, re.MULTILINE))
    assert sent and sent <= fields, f"02 sends fields the server refuses: {sent - fields}"
    assert '"extra": "forbid"' in modreq, "T835's contract under test"
    assert '{"detail": {"code", "message"}}' in api
    # the exit mapping shares getting-started's table (0/2/3 per action,
    # 4 = the API could not be used at all — the table's "configuration
    # error" row covers the CLI half of that class)
    gs = (repo / "docs/getting-started.md").read_text()
    for row in ("| 0 | allow |", "| 3 | escalate |",
                "| 4 | configuration error"):
        assert row in gs, row
    assert 'EXIT = {"allow": 0, "flag": 2, "delete": 2, "escalate": 3}' in api
    assert "return 4" in api, "02's could-not-use exit must stay"


def test_t1003_mkdocs_nav_equals_the_published_file_set():  # T1003
    """T1003: the nav still equals the file set — the P52-hardened
    version of T792. T792 compares nav against docs/*.md at the TOP
    level; this one defines the file set the way mkdocs itself does:
    every .md under docs/ recursively, minus whatever mkdocs.yml's
    exclude_docs actually excludes (drafts/ today). A new published
    subdirectory page — orphaned from the nav — fails here even though
    T792's glob can't see it. Both directions hold (no orphan files,
    no dangling nav entries), the exclusion list is parsed from the
    config rather than hardcoded, and a floor stops a mass deletion
    from passing the equality vacuously."""
    raw = Path("mkdocs.yml").read_text()

    # exclude_docs: block scalar — the patterns mkdocs ships without
    block = raw.split("exclude_docs: |")[1]
    patterns = []
    for line in block.splitlines()[1:]:
        if line and not line.startswith((" ", "\t")):
            break
        if line.strip():
            patterns.append(line.strip())
    assert "drafts/" in patterns, patterns

    # nav: every "Title: path.md" (or bare "- path.md") until the next
    # top-level key
    nav_block = raw.split("\nnav:")[1]
    nav = []
    for line in nav_block.splitlines()[1:]:
        if line and not line.startswith((" ", "\t")):
            break
        m = re.search(r":\s*(\S+\.md)\s*$", line) or \
            re.search(r"-\s*(\S+\.md)\s*$", line)
        if m:
            nav.append(m.group(1))
    nav = set(nav)

    def excluded(rel: str) -> bool:
        return any(rel.startswith(p) for p in patterns)

    files = {str(p.relative_to("docs")) for p in Path("docs").rglob("*.md")
             if not excluded(str(p.relative_to("docs")))}
    assert len(files) >= 20, f"file set collapsed: {sorted(files)}"
    assert files <= nav, f"published but unreachable: {sorted(files - nav)}"
    assert nav <= files, f"nav points at nothing: {sorted(nav - files)}"


def test_t1004_link_checker_covers_every_shipped_page():  # T1004
    """T1004: one link check over the union of everything a reader can
    reach — root entry files (T821's set) AND every page mkdocs ships
    (T798's set, extended to be exclusion-aware and recursive like
    T1003: docs/**/*.md minus exclude_docs — drafts/ never ships, so
    its draft-era links stay out of court). Same helpers as both
    boxes (imported from test_p42 — one _LINK_RE, one slugger), so
    dead relative links and dead anchors fail identically on either
    surface. The T792/T1003 equality tests guarantee nav == file set;
    this one guarantees every file IN that set actually links clean."""
    sys.path.insert(0, str(Path(__file__).parent))
    from test_p42 import _LINK_RE, _headings, _strip_code

    raw = Path("mkdocs.yml").read_text()
    block = raw.split("exclude_docs: |")[1]
    patterns = []
    for line in block.splitlines()[1:]:
        if line and not line.startswith((" ", "\t")):
            break
        if line.strip():
            patterns.append(line.strip())

    shipped = [p for p in Path(".").glob("*.md")]  # root entry files
    shipped += [p for p in Path("docs").rglob("*.md")
                if not any(str(p.relative_to("docs")).startswith(pat)
                           for pat in patterns)]
    problems, checked = [], 0
    for p in sorted(shipped):
        text = _strip_code(p.read_text())
        for _label, href in _LINK_RE.findall(text):
            if href.startswith(("http://", "https://", "mailto:", "//", "/")):
                continue
            checked += 1
            path, _, anchor = href.partition("#")
            target = p if not path else Path(p.parent / path)
            if not target.exists():
                problems.append(f"{p}: dead link {href}")
                continue
            if anchor and anchor not in _headings(target.read_text()):
                problems.append(f"{p}: dead anchor {href}")
    assert not problems, "\n".join(problems)
    # floor: the union links heavily (README into docs/, pages to each
    # other) — a drop to dozens means the scanner lost its grip
    assert checked >= 60, f"only {checked} relative links — scanner broken?"


def test_t1005_freshness_markers_track_the_pre_release_version():  # T1005
    """T1005: every shipped page's freshness marker sits at pyproject's
    version, so the bump at release (T1011) can't leave a stale v0.4.0
    claim behind. T809 already pins this for top-level docs/*.md with
    an X.Y.Z-only regex; this is the pre-release hardening: the parse
    takes pyproject's FULL version string (rc/dev suffixes included —
    T809's regex would report '0 markers' on an rc version, so the
    release machinery needs a form that survives one), the file set is
    the recursive exclusion-aware shipped set (drafts/ may keep stale
    markers — it never ships), and any 'Last checked' phrasing that ISN'T
    the exact marker line fails outright, so a paraphrase can never
    masquerade as a freshness receipt. Exactly one marker per page, all
    of them on the current version — the whole claim in two asserts."""
    version = re.search(r'^version = "([^"]+)"',
                        Path("pyproject.toml").read_text(), re.MULTILINE).group(1)
    exact = f"_(Last checked against v{version}.)_"

    raw = Path("mkdocs.yml").read_text()
    block = raw.split("exclude_docs: |")[1]
    patterns = []
    for line in block.splitlines()[1:]:
        if line and not line.startswith((" ", "\t")):
            break
        if line.strip():
            patterns.append(line.strip())

    shipped = [p for p in Path("docs").rglob("*.md")
               if not any(str(p.relative_to("docs")).startswith(pat)
                          for pat in patterns)]
    problems, found = [], set()
    for p in sorted(shipped):
        lines = p.read_text().splitlines()
        hits = [ln for ln in lines if ln.strip() == exact]
        if len(hits) != 1:
            problems.append(f"{p}: {len(hits)} exact markers (want 1)")
        # any freshness claim that isn't the exact line is stale by
        # construction — a paraphrase is a claim we can't verify
        stray = [ln for ln in lines if "Last checked" in ln and ln.strip() != exact]
        if stray:
            problems.append(f"{p}: non-marker claim {stray[0].strip()!r}")
        found |= {ln.strip() for ln in lines if "Last checked" in ln}
    assert not problems, "\n".join(problems)
    # the corpus's freshness set is exactly the current version
    assert found == {exact}, f"marker drift: {found}"
    assert len(shipped) >= 20, f"file set collapsed: {len(shipped)}"


def test_t1006_adapters_readme_final_pass_matches_sources():  # T1006
    """T1006: the adapters README's final pass — every P45/P50 change
    reflected. The receipts are set-equalities against the sources, not
    prose reviews: the SDK column's shared-surface list must equal
    common.py's actual public names exactly (the P50 refactor grew it
    by eight — api, parse_command, command_reply, moderate_action and
    friends — and the old list silently missed them); matrix's setup
    cell must name `!bouncer appeal` the way its own help text does
    (T864 wired the flow, the cell forgot); the discord note must cite
    the shared command_reply table (T952) with appeal in its set
    instead of the stale local-T705 story; and the new Shared plumbing
    section must name the four P50 helpers that exist in common.py.
    Citation integrity over every T-number the file carries closes it."""
    text = (Path("src/gatekeeper/adapters/README.md")).read_text()
    assert "T1006" in text

    # the SDK column == common.py's public surface, exactly
    row = next(ln for ln in text.splitlines()
               if ln.startswith("| *shared*"))
    listed = {n.strip() for n in row.rsplit("|", 2)[1].split(",")}
    src = Path("src/gatekeeper/adapters/common.py").read_text()
    actual = set(re.findall(r"^(?:async )?def ([a-z_]+)", src, re.MULTILINE))
    actual |= set(re.findall(r"^class ([A-Za-z]+)", src, re.MULTILINE))
    assert listed == actual, \
        f"README misses {sorted(actual - listed)}, invents {sorted(listed - actual)}"

    # matrix cell names appeal; grounding is the delegation, not a
    # literal — matrix advertises no help text at all, its command
    # surface IS the shared table: parse_command drops the "!bouncer"
    # trigger and command_reply's appeal branch answers
    mrow = next(ln for ln in text.splitlines() if ln.startswith("| Matrix "))
    assert "!bouncer appeal" in mrow
    mb = Path("src/gatekeeper/adapters/matrix_bot.py").read_text()
    assert 'parse_command(body, "!bouncer")' in mb, "matrix must delegate"
    assert "command_reply(" in mb, "matrix must use the shared table"
    assert 'if cmd == "appeal"' in src, "the table must answer it"

    # the discord note: shared table, appeal included, T952 cited
    note = text.split("* Discord:")[1].split("\n* ")[0]
    assert "T952" in note and "appeal" in note and "T864" in note
    assert "T952" in Path("src/gatekeeper/adapters/common.py").read_text()

    # the Shared plumbing section names the helpers that exist
    sec = text.split("## Shared plumbing")[1].split("\n## ")[0]
    for cite, name in (("T951", "api()"), ("T952", "command_reply()"),
                       ("T953", "moderate_action()"), ("T958", "test_t958")):
        assert cite in sec and name in sec, f"{cite}/{name} missing"
    for fn in ("api", "parse_command", "command_reply", "moderate_action"):
        assert re.search(rf"^def {fn}\(", src, re.MULTILINE), fn

    # every T-number this README cites is a real box
    todo = Path("TODO.md").read_text()
    for t in set(re.findall(r"\bT\d{3,4}\b", text)):
        assert t in todo, f"adapters README cites unknown box {t}"


def test_t1007_readme_perf_claims_rechecked_against_reports():  # T1007
    """T1007: the README's performance claims re-checked against the
    in-tree bench reports. The import row is pinned NUMBER-FOR-NUMBER
    to eval/reports/import.json — the one claim a refreshed bench
    actually moved (T966's re-run: 31.9ms, replacing T762's 30.4ms) —
    so the next re-run that changes it fails here until the README is
    updated with it. The re-check paragraph must name the two honest
    findings: the pool row keeps T592's dated 5.4× while the in-tree
    lighter-params rerun says 5.0× (both numbers on the page, neither
    hidden), and stats-load.json is CI's scaled run, not a re-
    measurement of T760's 8×100. Every table row keeps a date or a
    box cite in its measured cell, the cost table's latency cell
    names its hardware (T4 — an unattributed ~33ms invites the
    reader to assume their laptop), and the batch claim stays inside
    the in-tree sweep's numbers."""
    text = Path("README.md").read_text()
    assert "T1007" in text

    # the import row tracks the report, exactly
    report = json.loads(Path("eval/reports/import.json").read_text())
    row = next(ln for ln in text.splitlines()
               if "import gatekeeper" in ln and ln.startswith("|"))
    assert f"**{report['p50_ms']}ms**" in row, \
        f"README import claim drifted from import.json ({report['p50_ms']}ms)"
    assert "T966" in row and "T762" in row, "the refresh cites both eras"

    # the re-check paragraph: both pool numbers, the stats scenario split
    check = text.split("Re-checked against")[1].split("\n\n")[0]
    assert "T1007" in check or "Re-checked against" in text
    assert "5.4" in check and "5.0" in check, "both pool numbers must stand"
    assert "2-threads" in check and "T760" in check, \
        "the CI-scaled stats rerun must be named as such"

    # every measured cell carries an attribution
    perf = text.split("## Performance")[1]
    for ln in perf.splitlines():
        if ln.startswith(("| `", "| batch", "| warm")):
            cell = ln.rsplit("|", 2)[1]
            assert re.search(r"\d{4}-\d{2}-\d{2}|T\d{3,4}", cell), ln

    # the cost table names its hardware
    cost = next(ln for ln in text.splitlines()
                if "self-hosted Laya" in ln)
    assert "T4" in cost, "latency cell must name the hardware it measured on"

    # the batch claim stays inside the in-tree sweep
    sweep = json.loads(Path("eval/reports/batch-sweep.json").read_text())
    assert any(v <= 0.5 for v in sweep["rows"].values()), \
        "no row near the README's ~0.2ms claim — re-measure, don't round"


def test_t1008_known_numbers_covers_every_enforced_budget(tmp_path):  # T1008
    """T1008: the Known-numbers table refreshed so it covers EVERY
    enforced gate default, not just the five T684-era ones. The check
    is live, not textual: a passing synthetic report goes through
    gate.py --check-docs --json and the docs_* checks it emits must
    equal the table's 'enforced default' rows as a set — a budget gate.py
    enforces but the table forgot (like the P49 metrics scrape budget,
    T948) fails here, and a table row with no matching default fails
    the other way. Each enforced row must also name its --flag, and
    the T948 row is pinned by value (100ms) and cite so the P49 number
    can't quietly vanish from the docs."""
    rep = tmp_path / "generic.json"
    rep.write_text(json.dumps({"n": 300, "rule_acc": 0.403}))
    r = subprocess.run([sys.executable, "eval/gate.py", str(rep),
                        "--check-docs", "--json"], check=False,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    checks = json.loads(r.stdout)["checks"]
    docs = {c["name"][len("docs_"):]: c["ok"] for c in checks
            if c["name"].startswith("docs_")}
    assert len(docs) >= 14, f"drift checker shrank to {len(docs)} budgets"
    assert all(docs.values()), [n for n, ok in docs.items() if not ok]

    section = Path("BENCHMARKS.md").read_text().split("## Known numbers")[1]
    enforced = set(re.findall(
        r"^\| ([a-z0-9_]+) \| [0-9.]+ \| enforced default", section,
        re.MULTILINE))
    assert enforced == set(docs), \
        f"table {sorted(enforced)} vs drift-checked {sorted(docs)}"
    for name in enforced:
        row = next(ln for ln in section.splitlines()
                   if ln.startswith(f"| {name} |"))
        assert "--" in row, f"{name} row names no flag"

    # the P49 numbers landed, pinned by value and cite
    assert "| max_metrics_p50_ms | 100 |" in section
    assert "T948" in section and "T1008" in section


def test_t1009_p52_fix_box_found_no_reds():  # T1009
    """T1009: the P52 fix box found no reds — every gate run across the
    batch came back green (T991-T1008 landed on verify_rc=0 runs, each
    with an empty lastfailed), so there was nothing for the fix box to
    fix. This test is that claim, made falsifiable: every box the fix
    box's sweep covered (T991-T1008) is ticked AND carries its receipt
    literally outside TODO.md (the sweep corpus, same roots the P42/P50
    sweeps scan), and this batch's own test file carries no skip or
    xfail marker — a red never hides behind a disabled test. If a later
    box gets unticked, loses its receipt, or someone xfails a P52 test
    to get green, this fails and the fix box's promise is void."""
    todo = Path("TODO.md").read_text()
    boxes = [f"T{n}" for n in range(991, 1009)]
    for b in boxes:
        assert f"- [x] {b}" in todo, f"{b} unticked when the fix box ran"

    corpus = ""
    for root in ("docs", "tests", "src", ".github", "eval"):
        for p in Path(root).rglob("*"):
            if p.is_file() and p.suffix in (".md", ".py", ".yml", ".yaml",
                                            ".sh"):
                corpus += p.read_text()
    for name in ("README.md", "BENCHMARKS.md", "CHANGELOG.md",
                 "CONTRIBUTING.md", "mkdocs.yml", "verify.sh"):
        corpus += Path(name).read_text()
    for b in boxes:
        assert b in corpus, f"{b} has no receipt outside TODO.md"

    own = Path("tests/test_p52.py").read_text()
    # needles assembled so this test's own source can't trip them
    skip_n, xfail_n = "@pytest" + ".mark.skip", "mark" + ".xfail"
    assert skip_n not in own and xfail_n not in own, \
        "a P52 test went dark — the fix box's no-reds claim is void"
    assert "T1009" in own


def test_t1010_p52_sweep_every_box_ticked_with_receipts():  # T1010
    """T1010: the P52 sweep — all twenty boxes (T991–T1010) ticked, and
    every ticked box's T-number appears literally in some non-TODO
    file: its receipt. The receipt corpus excludes TODO.md itself (the
    T990 correction — a root glob that swallows TODO.md lets every
    number match trivially and the receipt half can never fire). This
    is the batch's closing gate: a red here means a box was ticked
    without doing (or citing) its work. Citation integrity closes it —
    every T-number the batch's own surfaces carry must be a box
    TODO.md actually knows, so an invented receipt fails both ways."""
    todo = Path("TODO.md").read_text()
    assert "## P52 Docs & versioned site (T991–T1010)" in todo
    section = re.search(r"^## P52 .*?(?=^## |\Z)", todo,
                        re.MULTILINE | re.DOTALL)
    assert section, "P52 section missing from TODO.md"
    pairs = re.findall(r"^- \[( |x)\] (T(?:99\d|10\d\d))",
                       section.group(0), re.MULTILINE)
    status = {name: tick for tick, name in pairs}
    assert set(status) == {f"T{n}" for n in range(991, 1011)}, sorted(status)
    unticked = sorted(n for n, t in status.items() if t != "x")
    assert not unticked, f"boxes still open at the sweep: {unticked}"

    # the receipts, TODO.md excluded from the corpus
    corpus = ""
    for root in ("src", "tests", "eval", "data", "kaggle", "scripts",
                 "app", "notebooks", "docs", ".github"):
        base = Path(root)
        if base.exists():
            for p in base.rglob("*"):
                if p.is_file() and p.suffix in (".md", ".py", ".yml",
                                                ".yaml", ".sh"):
                    corpus += p.read_text()
    for name in ("README.md", "BENCHMARKS.md", "CHANGELOG.md",
                 "CONTRIBUTING.md", "mkdocs.yml", "verify.sh"):
        corpus += Path(name).read_text()
    for b in status:
        assert b in corpus, f"{b} ticked without a receipt outside TODO.md"

    # citation integrity over every surface this batch touched
    touched = [Path("tests/test_p52.py"),
               Path("scripts/build_docs_version.py"),
               Path(".github/workflows/docs.yml"), Path("mkdocs.yml"),
               Path("README.md"), Path("BENCHMARKS.md"),
               Path("src/gatekeeper/adapters/README.md")] + [
        Path("docs") / n for n in (
            "versions.md", "api.md", "error-codes.md", "environment.md",
            "cookbook.md", "getting-started.md", "glossary.md",
            "ROADMAP.md", "RELEASE-CHECKLIST.md")] + list(
        Path("docs/examples").glob("*.py"))
    for f in touched:
        for t in set(re.findall(r"\bT\d{3,4}\b", f.read_text())):
            assert t in todo, (str(f), f"cites unknown box {t}")
