"""P50 tests (T951-T970): refactor & repo hygiene."""
import sys
from pathlib import Path

sys.path.insert(0, "src")

from gatekeeper.adapters import common, matrix_bot, mattermost, telegram_bot
from gatekeeper.adapters import zulip_bot as zulip

ADAPTERS = Path("src/gatekeeper/adapters")


def test_t951_common_api_is_the_single_request_builder(monkeypatch):  # T951
    """T951: the four api() copies now delegate to `common.api` — one
    request builder. Captured at the http_json seam, each wrapper must
    produce byte-identical URL/method/body/headers/timeout."""
    seen = []

    def fake_http_json(req, *, timeout, **kw):
        seen.append((req, timeout))
        return {"stub": True}

    monkeypatch.setattr(common, "http_json", fake_http_json)

    telegram_bot.api("tok", "sendMessage", chat_id=1)
    matrix_bot.api("tok", "https://hs", "GET", "/sync")
    mattermost.api("tok", "https://mm", "POST", "/posts")
    zulip.api("bot@x", "key", "https://z", "POST", "/messages", type="direct")
    assert len(seen) == 4, "every wrapper must reach the shared builder"

    (t_req, t_to), (m_req, m_to), (mm_req, mm_to), (z_req, z_to) = seen

    # telegram: token URL, JSON body always, verb from urllib (data => POST)
    assert t_req.full_url == "https://api.telegram.org/bottok/sendMessage"
    assert t_req.data == b'{"chat_id": 1}'
    assert t_req.get_header("Content-type") == "application/json"
    assert t_req.get_method() == "POST"
    assert t_to == 60

    # matrix: Bearer + Content-Type survive even on a bodyless GET
    assert m_req.full_url == "https://hs/_matrix/client/v0/sync"
    assert m_req.data is None
    assert m_req.get_method() == "GET"
    assert m_req.get_header("Authorization") == "Bearer tok"
    assert m_req.get_header("Content-type") == "application/json"
    assert m_to == 70

    # mattermost: explicit verb, no body when no params were given
    assert mm_req.full_url == "https://mm/api/v4/posts"
    assert mm_req.data is None
    assert mm_req.get_method() == "POST"
    assert mm_req.get_header("Authorization") == "Bearer tok"
    assert mm_to == 30

    # zulip: urlencoded form body, Basic auth, no Content-Type (its way)
    assert z_req.full_url == "https://z/api/v1/messages"
    assert z_req.data == b"type=direct"
    assert z_req.get_method() == "POST"
    assert str(z_req.get_header("Authorization")).startswith("Basic ")
    assert z_req.get_header("Content-type") is None
    assert z_to == 60

    # the copies are gone: no adapter builds a Request by hand any more
    for name in ("telegram_bot.py", "matrix_bot.py", "mattermost.py",
                 "zulip_bot.py"):
        assert "urllib.request.Request" not in (ADAPTERS / name).read_text(), \
            f"{name} still reimplements the shared api() builder"


def test_t952_shared_command_table_and_parser(monkeypatch):  # T952
    """T952: one table + one first-word parser behind all five adapters —
    the five local `if cmd == "rules"` ladders and four hand-rolled
    lstrip/split/lower dances reduced to common.command_reply and
    common.parse_command."""
    from gatekeeper.adapters import discord_bot

    rules = {"sin-spam": "t", "no-doxx": "t"}

    # the table: sorted (deterministic), injectable stats, help contract
    assert common.command_reply("rules", rules) == "active: no-doxx, sin-spam"
    assert common.command_reply(
        "stats", rules, stats={"allow": 2, "flag": 1}) == \
        "decisions: allow=2, flag=1"
    assert common.command_reply("help", rules, help_text="mine") == "mine"
    assert common.command_reply("help", rules) is None  # no help_text ->
    assert common.command_reply("bogus", rules) is None  # the surface's
    # own unknown/usage fallback answers instead
    from gatekeeper import review  # appeal passes the caller's user
    monkeypatch.setattr(review, "appeal_reply",
                        lambda u, r: f"appeal:{u}:{min(r)}")
    assert common.command_reply("appeal", rules, "discord:1") == \
        "appeal:discord:1:no-doxx"

    # no adapter keeps a private copy of the ladder
    for name in ("discord_bot.py", "telegram_bot.py", "matrix_bot.py",
                 "mattermost.py", "zulip_bot.py"):
        src = (ADAPTERS / name).read_text()
        assert 'cmd == "rules"' not in src, f"{name} still has its own table"
        assert "command_reply" in src, f"{name} does not use the shared table"
    assert discord_bot.command_reply("help", rules)  # wrapper keeps its
    assert "bouncer" in discord_bot.command_reply("help", rules)  # own text

    # the parser: telegram shape (no drops) — slash runs stripped, lowered
    assert common.parse_command("/rules") == "rules"
    assert common.parse_command("  //HELP ") == "help"
    assert common.parse_command("/") == ""  # was IndexError in that copy
    # trigger-word drops (matrix / mattermost / zulip shapes)
    assert common.parse_command("!bouncer stats", "!bouncer") == "stats"
    assert common.parse_command("!bouncer", "!bouncer") == ""  # bare trigger
    assert common.parse_command("/bouncer rules", "bouncer") == "rules"
    assert common.parse_command("bouncer stats", "bouncer") == "stats"
    assert common.parse_command("bouncery rules", "bouncer") == "bouncery"
    assert common.parse_command("rules now", "bouncer") == "rules"
    assert common.parse_command("", "bouncer") == ""


def test_t953_moderate_action_skeleton_shared_by_four_pollers(monkeypatch,
                                                              capsys):  # T953
    """T953: telegram/matrix/mattermost/zulip run moderate+effect+announce
    through common.moderate_action; only the effect callback is local.
    Their rate-cap guards stay put (T701 scans for them per adapter)."""
    import gatekeeper

    seen = {}

    def fake(text, rules, **kw):
        seen.update(kw)
        return {"action": "delete", "rule": "no-spam", "confidence": 0.97}

    monkeypatch.setattr(gatekeeper, "moderate", fake)
    monkeypatch.delenv("BOUNCER_DRY_RUN", raising=False)
    effects, out = [], []

    def eff(dry, res):
        effects.append((dry, res.get("rule")))

    res = common.moderate_action(
        "buy followers", {"no-spam": "t"}, adapter="telegram", uid=7,
        enabled=True, effect=eff, out=out.append, sender=False)
    assert res["deleted"] is True and "dry_run" not in res
    assert effects == [(False, "no-spam")]
    assert seen["user_id"] == "telegram:7" and seen["adapter"] == "telegram"
    assert "lang" in seen  # T897: env pin, else detect — the plumbing moved
    assert out == ["[delete] buy followers (no-spam@0.97)"]  # no <sender>

    monkeypatch.setenv("BOUNCER_DRY_RUN", "1")  # T697: intent, never the act
    res = common.moderate_action(
        "buy followers", {"no-spam": "t"}, adapter="mattermost", uid=9,
        enabled=True, effect=eff, out=out.append)
    assert res["deleted"] is False and res["dry_run"] is True
    assert effects[-1] == (True, "no-spam")
    assert out[-1].startswith("[delete] <9> ")  # sender prefix, redacted

    monkeypatch.delenv("BOUNCER_DRY_RUN")
    before = len(effects)
    res = common.moderate_action(
        "buy followers", {"no-spam": "t"}, adapter="zulip", uid=3,
        enabled=False, effect=eff, out=out.append)  # no creds -> no effect
    assert res["deleted"] is False and len(effects) == before
    assert out[-1].startswith("[delete] ")  # the announce still prints

    res = common.moderate_action(
        "buy followers", {"no-spam": "t"}, adapter="matrix",
        uid="alice:hs", enabled=True, effect=eff, out=out.append,
        flag="redacted")  # matrix keys its flag differently
    assert res["redacted"] is True
    assert out[-1].startswith("[delete] <alice:hs> buy followers")

    # the four copies are gone; the T701 cap guards they kept are not
    for name in ("telegram_bot.py", "matrix_bot.py", "mattermost.py",
                 "zulip_bot.py"):
        src = (ADAPTERS / name).read_text()
        assert "moderate_action(" in src, f"{name} bypasses the skeleton"
        assert "dict(moderate(" not in src, f"{name} keeps its own copy"
        assert 'reason": "rate-limited"' in src, f"{name} lost its cap guard"


def test_explain_has_no_dead_announce_line():  # T954
    """announce_line (T184) was dead since introduction — no caller in src,
    tests or docs ever appeared. The box is a fork: wire it or remove it;
    we removed it (T896's tombstone precedent), and this test keeps the
    third option (leave dead code around) off the table."""
    from gatekeeper import explain

    assert not hasattr(explain, "announce_line"), "dead twin is gone, not dormant"
    src = Path("src/gatekeeper/explain.py").read_text()
    assert "T954" in src and "T184" in src  # the tombstone cites both boxes
    # nothing anywhere can call it back unnoticed (the tombstone itself
    # writes the name with a space before any parenthesis)
    corpus = (list(Path("src").rglob("*.py"))
              + list(Path("tests").rglob("*.py"))
              + list(Path("docs").rglob("*.md"))
              + [Path("README.md")])
    me = Path(__file__).resolve()
    for p in corpus:
        if p.resolve() == me:  # this test's own name matches the pattern
            continue
        assert "announce_line(" not in p.read_text(), p


def test_t955_flood_signals_are_eval_baseline_only():  # T955
    """T955: caps_flood/emoji_flood demoted honestly — the engine never
    calls them (wiring them as cheap paths would silently downgrade
    model-delete spam to a review-queue flag), the eval baseline does,
    and docs/architecture.md no longer claims a flood step it never had."""
    engine = Path("src/gatekeeper/__init__.py").read_text()
    assert "caps_flood" not in engine and "emoji_flood" not in engine
    baseline = Path("eval/baseline_regex.py").read_text()
    assert "caps_flood" in baseline and "emoji_flood" in baseline
    demo = Path("src/gatekeeper/demo_app.py").read_text()
    assert "caps_flood" in demo  # T175's regex-baseline meter still compares
    norm = Path("src/gatekeeper/normalize.py").read_text()
    assert "T955" in norm  # the demotion is documented, not silent
    arch = Path("docs/architecture.md").read_text()
    assert "clean, flood, links" not in arch  # the diagram's overclaim
    assert "normalize: clean, links" in arch
    assert "T955" in arch  # and the honest note cites the box
    # the signals themselves still work — baseline fidelity preserved
    from gatekeeper.normalize import caps_flood, emoji_flood
    assert caps_flood("STOP DOING THAT RIGHT NOW OK")
    assert emoji_flood("🔥" * 12)


def test_t956_serve_one_httpexception_import_and_dead_branches_gone():
    """T956: one HTTPException import — predict's literal duplicate and the
    other lazy copies are gone — and the dead branches cleaned: the
    catch-all's isinstance (Starlette's MRO lookup hands HTTPExceptions to
    FastAPI's default handler first, same body), _rate's None guard (no
    caller can pass None), systemone's isinstance(dict) tautologies."""
    src = Path("src/gatekeeper/serve.py").read_text()
    assert "from fastapi import FastAPI, HTTPException, Request" in src
    assert "from fastapi import HTTPException" not in src, "lazy copies back"
    assert "isinstance(exc, HTTPException)" not in src
    assert "if request is None" not in src
    assert "isinstance(part, dict)" not in src
    assert src.count("T956") >= 4  # each cleanup left its mark

    # the consolidated import still serves HTTP errors from the top level
    from fastapi.testclient import TestClient

    from gatekeeper import serve
    r = TestClient(serve.app).get("/presets/definitely-not-a-preset")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E_PRESET"


def test_t957_no_dead_public_code_in_src():  # T957 receipt: this sweep
    """T957: every public function/class in src/ is referenced in code,
    docs or tests — outside its own definition lines.

    Heuristic, stated honestly: word-boundary mentions across src+eval+
    tests+docs minus one per definition line; a decorated definition
    counts as wired (FastAPI routes are attached by @app.get and the
    text never says the function's name); TODO.md is excluded — a box
    mentioning a name is not a receipt (the same rule the batch sweeps
    apply). Name collisions can hide a dead alias behind a live one of
    the same word; whole-name death is what fails here."""
    import ast
    import re

    corpus = []
    for pat in ("src/**/*.py", "tests/**/*.py", "eval/**/*.py",
                "docs/**/*.md"):
        corpus += [p.read_text() for p in Path().glob(pat)]
    corpus += [p.read_text() for p in Path().glob("*.md")
               if p.name != "TODO.md"]  # boxes are not receipts
    corpus += [p.read_text() for p in Path("eval").glob("*.md")]

    defs = []  # (name, lineno, end_lineno, decorated)
    for p in Path("src").rglob("*.py"):
        tree = ast.parse(p.read_text())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and not node.name.startswith("_"):
                defs.append((node.name, node.lineno, node.end_lineno,
                             bool(node.decorator_list)))
                if isinstance(node, ast.ClassDef):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef,
                                            ast.AsyncFunctionDef)) \
                                and not sub.name.startswith("_"):
                            defs.append((f"{node.name}.{sub.name}",
                                         sub.lineno, sub.end_lineno, False))

    assert len(defs) > 100, f"the walk missed src/: only {len(defs)} defs"
    dead = []
    for full, _lo, _hi, decorated in defs:
        name = full.split(".")[-1]
        hits = sum(len(re.findall(rf"\b{re.escape(name)}\b", t))
                   for t in corpus)
        n_defs = sum(1 for n, *_ in defs if n.split(".")[-1] == name)
        if not decorated and hits - n_defs < 1:
            dead.append(full)
    assert not dead, f"public code with no reference outside its defs: {dead}"


def test_t958_adapter_parity_matrix_shared_helpers():  # T958
    """T958: the parity matrix — rows are the seven adapters, columns the
    helpers common owns. Cells are 'calls it', 'via moderate_action' (the
    T953 skeleton carries it), or a thin delegating wrapper that imports
    the common name. The global rule: an adapter defining a helper common
    owns without importing that name from common is a local
    reimplementation and fails — except the one documented contract split."""
    import ast

    adapters = {n: (Path("src/gatekeeper/adapters") / f"{n}.py").read_text()
                for n in ("telegram_bot", "matrix_bot", "mattermost", "zulip_bot",
                          "discord_bot", "twitch_irc", "webhooks")}
    pollers = ("telegram_bot", "matrix_bot", "mattermost", "zulip_bot",
               "discord_bot", "twitch_irc")

    # column 1-7: the startup/shared plumbing every poller must ride
    for name in pollers:
        for helper in ("require_env(", "load_rules(", "load_config()",
                       "cfg_get(", "install_shutdown(", "as_user_id(",
                       "Health("):
            assert helper in adapters[name], (name, helper)
    # column 8: rate caps on five; twitch is the documented T701 gap
    # (README's capability table says so and test_p45 holds that line)
    for name in pollers[:5]:
        assert "rate_cap_from_env(" in adapters[name], name
    assert "rate_cap_from_env(" not in adapters["twitch_irc"]
    # column 9: the webhook library row — signature + identity + dry-run,
    # but no env/shutdown/health: it runs inside someone else's process
    for helper in ("verify_signature(", "as_user_id(", "dry_run(",
                   "redact(", "adapter_lang("):
        assert helper in adapters["webhooks"], helper
    for helper in ("require_env(", "install_shutdown(", "Health("):
        assert helper not in adapters["webhooks"], helper
    # column 10: the quartet's decision path is the shared one (T952+T953),
    # and their lang/redact plumbing arrives through moderate_action
    for name in ("telegram_bot", "matrix_bot", "mattermost", "zulip_bot"):
        for helper in ("command_reply(", "parse_command(", "moderate_action("):
            assert helper in adapters[name], (name, helper)
        assert "adapter_lang(" not in adapters[name], name  # via the skeleton
    # column 11: the three direct-call surfaces spell adapter_lang out
    for name in ("discord_bot", "twitch_irc", "webhooks"):
        assert "adapter_lang(" in adapters[name], name

    # no local reimplementation: every adapter def colliding with a
    # common-owned helper must import that name from common
    common_src = Path("src/gatekeeper/adapters/common.py").read_text()
    tree = ast.parse(common_src)
    owned = {n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and not n.name.startswith("_")}
    # documented contract split: discord's strict T705 parser answers
    # None-for-non-commands (common.parse_command's docstring says so);
    # it is not a copy of the shared first-word dance
    allowed_own = {("discord_bot", "parse_command")}
    for name, src in adapters.items():
        atree = ast.parse(src)
        imported = {a.name for n in ast.walk(atree)
                    if isinstance(n, ast.ImportFrom)
                    and (n.module or "").endswith("common")
                    for a in n.names}
        for node in atree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) \
                    and node.name in owned \
                    and (name, node.name) not in allowed_own:
                assert node.name in imported, \
                    (name, node.name, "reimplements common without importing it")


def test_t959_stricter_ruff_config_enabled_and_fixed_not_suppressed():  # T959
    """T959: the lint skew fix is CONFIG, not suppressions. The pycodestyle
    E/W families are turned on repo-wide in pyproject, the one documented
    exception (kaggle kernels' pip-install-before-import = E402) is scoped
    to those files, the pre-commit pin tracks CI's floating ruff, and none
    of the 148 pre-existing violations were silenced with noqa."""
    import re

    import tomllib

    py = tomllib.loads(Path("pyproject.toml").read_text())
    lint = py["tool"]["ruff"]["lint"]
    assert lint["extend-select"] == ["E", "W"], lint["extend-select"]
    pfi = lint["per-file-ignores"]
    assert pfi == {"kaggle/**": ["E402"]}, pfi  # the single, documented exception

    pre = Path(".pre-commit-config.yaml").read_text()
    assert "rev: v0.17.1" in pre  # same generation as CI's `uvx ruff`
    assert pre.index("rev: v0.17.1") < pre.index("id: ruff")  # the ruff hook's rev

    # the violations were FIXED, not noqa'd: no pycodestyle suppression
    # anywhere in the Python sources (BLE001/F401/SIM115 predate T959)
    bad = re.compile(r"#\s*noqa:\s*[A-Z]*\d*\b.*\b[EW]\d{3,4}\b")
    for path in Path(".").rglob("*.py"):
        if ".git" in path.parts or "p13env" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            assert not bad.search(line), f"{path}:{lineno}: {line.strip()}"


def test_t960_in_tree_artifact_classes_gitignored():  # T960
    """T960: every artifact class that can land in the tree is ignored by
    git. T623 already held the runtime-state line (audit/review jsonl,
    stats, reports); this is the box's own sweep over its named classes —
    audit/review jsonl, build/, site/, egg-info — plus the dist/ sibling.
    Config-level receipt: hypothetical paths, no file has to exist. The
    live tree being clean right now is T961's test."""
    import subprocess

    candidates = [
        "bouncer-audit.jsonl",                # audit jsonl
        "bouncer-audit.jsonl.1",              # rotated audit jsonl
        "review-queue.jsonl",                 # review jsonl
        "build/lib/gatekeeper/__init__.py",   # build/ (setuptools staging)
        "build/bdist.macosx-11.0-arm64/x",    # build/ (bdist)
        "site/index.html",                    # site/ (mkdocs output, T801)
        "src/gatekeeper_1.egg-info/PKG-INFO",  # egg-info (src layout)
        "gatekeeper_1.egg-info/PKG-INFO",     # egg-info (flat layout)
        "dist/bouncer-0.4.0-py3-none-any.whl",  # dist/ (build/ sibling)
    ]
    r = subprocess.run(["git", "check-ignore", "--stdin"], input="\n".join(candidates),
                       capture_output=True, text=True, check=True)
    missing = set(candidates) - set(r.stdout.split())
    assert not missing, f"not gitignored: {sorted(missing)}"


def test_t961_repo_root_carries_no_unignored_runtime_artifacts():  # T961
    """T961: the LIVE tree, not the config — the repo root must carry no
    unignored runtime artifacts. Three angles: nothing untracked-and-
    unignored at the root is artifact-shaped, nothing artifact-shaped is
    tracked at the root, and any artifact from the T960 classes that
    physically exists on disk right now is covered by an ignore rule.
    Root-scoped on purpose: fixture files under tests/ are sources, and
    eval/reports is T623/T960's line."""
    import subprocess

    def git(*args: str) -> list[str]:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              check=True).stdout.splitlines()

    def is_artifact(entry: str) -> bool:
        e = entry.rstrip("/")
        if e in ("build", "site", "dist", "htmlcov"):
            return True  # artifact directory sitting at the root
        if "/" in e:
            return False  # the box scopes to the root level
        return (e == ".coverage" or ".egg-info" in e
                or e.endswith((".jsonl", ".json", ".csv", ".log")))

    untracked_bad = [e for e in git("ls-files", "--others", "--exclude-standard")
                     if is_artifact(e)]
    assert not untracked_bad, f"unignored untracked at root: {untracked_bad}"
    tracked_bad = [e for e in git("ls-files") if is_artifact(e)]
    assert not tracked_bad, f"tracked artifact at root: {tracked_bad}"

    # whatever of the artifact classes exists on disk must be ignored
    on_disk = [p for p in ("bouncer-audit.jsonl", "review-queue.jsonl",
                           "bouncer-stats.json", "audit.csv",
                           "build", "site", "dist")
               if Path(p).exists()]
    if on_disk:
        r = subprocess.run(["git", "check-ignore", "--stdin"],
                           input="\n".join(on_disk), capture_output=True,
                           text=True, check=True)
        missing = set(on_disk) - set(r.stdout.split())
        assert not missing, f"present but unignored: {sorted(missing)}"


def test_t963_from_dict_unknown_keys_rejected_at_every_entry_point(
        tmp_path, capsys):  # T963
    """T963: unknown config keys are rejected at EVERY entry point that
    feeds user JSON into GateConfig. The inventory is from_dict's full
    call-site list: the library call itself, `config validate --json`,
    and `_cfg_from_args` (which serves `check --config` and
    `watch --config`). adapters' load_config/TOML is deliberately out of
    scope — it returns raw adapter settings and never reaches from_dict."""
    import json

    import pytest

    from gatekeeper import cli
    from gatekeeper.config import ConfigError, GateConfig

    bad = {"warp_speed": 9}

    # 1. the library entry: raises, coded, and names the key
    with pytest.raises(ConfigError) as ei:
        GateConfig.from_dict(bad)
    assert ei.value.code == "E_CONFIG"
    assert "warp_speed" in str(ei.value)

    # 2. config validate --json: reported as a fail line, exit 1
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(bad))
    assert cli.main(["config", "validate", "--json", str(f)]) == 1
    out = capsys.readouterr().out
    assert "E_CONFIG" in out and "warp_speed" in out, out

    # 3. check --config: coded line via main(), exit 4, never a traceback
    rc = cli.main(["check", "--preset", "study", "--config", str(f), "hi"])
    assert rc == 4
    err = capsys.readouterr().err
    assert "E_CONFIG" in err and "warp_speed" in err, err

    # 4. watch --config: same contract, rejection happens before the pipe
    rc = cli.main(["watch", "--preset", "study", "--config", str(f)])
    assert rc == 4
    err = capsys.readouterr().err
    assert "E_CONFIG" in err and "warp_speed" in err, err
