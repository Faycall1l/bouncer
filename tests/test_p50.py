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
