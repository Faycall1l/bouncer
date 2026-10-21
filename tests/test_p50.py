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
