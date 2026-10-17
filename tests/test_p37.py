"""P37 tests (T691-T710): adapters. Weightless — env guards, static wiring,
stubbed transports; no platform SDK or network in sight."""
import subprocess
import sys
from pathlib import Path

ADAPTERS = Path("src/gatekeeper/adapters")


def _run_py(*args, env_extra=None):
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"}
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, *args], check=False, capture_output=True,
                          text=True, timeout=60, env=env)


def test_require_env_names_the_missing_variable(monkeypatch):  # T691
    sys.path.insert(0, "src")
    from gatekeeper.adapters.common import AdapterError, require_env
    monkeypatch.delenv("BOUNCER_TEST_TOKEN_XYZ", raising=False)
    try:
        require_env("BOUNCER_TEST_TOKEN_XYZ")
    except AdapterError as e:
        assert e.code == "E_ADAPTER"  # operator-fixable, not a crash
        assert "BOUNCER_TEST_TOKEN_XYZ" in str(e)  # the variable is named
        assert "KeyError" not in str(e)
    else:
        raise AssertionError("require_env must raise on a missing var")
    # set and non-empty -> returned as-is
    monkeypatch.setenv("BOUNCER_TEST_TOKEN_XYZ", "sekrit")
    assert require_env("BOUNCER_TEST_TOKEN_XYZ") == "sekrit"
    # exported-but-blank is also a misconfiguration, not a value
    monkeypatch.setenv("BOUNCER_TEST_TOKEN_XYZ", "")
    try:
        require_env("BOUNCER_TEST_TOKEN_XYZ")
    except AdapterError as e:
        assert e.code == "E_ADAPTER"
    else:
        raise AssertionError("blank env var must count as missing")


def test_adapters_use_require_env_not_raw_indexing():  # T691: wired for real
    discord = (ADAPTERS / "discord_bot.py").read_text()
    twitch = (ADAPTERS / "twitch_irc.py").read_text()
    assert 'require_env("DISCORD_TOKEN")' in discord
    assert "environ[" not in discord  # no raw KeyError path left
    for var in ("TWITCH_NICK", "TWITCH_CHAN", "TWITCH_TOKEN"):
        assert f'require_env("{var}")' in twitch, var
    assert 'environ["TWITCH_' not in twitch  # tokens read via the guard


def test_twitch_missing_env_fails_with_e_adapter_not_keyerror():  # T691 e2e
    r = _run_py("-m", "gatekeeper.adapters.twitch_irc")
    assert r.returncode != 0  # no env -> must fail, loudly
    assert "E_ADAPTER" in r.stderr and "TWITCH_NICK" in r.stderr
    assert "KeyError" not in r.stderr  # the whole point: no raw traceback
    # only the first missing var is named (fail-fast order)
    assert "TWITCH_TOKEN" not in r.stderr


def test_discord_module_still_importable_without_dep():  # T691: guard is lazy
    # the require_env import lives inside run(), so importing the module
    # (docs tooling, tests) never needs discord or env vars
    r = _run_py("-c", "import gatekeeper.adapters.discord_bot as m; "
                      "print(m.run.__name__)")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "run"


def test_adapters_readme_mentions_shared_guard():  # T691: docs stay honest
    text = (ADAPTERS / "README.md").read_text()
    assert "require_env" in text and "E_ADAPTER" in text


def _tg_message(text, chat_id=1, message_id=7):
    return {"message": {"text": text, "chat": {"id": chat_id},
                        "message_id": message_id}}


def test_telegram_commands_answer_in_place():  # T692: / commands, no model
    sys.path.insert(0, "src")
    from gatekeeper import get_preset
    from gatekeeper.adapters.telegram_bot import handle_update
    rules = get_preset("gaming")
    for cmd, expect in (("/rules", "active:"), ("/stats", "decisions:"),
                        ("/help", "BOUNCER_TG_DELETE")):
        res = handle_update(_tg_message(cmd), rules)
        assert res["action"] == "command" and res["command"] == cmd.lstrip("/")
        assert expect in res["reply"]
    # unknown commands are ignored, not moderated as content
    res = handle_update(_tg_message("/definitely-not-a-command"), rules)
    assert res == {"action": "ignored", "reason": "unknown-command"}
    # with a token, replies go through the (injectable) api, not print
    calls = []
    res = handle_update(_tg_message("/rules"), rules, token="t",
                        api_fn=lambda *a, **k: calls.append((a, k)))
    assert calls and calls[0][0][1:] == ("sendMessage",)
    assert calls[0][1]["chat_id"] == 1


def test_telegram_flag_only_by_default(monkeypatch):  # T692: delete is opt-in
    sys.path.insert(0, "src")
    import gatekeeper
    from gatekeeper.adapters import telegram_bot as tg
    monkeypatch.setattr(gatekeeper, "moderate",
                        lambda text, rules: {"action": "delete",
                                             "rule": "sin-spam",
                                             "confidence": 0.99})
    rules = {"sin-spam": "t"}
    calls = []
    # default: the delete decision is printed, never executed
    res = tg.handle_update(_tg_message("buy followers now"), rules)
    assert res["action"] == "delete" and res["deleted"] is False
    assert calls == []  # no api call happened
    # opt-in with a token: exactly one deleteMessage call
    res = tg.handle_update(_tg_message("buy followers now"), rules,
                           token="t", can_delete=True,
                           api_fn=lambda *a, **k: calls.append((a, k)))
    assert res["deleted"] is True
    assert calls[0][0][1:] == ("deleteMessage",)
    assert calls[0][1] == {"chat_id": 1, "message_id": 7}
    # without a token even can_delete=True cannot fire (nothing to auth with)
    res = tg.handle_update(_tg_message("buy followers now"), rules,
                           can_delete=True)
    assert res["deleted"] is False


def test_telegram_ignores_non_text_updates():  # T692: stickers carry no text
    sys.path.insert(0, "src")
    from gatekeeper import get_preset
    from gatekeeper.adapters.telegram_bot import handle_update
    rules = get_preset("gaming")
    res = handle_update({"message": {"sticker": {}}}, rules)
    assert res == {"action": "ignored", "reason": "no-text"}
    res = handle_update({}, rules)
    assert res["action"] == "ignored"


def test_telegram_adapter_is_stdlib_only():  # T692: no pip extra to run it
    src = (ADAPTERS / "telegram_bot.py").read_text()
    for banned in ("import telegram", "import aiogram", "import aiohttp",
                   "import httpx", "import requests"):
        assert banned not in src
    # every top-level import is stdlib
    top = [l.strip() for l in src.splitlines()
           if l.startswith(("import ", "from ")) and "future" not in l]
    allowed = {"json", "os", "sys", "urllib.request"}
    for line in top:
        mod = line.split()[1]
        assert mod in allowed, line


def test_telegram_missing_token_fails_e_adapter():  # T692: T691 guard applies
    r = _run_py("-m", "gatekeeper.adapters.telegram_bot")
    assert r.returncode != 0
    assert "E_ADAPTER" in r.stderr and "TELEGRAM_TOKEN" in r.stderr
    assert "KeyError" not in r.stderr


def _mx_event(text="hello there", etype="m.room.message", msgtype="m.text",
              event_id="$ev1"):
    return {"type": etype, "event_id": event_id, "sender": "@user:example.org",
            "content": {"msgtype": msgtype, "body": text}}


class _StubRouter:
    """T580 convention: laya isn't installed; the engine needs a router stub."""
    def predict(self, state, questions):
        return {"answers": {"rule": {"choice": "ok", "confidence": 0.9,
                                     "probabilities": {"ok": 0.9}},
                            "harm": {"score": "safe"},
                            "hype": {"score": "chill"},
                            "jailbreak": {"noul": 0.0},
                            "escalate": {"noul": 0.0}}}


def test_matrix_timeline_goes_through_moderate(monkeypatch):  # T693: -> moderate
    sys.path.insert(0, "src")
    import gatekeeper
    monkeypatch.setattr(gatekeeper, "_router", _StubRouter())
    from gatekeeper import get_preset
    from gatekeeper.adapters.matrix_bot import handle_event
    rules = get_preset("gaming")
    res = handle_event(_mx_event("just chatting"), rules)
    assert res["action"] in ("allow", "flag", "delete", "escalate")
    assert res["redacted"] is False
    # non-message and non-text events are ignored, not moderated
    assert handle_event(_mx_event(etype="m.room.member"), rules) == \
        {"action": "ignored", "reason": "not-message"}
    assert handle_event(_mx_event(msgtype="m.image"), rules) == \
        {"action": "ignored", "reason": "no-text"}
    assert handle_event(_mx_event(""), rules)["reason"] == "no-text"


def test_matrix_commands_and_redaction_opt_in(monkeypatch):  # T693
    sys.path.insert(0, "src")
    import gatekeeper
    from gatekeeper import get_preset
    from gatekeeper.adapters import matrix_bot as mx
    rules = get_preset("gaming")
    # !bouncer prefix parity with discord
    res = mx.handle_event(_mx_event("!bouncer rules"), rules)
    assert res["action"] == "command" and res["reply"].startswith("active:")
    assert mx.handle_event(_mx_event("!bouncer wat"), rules) == \
        {"action": "ignored", "reason": "unknown-command"}
    # redaction is opt-in and needs token + homeserver to fire
    monkeypatch.setattr(gatekeeper, "moderate",
                        lambda text, r: {"action": "delete", "rule": "sin-spam",
                                         "confidence": 0.99})
    calls = []
    ev = _mx_event("buy followers", event_id="$bad")
    res = mx.handle_event(dict(ev, room_id="!r:example.org"), rules)
    assert res["redacted"] is False and calls == []
    res = mx.handle_event(dict(ev, room_id="!r:example.org"), rules,
                          token="t", homeserver="https://mx", can_redact=True,
                          api_fn=lambda *a, **k: calls.append((a, k)))
    assert res["redacted"] is True
    assert calls[0][0][2:4] == ("PUT", "/rooms/!r:example.org/redact/$bad/bouncer1")
    assert calls[0][0][4] == {"redacts": "$bad", "reason": "bouncer:sin-spam"}
    res = mx.handle_event(dict(ev, room_id="!r:example.org"), rules,
                          token="t", can_redact=True)  # no homeserver -> no fire
    assert res["redacted"] is False


def test_matrix_dispatch_page_routes_and_survives_bad_events(monkeypatch):  # T693
    sys.path.insert(0, "src")
    import gatekeeper
    monkeypatch.setattr(gatekeeper, "_router", _StubRouter())
    from gatekeeper import get_preset
    from gatekeeper.adapters.matrix_bot import dispatch_page
    page = {"next_batch": "s1", "rooms": {"join": {"!r:x": {"timeline":
            {"events": [_mx_event("hello"), {"type": "m.room.member"},
                        {"type": "m.room.message", "content": None}]}}}}}
    results = dispatch_page(page, get_preset("gaming"))
    assert len(results) == 3  # every event accounted for
    assert results[1]["reason"] == "not-message"
    # room_id is stamped from the sync envelope, not required on each event
    assert all(r.get("action") for r in results)


def test_matrix_adapter_is_stdlib_only_and_guarded():  # T693: no extra, T691 guard
    src = (ADAPTERS / "matrix_bot.py").read_text()
    for banned in ("import matrix", "import nio", "import aiohttp",
                   "import httpx", "import requests"):
        assert banned not in src
    r = _run_py("-m", "gatekeeper.adapters.matrix_bot")
    assert r.returncode != 0
    assert "E_ADAPTER" in r.stderr and "MATRIX_TOKEN" in r.stderr
    assert "KeyError" not in r.stderr


def _mm_post(message="hello channel", ptype="", pid="p1"):
    return {"id": pid, "type": ptype, "user_id": "u1", "message": message}


def test_mattermost_posts_moderated_flag_only(monkeypatch):  # T694
    sys.path.insert(0, "src")
    import gatekeeper
    monkeypatch.setattr(gatekeeper, "_router", _StubRouter())
    from gatekeeper import get_preset
    from gatekeeper.adapters.mattermost import handle_post
    rules = get_preset("gaming")
    # system posts and empties never reach the model
    assert handle_post(_mm_post(ptype="system_join_channel"), rules) == \
        {"action": "ignored", "reason": "system-post"}
    assert handle_post(_mm_post("   "), rules)["reason"] == "no-text"
    # normal posts are moderated; delete is opt-in (flag-only default)
    res = handle_post(_mm_post("just chatting"), rules)
    assert res["action"] in ("allow", "flag", "delete", "escalate")
    assert res["deleted"] is False
    monkeypatch.setattr(gatekeeper, "moderate",
                        lambda text, r: {"action": "delete", "rule": "sin-spam",
                                         "confidence": 0.99})
    calls = []
    res = handle_post(_mm_post("buy followers", pid="p9"), rules)
    assert res["deleted"] is False and calls == []
    res = handle_post(_mm_post("buy followers", pid="p9"), rules,
                      token="t", server="https://mm", can_delete=True,
                      api_fn=lambda *a, **k: calls.append((a, k)))
    assert res["deleted"] is True
    assert calls[0][0][2:] == ("DELETE", "/posts/p9")


def test_mattermost_slash_token_and_replies():  # T694: constant-time compare
    sys.path.insert(0, "src")
    from gatekeeper import get_preset
    from gatekeeper.adapters.mattermost import handle_slash
    rules = get_preset("gaming")
    # wrong webhook token is rejected before anything else happens
    assert handle_slash({"token": "evil", "text": "/bouncer rules"}, rules,
                        slash_token="sekrit") == \
        {"action": "ignored", "reason": "bad-token"}
    # correct token answers in the channel via api_fn
    calls = []
    res = handle_slash({"token": "sekrit", "text": "/bouncer rules",
                        "channel_id": "c1"}, rules, slash_token="sekrit",
                       token="t", server="https://mm",
                       api_fn=lambda *a, **k: calls.append((a, k)))
    assert res["action"] == "command" and res["reply"].startswith("active:")
    assert calls[0][0][2:4] == ("POST", "/posts")
    assert calls[0][1]["channel_id"] == "c1"
    # canonical Mattermost shape: text carries only the args after the trigger
    res = handle_slash({"token": "sekrit", "text": "rules"}, rules,
                       slash_token="sekrit")
    assert res["command"] == "rules" and res["reply"].startswith("active:")
    # unknown subcommand gets usage, not a model call
    res = handle_slash({"token": "sekrit", "text": "/bouncer wat"}, rules,
                       slash_token="sekrit")
    assert "usage:" in res["reply"]


def test_mattermost_dep_is_optional_and_fail_fast():  # T694: named extra
    src = (ADAPTERS / "mattermost.py").read_text()
    # websockets is imported lazily inside run(); the module itself is importable
    assert src.index("import websockets") > src.index("def run(")
    r = _run_py("-c", "import gatekeeper.adapters.mattermost")
    assert r.returncode == 0, r.stderr
    # missing extra fails with the exact install line; the raw ImportError is
    # kept as the __cause__ for diagnostics, but the loud error is ours
    r = _run_py("-m", "gatekeeper.adapters.mattermost")
    assert r.returncode != 0
    assert "E_ADAPTER" in r.stderr and "pip install -e .[mattermost]" in r.stderr
    assert r.stderr.strip().splitlines()[-1].startswith(
        "gatekeeper.adapters.common.AdapterError")  # our error, last word


def _zl_message(text="hello stream", mtype="stream", sender=42, mid=11):
    return {"type": "message",
            "message": {"id": mid, "type": mtype, "sender_id": sender,
                        "content": text}}


def test_zulip_stream_moderated_own_skipped(monkeypatch):  # T695
    sys.path.insert(0, "src")
    import gatekeeper
    monkeypatch.setattr(gatekeeper, "_router", _StubRouter())
    from gatekeeper import get_preset
    from gatekeeper.adapters.zulip_bot import handle_event
    rules = get_preset("gaming")
    res = handle_event(_zl_message("just chatting"), rules)
    assert res["action"] in ("allow", "flag", "delete", "escalate")
    assert res["deleted"] is False
    # the bot's own messages are never re-moderated (no feedback loops)
    assert handle_event(_zl_message("active: ok", sender=1), rules,
                        own_id=1) == {"action": "ignored",
                                      "reason": "own-message"}
    assert handle_event({"type": "heartbeat"}, rules) == \
        {"action": "ignored", "reason": "not-message"}
    assert handle_event(_zl_message("   "), rules)["reason"] == "no-text"


def test_zulip_pms_are_commands_only(monkeypatch):  # T695: mention parity
    sys.path.insert(0, "src")
    import gatekeeper
    monkeypatch.setattr(gatekeeper, "_router", _StubRouter())
    from gatekeeper import get_preset
    from gatekeeper.adapters.zulip_bot import handle_event
    rules = get_preset("gaming")
    calls = []
    creds = ("bot@x", "key", "https://zulip")
    # "bouncer rules" as a PM or as a stream mention answers in PM
    for text, mtype in (("bouncer rules", "private"),
                        ("/bouncer rules", "stream")):
        res = handle_event(_zl_message(text, mtype), rules, creds=creds,
                           api_fn=lambda *a, **k: calls.append((a, k)))
        assert res["action"] == "command" and res["reply"].startswith("active:")
    assert calls[0][0][3:5] == ("POST", "/messages")
    assert calls[0][1]["to"] == 42
    # a chat PM is ignored, not moderated
    assert handle_event(_zl_message("hey bot", "private"), rules, creds=creds) == \
        {"action": "ignored", "reason": "private-needs-command"}


def test_zulip_delete_is_opt_in(monkeypatch):  # T695: flag-only default
    sys.path.insert(0, "src")
    import gatekeeper
    from gatekeeper.adapters import zulip_bot as zl
    monkeypatch.setattr(gatekeeper, "moderate",
                        lambda text, r: {"action": "delete", "rule": "sin-spam",
                                         "confidence": 0.99})
    rules = {"sin-spam": "t"}
    calls = []
    creds = ("bot@x", "key", "https://zulip")
    res = zl.handle_event(_zl_message("buy followers", mid=77), rules)
    assert res["deleted"] is False and calls == []
    res = zl.handle_event(_zl_message("buy followers", mid=77), rules,
                          creds=creds, can_delete=True,
                          api_fn=lambda *a, **k: calls.append((a, k)))
    assert res["deleted"] is True
    assert calls[0][0][3:5] == ("DELETE", "/messages/77")


def test_zulip_adapter_is_stdlib_only_and_guarded():  # T695: no extra, T691
    src = (ADAPTERS / "zulip_bot.py").read_text()
    for banned in ("import zulip", "import aiohttp", "import httpx",
                   "import requests"):
        assert banned not in src
    r = _run_py("-m", "gatekeeper.adapters.zulip_bot")
    assert r.returncode != 0
    assert "E_ADAPTER" in r.stderr and "ZULIP_EMAIL" in r.stderr
    assert "KeyError" not in r.stderr


class _StopLoop(BaseException):
    """Escape hatch for run_loop tests — deliberately not an Exception."""


def test_run_loop_is_the_shared_poll_loop(capsys):  # T696
    sys.path.insert(0, "src")
    from gatekeeper.adapters.common import run_loop
    calls = {"fetches": 0, "handled": []}

    def fetch():
        calls["fetches"] += 1
        if calls["fetches"] == 1:
            raise OSError("net down")
        if calls["fetches"] == 2:
            return [{"x": 1}, {"x": 2}, {"x": 3}]
        raise _StopLoop

    def handle(ev):
        if ev["x"] == 2:
            raise ValueError("bad event")
        calls["handled"].append(ev["x"])

    sleeps = []
    try:
        run_loop(fetch, handle, name="testadp", sleep=sleeps.append)
    except _StopLoop:
        pass
    # fetch failure -> one 5s backoff; bad event -> one line; rest still ran
    assert sleeps == [5.0] and calls["handled"] == [1, 3]
    err = capsys.readouterr().err
    assert "testadp error: net down" in err
    assert "testadp event error: bad event" in err


def test_run_loop_lets_ctrl_c_through():  # T696: KeyboardInterrupt is sacred
    sys.path.insert(0, "src")
    import pytest

    from gatekeeper.adapters.common import run_loop

    def fetch():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_loop(fetch, lambda ev: None, name="testadp", sleep=lambda s: None)


def test_sync_pollers_use_the_shared_loop():  # T696: wired, not aspirational
    for name in ("telegram_bot", "matrix_bot", "zulip_bot"):
        src = (ADAPTERS / f"{name}.py").read_text()
        assert "run_loop(fetch, handle" in src, name
        assert "import require_env, run_loop" in src, name
        assert "while True" not in src, name  # the loop lives in common.py
    # mattermost is the documented async exception (websocket, not a poller)
    mm = (ADAPTERS / "mattermost.py").read_text()
    assert "while True" not in mm and "async for" in mm
