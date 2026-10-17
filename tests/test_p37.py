"""P37 tests (T691-T710): adapters. Weightless — env guards, static wiring,
stubbed transports; no platform SDK or network in sight."""
import json
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
        assert "from gatekeeper.adapters.common import" in src, name
        assert "run_loop" in src and "require_env" in src, name
        assert "while True" not in src, name  # the loop lives in common.py
    # mattermost is the documented async exception (websocket, not a poller)
    mm = (ADAPTERS / "mattermost.py").read_text()
    assert "while True" not in mm and "async for" in mm


def test_dry_run_prints_never_posts(monkeypatch, capsys):  # T697
    sys.path.insert(0, "src")
    import gatekeeper
    from gatekeeper.adapters.common import dry_run
    assert dry_run() is False  # default: real actions happen
    monkeypatch.setenv("BOUNCER_DRY_RUN", "1")
    assert dry_run() is True
    monkeypatch.setattr(gatekeeper, "moderate",
                        lambda t, r: {"action": "delete", "rule": "sin-spam",
                                      "confidence": 0.99})
    rules = {"sin-spam": "t"}
    calls = []
    recorder = lambda *a, **k: calls.append((a, k))  # stub transport

    from gatekeeper.adapters import matrix_bot as mx
    from gatekeeper.adapters import mattermost as mm
    from gatekeeper.adapters import telegram_bot as tg
    from gatekeeper.adapters import zulip_bot as zl
    # every delete path prints the intent and never reaches the api
    tg.handle_update(_tg_message("buy now"), rules, token="t", can_delete=True,
                     api_fn=recorder)
    mx.handle_event(dict(_mx_event("buy now"), room_id="!r:x"), rules,
                    token="t", homeserver="https://mx", can_redact=True,
                    api_fn=recorder)
    mm.handle_post(_mm_post("buy now"), rules, token="t",
                   server="https://mm", can_delete=True, api_fn=recorder)
    zl.handle_event(_zl_message("buy now"), rules,
                    creds=("bot@x", "k", "https://z"), can_delete=True,
                    api_fn=recorder)
    assert calls == []  # not one outbound call happened
    out = capsys.readouterr().out
    assert "[dry-run] would deleteMessage" in out
    assert "[dry-run] would redact" in out
    assert "[dry-run] would deletePost" in out
    assert "[dry-run] would delete message" in out
    # command replies are printed too, never sent
    tg.handle_update(_tg_message("/rules"), rules, token="t",
                     api_fn=recorder)
    mm.handle_slash({"token": "s", "text": "rules", "channel_id": "c1"}, rules,
                    token="t", server="https://mm", api_fn=recorder)
    zl.handle_event(_zl_message("bouncer rules", "private"), rules,
                    creds=("bot@x", "k", "https://z"), api_fn=recorder)
    assert calls == []
    out = capsys.readouterr().out
    assert "[dry-run] would send:" in out and "[dry-run] would post:" in out
    assert "[dry-run] would PM" in out
    # nothing was actually deleted: the result says so honestly
    res = tg.handle_update(_tg_message("buy now"), rules, token="t",
                           can_delete=True, api_fn=recorder)
    assert res["deleted"] is False and res["dry_run"] is True


def test_dry_run_covers_forwarder_and_all_adapters(monkeypatch):  # T697
    sys.path.insert(0, "src")
    monkeypatch.setenv("BOUNCER_DRY_RUN", "1")
    from gatekeeper.adapters.webhooks import forward
    # a dry-run forward must not open a socket — the dummy url would raise
    # URLError if anything tried to POST to it
    forward("https://127.0.0.1:9/nowhere", {"action": "flag", "message": "x"})
    # static sweep: every adapter file knows about the switch (or is the
    # print-only twitch, which documents why it doesn't need one)
    for name in ("telegram_bot", "matrix_bot", "mattermost", "zulip_bot",
                 "discord_bot", "webhooks", "common"):
        src = (ADAPTERS / f"{name}.py").read_text()
        assert "dry_run" in src, name
    assert "no-op" in (ADAPTERS / "twitch_irc.py").read_text()


def test_load_rules_preset_file_and_per_adapter(monkeypatch, tmp_path):  # T698
    sys.path.insert(0, "src")
    from gatekeeper import get_preset
    from gatekeeper.adapters.common import AdapterError, load_rules
    for var in ("BOUNCER_RULES", "BOUNCER_RULES_TESTADP",
                "BOUNCER_RULES_OTHER", "BOUNCER_RULES_STREAM"):
        monkeypatch.delenv(var, raising=False)
    # default: the gaming preset
    assert load_rules("testadp") == get_preset("gaming")
    # shared env names another preset
    monkeypatch.setenv("BOUNCER_RULES", "study")
    assert load_rules("testadp") == get_preset("study")
    # a JSON file path loads its rules verbatim
    f = tmp_path / "rules.json"
    f.write_text(json.dumps({"my-rule": {"pattern": "buy followers",
                                         "action": "delete"}}))
    monkeypatch.setenv("BOUNCER_RULES", str(f))
    assert load_rules("testadp") == {
        "my-rule": {"pattern": "buy followers", "action": "delete"}}
    # per-adapter override beats the shared one; others keep the shared source
    monkeypatch.setenv("BOUNCER_RULES_STREAM", "stream")
    assert load_rules("stream") == get_preset("stream")
    assert load_rules("other") == {"my-rule": {"pattern": "buy followers",
                                               "action": "delete"}}
    # unknown preset -> E_ADAPTER naming the options, not a KeyError
    monkeypatch.setenv("BOUNCER_RULES", "nonsense")
    try:
        load_rules("testadp")
    except AdapterError as e:
        assert e.code == "E_ADAPTER" and "nonsense" in str(e)
        assert "gaming" in str(e)  # the valid presets are listed
    else:
        raise AssertionError("unknown preset must fail loudly")
    # a broken rules file -> E_ADAPTER, never a raw json traceback
    monkeypatch.setenv("BOUNCER_RULES", str(f))
    f.write_text("{broken")
    try:
        load_rules("testadp")
    except AdapterError as e:
        assert "unreadable JSON" in str(e)
    else:
        raise AssertionError("broken rules file must fail loudly")
    f.write_text("[1, 2]")  # valid JSON, wrong shape
    try:
        load_rules("testadp")
    except AdapterError as e:
        assert "non-empty JSON object" in str(e)
    else:
        raise AssertionError("non-object rules file must fail loudly")


def test_adapters_source_rules_via_load_rules():  # T698: wired for real
    for name in ("telegram_bot", "matrix_bot", "mattermost", "zulip_bot",
                 "twitch_irc", "discord_bot"):
        src = (ADAPTERS / f"{name}.py").read_text()
        assert "load_rules(" in src, name
        assert 'get_preset("' not in src, name  # no hardcoded presets left


def test_health_line_counts_decisions_and_last_error():  # T699
    sys.path.insert(0, "src")
    from gatekeeper.adapters.common import Health
    t = [0.0]
    lines = []
    h = Health("testadp", clock=lambda: t[0], log=lines.append,
               window_s=60.0, every_s=300.0)
    assert h.line() == "testadp health: 0 decisions/min, last error: none"
    for _ in range(7):
        h.decision()
    assert "7 decisions/min" in h.line()
    h.error("net down")
    assert "last error: 0m ago — net down" in h.line()
    t[0] = 90.0  # past the 60s window: old decisions fall off
    assert "0 decisions/min" in h.line()
    assert "2m ago — net down" in h.line()
    # the health line is emitted on the interval, not per event
    h.maybe_log()
    assert lines == []  # 90s < every_s=300s — not due yet
    t[0] = 300.0
    h.maybe_log()
    assert len(lines) == 1 and lines[0].startswith("testadp health:")
    h.maybe_log()  # immediately after: not due again
    assert len(lines) == 1


def test_run_loop_feeds_health():  # T699: the loop owns the counters
    sys.path.insert(0, "src")
    from gatekeeper.adapters.common import Health, run_loop
    t = [0.0]
    lines = []
    h = Health("testadp", clock=lambda: t[0], log=lines.append, every_s=10.0)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"a": "allow"}, {"a": "ignored"}, {"a": "command"}]
        if calls["n"] == 2:
            raise OSError("net down")
        raise _StopLoop  # BaseException: escapes run_loop's guards

    def handle(ev):
        return {"action": ev["a"]}

    try:
        run_loop(fetch, handle, name="testadp", sleep=lambda s: None, health=h)
    except _StopLoop:
        pass
    # ignored/command traffic isn't a decision; the allow is
    assert "1 decisions/min" in h.line()
    assert "last error: 0m ago — net down" in h.line()  # fetch failure logged
    t[0] = 10.0
    h.maybe_log()
    assert len(lines) == 1 and "1 decisions/min" in lines[0]


def test_adapters_wire_health():  # T699: every loop adapter reports health
    for name in ("telegram_bot", "matrix_bot", "zulip_bot"):
        src = (ADAPTERS / f"{name}.py").read_text()
        assert "health=Health(" in src, name  # wired through run_loop
    mm = (ADAPTERS / "mattermost.py").read_text()
    assert 'Health("mattermost")' in mm and "health.error(" in mm
    assert "health.decision()" in mm and "health.maybe_log()" in mm


def test_shared_redact_masks_tokens_and_emails(monkeypatch):  # T700
    sys.path.insert(0, "src")
    from gatekeeper.adapters.common import redact
    monkeypatch.setenv("TELEGRAM_TOKEN", "123456:AAFakeToken-xyz")
    monkeypatch.setenv("ZULIP_EMAIL", "bot@zulip.example.org")
    # exact env values are masked wherever they appear (exception echoes)
    s = redact("HTTPError: bot@zulip.example.org rejected "
               "token 123456:AAFakeToken-xyz")
    assert "123456:AAFakeToken-xyz" not in s and "***TELEGRAM_TOKEN***" in s
    assert "bot@zulip.example.org" not in s and "***ZULIP_EMAIL***" in s
    # credential schemes, emails, URL query secrets
    assert "Bearer ***" in redact("Authorization: Bearer abc123 rest")
    assert "oauth:***" in redact("PASS oauth:s3cret irc")
    assert "Basic ***" in redact("Basic dXNlcjpwYXNz")
    s = redact("contact admin@corp.example.org please")
    assert "admin@corp.example.org" not in s and "***@***" in s
    s = redact("POST https://hooks.example/x?token=shh&u=1")
    assert "shh" not in s and "token=***" in s
    # nothing to hide -> nothing mangled
    assert redact("just a normal message") == "just a normal message"


def test_adapter_output_is_redacted(monkeypatch, capsys):  # T700: wired
    sys.path.insert(0, "src")
    import gatekeeper
    monkeypatch.setenv("TELEGRAM_TOKEN", "sekrit-token-xyz")
    monkeypatch.setattr(gatekeeper, "moderate",
                        lambda t, r: {"action": "flag", "rule": "r",
                                      "confidence": 0.9})
    from gatekeeper.adapters.telegram_bot import handle_update
    handle_update(_tg_message("give me sekrit-token-xyz please "
                              "(mail admin@example.org)"), {"r": "t"})
    out = capsys.readouterr().out
    assert "sekrit-token-xyz" not in out and "***TELEGRAM_TOKEN***" in out
    assert "admin@example.org" not in out  # pasted emails don't leak either
    # the shared loop redacts stderr error lines and the health line
    from gatekeeper.adapters.common import Health, run_loop
    lines = []
    h = Health("t", clock=lambda: 0.0, log=lines.append)
    n = {"i": 0}

    def fetch():
        n["i"] += 1
        if n["i"] == 1:
            raise OSError("401 token sekrit-token-xyz")
        raise _StopLoop

    try:
        run_loop(fetch, lambda ev: None, name="t", sleep=lambda s: None,
                 health=h)
    except _StopLoop:
        pass
    err = capsys.readouterr().err
    assert "sekrit-token-xyz" not in err and "TELEGRAM_TOKEN" in err
    assert "sekrit-token-xyz" not in h.line()
    # every adapter either applies the pass or delegates to it
    for name in ("telegram_bot", "matrix_bot", "mattermost", "zulip_bot",
                 "webhooks", "twitch_irc"):
        src = (ADAPTERS / f"{name}.py").read_text()
        assert "redact(" in src, name


def test_rate_cap_sliding_window_and_sweep():  # T701
    sys.path.insert(0, "src")
    from gatekeeper.adapters.common import RateCap
    t = [0.0]
    cap = RateCap(max_calls=3, window_s=60.0, clock=lambda: t[0])
    assert all(cap.allow("u1") for _ in range(3))  # budget spent
    assert cap.allow("u1") is False  # 4th in-window call denied
    assert cap.allow("u2") is True  # other users keep their own budget
    t[0] = 61.0  # window slides: a fresh budget, not a permanent ban
    assert cap.allow("u1") is True
    t[0] = 200.0
    cap.allow("u3")  # the periodic sweep drops idle users
    assert "u1" not in cap._hits and "u2" not in cap._hits


def test_rate_cap_from_env(monkeypatch):  # T701
    sys.path.insert(0, "src")
    from gatekeeper.adapters.common import rate_cap_from_env
    monkeypatch.delenv("BOUNCER_RATE_CAP", raising=False)
    assert rate_cap_from_env().max_calls == 10  # sane default
    monkeypatch.setenv("BOUNCER_RATE_CAP", "3")
    assert rate_cap_from_env().max_calls == 3
    monkeypatch.setenv("BOUNCER_RATE_CAP", "0")
    assert rate_cap_from_env() is None  # opt-out
    monkeypatch.setenv("BOUNCER_RATE_CAP", "banana")
    assert rate_cap_from_env().max_calls == 10  # a typo must not crash a bot


def test_rate_cap_blocks_model_calls(monkeypatch, capsys):  # T701 e2e
    sys.path.insert(0, "src")
    import gatekeeper
    from gatekeeper.adapters.common import RateCap
    from gatekeeper.adapters.telegram_bot import handle_update
    calls = []
    monkeypatch.setattr(gatekeeper, "moderate",
                        lambda t, r: (calls.append(t),
                                      {"action": "allow", "rule": "ok",
                                       "confidence": 1.0})[1])
    rules = {"r": "t"}
    cap = RateCap(max_calls=2, window_s=60.0, clock=lambda: 0.0)
    for i in range(2):
        assert handle_update(_tg_message(f"msg {i}"), rules,
                             cap=cap)["action"] == "allow"
    assert len(calls) == 2
    # the flood message never reaches the model and is visibly logged
    res = handle_update(_tg_message("msg flood"), rules, cap=cap)
    assert res == {"action": "ignored", "reason": "rate-limited"}
    assert len(calls) == 2 and "[rate-limited]" in capsys.readouterr().out
    # commands bypass the cap (cheap, no model call)
    assert handle_update(_tg_message("/rules"), rules,
                         cap=cap)["action"] == "command"
    # no cap -> the old behavior, every message moderated
    assert handle_update(_tg_message("msg 3"), rules)["action"] == "allow"
    assert len(calls) == 3


def test_adapters_wire_rate_cap():  # T701: all four pollers carry a cap
    for name in ("telegram_bot", "matrix_bot", "mattermost", "zulip_bot"):
        src = (ADAPTERS / f"{name}.py").read_text()
        assert "rate_cap_from_env()" in src, name
        assert 'reason": "rate-limited"' in src, name


def test_install_shutdown_soft_flag_and_force():  # T702
    sys.path.insert(0, "src")
    import signal

    from gatekeeper.adapters.common import install_shutdown
    orig = signal.getsignal(signal.SIGTERM)
    try:
        lines = []
        stopping = install_shutdown("testadp", log=lines.append)
        assert stopping() is False
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not orig and callable(handler)
        handler(signal.SIGTERM, None)  # simulate the first SIGTERM
        assert stopping() is True
        assert lines == [("testadp: SIGTERM — finishing current page, "
                          "then exiting")]
        # a second SIGTERM force-exits (128+sig), like uvicorn
        try:
            handler(signal.SIGTERM, None)
        except SystemExit as e:
            assert e.code == 128 + signal.SIGTERM
        else:
            raise AssertionError("second SIGTERM must force-exit")
        # hard mode: the first SIGTERM exits immediately (discord's runner)
        hard = install_shutdown("testadp2", log=lines.append, hard=True)
        assert hard() is False
        try:
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        except SystemExit as e:
            assert e.code == 128 + signal.SIGTERM
        else:
            raise AssertionError("hard shutdown must exit immediately")
    finally:
        signal.signal(signal.SIGTERM, orig)  # never leak into other tests


def test_run_loop_stops_cleanly_on_shutdown(capsys):  # T702
    sys.path.insert(0, "src")
    from gatekeeper.adapters.common import run_loop
    state = {"stop": False, "fetched": 0}

    def fetch():
        state["fetched"] += 1
        state["stop"] = True  # the signal lands mid long-poll...
        raise OSError("connection reset")  # ...which often dies like this

    sleeps = []
    run_loop(fetch, lambda ev: None, name="testadp", sleep=sleeps.append,
             stopping=lambda: state["stop"])
    err = capsys.readouterr().err
    # exited at the error path without the backoff sleep, then cleanly
    assert state["fetched"] == 1 and sleeps == []
    assert "shutdown requested — exiting cleanly" in err


def test_adapters_install_shutdown():  # T702: every adapter, one way or another
    for name in ("telegram_bot", "matrix_bot", "mattermost", "zulip_bot",
                 "twitch_irc", "discord_bot"):
        src = (ADAPTERS / f"{name}.py").read_text()
        assert "install_shutdown(" in src, name
    # the pollers hand the flag to run_loop; mattermost/twitch/discord check
    # it in their own loops (discord's is hard: discord.py owns cleanup)
    for name in ("telegram_bot", "matrix_bot", "zulip_bot"):
        assert "stopping=stopping)" in (ADAPTERS / f"{name}.py").read_text()
    assert "hard=True" in (ADAPTERS / "discord_bot.py").read_text()
    assert "if stopping():" in (ADAPTERS / "twitch_irc.py").read_text()
    assert "if stopping():" in (ADAPTERS / "mattermost.py").read_text()


def test_adapter_matrix_is_complete_and_honest():  # T703
    text = (ADAPTERS / "README.md").read_text()
    # every adapter file in the package is a row in the matrix
    files = sorted(p.name for p in ADAPTERS.glob("*.py"))
    assert files  # the glob isn't silently empty
    for name in files:
        assert f"`adapters/{name}`" in text, name
    # the SDK column only names helpers that actually exist in common.py
    common = (ADAPTERS / "common.py").read_text()
    for fn in ("require_env", "load_rules", "run_loop", "Health", "RateCap",
               "redact", "dry_run", "install_shutdown", "verify_signature"):
        assert f"def {fn}" in common or f"class {fn}" in common, fn
        assert fn in text, fn
    # env opt-ins named in the matrix are real env vars in the sources
    for env in ("BOUNCER_TG_DELETE", "BOUNCER_MX_REDACT", "BOUNCER_MM_DELETE",
                "BOUNCER_ZL_DELETE"):
        assert env in text
        assert any(env in (ADAPTERS / f).read_text()
                   for f in files), env


def test_verify_signature_constant_time_helper():  # T704
    sys.path.insert(0, "src")
    import hashlib
    import hmac as _hmac

    from gatekeeper.adapters.common import verify_signature
    body = '{"text": "hi"}'
    good = _hmac.new(b"s3cret", body.encode(), hashlib.sha256).hexdigest()
    assert verify_signature("s3cret", good, body) is True
    assert verify_signature("s3cret", good, body + " ") is False  # tampered
    assert verify_signature("s3cret", "deadbeef", body) is False
    # GitHub-style prefixed scheme
    assert verify_signature("s3cret", "sha256=" + good, body,
                            prefix="sha256=") is True
    assert verify_signature("s3cret", good, body, prefix="sha256=") is False
    # bytes and str bodies verify identically
    assert verify_signature("s3cret", good, body.encode()) is True
    # malformed input is a mismatch, never an exception
    assert verify_signature("", good, body) is False
    assert verify_signature("s3cret", None, body) is False
    assert verify_signature("s3cret", good, None) is False
    assert verify_signature("s3cret", good, body,
                            digestmod="sha512") is False
    # comparison is constant-time, never ==
    assert "compare_digest" in (ADAPTERS / "common.py").read_text()


def test_slack_signature_scheme_and_replay_window(monkeypatch):  # T704
    sys.path.insert(0, "src")
    import hashlib
    import hmac as _hmac
    import time

    import gatekeeper
    from gatekeeper.adapters.webhooks import SlackError, receive_slack_event, verify_slack_signature
    secret = "signing-secret-xyz"
    raw = '{"text": "hello"}'
    ts = "1729160000.000100"
    sig = "v0=" + _hmac.new(secret.encode(), f"v0:{ts}:{raw}".encode(),
                            hashlib.sha256).hexdigest()
    monkeypatch.setattr(gatekeeper, "_router", _StubRouter())
    now = float(ts)
    assert verify_slack_signature(secret, ts, raw, sig, now=now) is True
    assert verify_slack_signature(secret, ts, raw + "x", sig,
                                  now=now) is False  # tampered body
    # replay window: stale or future-skewed beyond tolerance fails
    assert verify_slack_signature(secret, ts, raw, sig,
                                  now=now + 301) is False
    assert verify_slack_signature(secret, ts, raw, sig,
                                  now=now - 301) is False
    assert verify_slack_signature(secret, ts, raw, sig, now=now + 60) is True
    # garbage timestamps and missing pieces are mismatches, not crashes
    assert verify_slack_signature(secret, "not-a-ts", raw, sig,
                                  now=now) is False
    assert verify_slack_signature(secret, ts, raw, None, now=now) is False
    # no secret -> legacy behavior, no verification expected
    assert receive_slack_event({"text": "hi"}, {"r": "t"})["action"]
    # with a secret: a valid signature passes through to moderation
    fresh = str(time.time())
    raw2 = '{"text": "hi"}'
    sig2 = "v0=" + _hmac.new(secret.encode(),
                             f"v0:{fresh}:{raw2}".encode(),
                             hashlib.sha256).hexdigest()
    res = receive_slack_event({"text": "hi"}, {"r": "t"}, secret=secret,
                              raw=raw2, ts=fresh, signature=sig2)
    assert res["action"] in ("allow", "flag", "delete", "escalate")
    # a bad signature raises E_SLACK before moderation sees the event
    try:
        receive_slack_event({"text": "hi"}, {"r": "t"}, secret=secret,
                            raw=raw2, ts=fresh, signature="v0=bad")
    except SlackError as e:
        assert e.code == "E_SLACK" and "signature" in str(e)
    else:
        raise AssertionError("bad signature must raise E_SLACK")
    # fail-closed: a secret without the raw signed body raises too
    try:
        receive_slack_event({"text": "hi"}, {"r": "t"}, secret=secret,
                            ts=fresh, signature=sig2)
    except SlackError:
        pass
    else:
        raise AssertionError("missing raw body must fail closed")


def test_discord_prefix_and_slash_parse_identically():  # T705
    sys.path.insert(0, "src")
    from gatekeeper.adapters.discord_bot import command_reply, parse_command
    # T705 parity: prefix and slash forms yield the same subcommand...
    for sub in ("rules", "stats", "help"):
        assert parse_command(f"!bouncer {sub}") == sub
        assert parse_command(f"/bouncer {sub}") == sub
        assert parse_command(f"!BOUNCER {sub.upper()}") == sub  # case-proof
    # ...and the same table answers both
    rules = {"sin-spam": "t", "no-doxx": "t"}
    for sub in ("rules", "stats", "help"):
        a = command_reply(parse_command(f"!bouncer {sub}"), rules)
        b = command_reply(parse_command(f"/bouncer {sub}"), rules)
        assert a == b and a, sub
    # the bare prefix on either surface asks for help
    assert parse_command("!bouncer") == "help"
    assert parse_command("/bouncer") == "help"
    assert parse_command("  /bouncer  ") == "help"
    # trailing text after the subcommand doesn't break parsing
    assert parse_command("!bouncer rules now") == "rules"
    # non-commands pass through to moderation untouched
    assert parse_command("just talking") is None
    assert parse_command("!bouncerx") is None  # not our prefix
    assert parse_command("") is None
    # the table itself
    assert command_reply("rules", rules) == "active: sin-spam, no-doxx"
    assert command_reply("stats", rules,
                         stats={"allow": 2, "flag": 1}) == \
        "decisions: allow=2, flag=1"
    assert "bouncer" in command_reply("help", rules)
    assert command_reply("bogus", rules) is None  # unknown -> the handler's
    # `or command_reply("help", rules)` fallback answers instead


def test_discord_surfaces_share_the_command_table():  # T705: wired for real
    src = (ADAPTERS / "discord_bot.py").read_text()
    # on_message routes commands through parse_command + command_reply...
    assert "cmd = parse_command(msg.content)" in src
    assert "command_reply(cmd, rules)" in src
    # ...and the slash command answers from the same table
    assert "client.tree.command" in src
    assert "command_reply(command, rules)" in src
    # no hardcoded "!bouncer ..." message checks left in the handler
    assert '"!bouncer rules"' not in src and '"!bouncer stats"' not in src


def test_twitch_mentions_and_whispers_documented():  # T706
    sys.path.insert(0, "src")
    from gatekeeper.adapters import twitch_irc as tw
    # mentions are ordinary PRIVMSG text — the parser hands them to
    # moderation unchanged (the @-prefix is just text to the rules pass)
    assert tw._parse_privmsg(":u!u@h PRIVMSG #c :@bouncer buy followers now") \
        == ("u", "@bouncer buy followers now")
    # whispers arrive as WHISPER lines and are dropped pre-moderation:
    # a flag-only print bot can't act on a private message (T706 scope)
    assert tw._parse_privmsg(":u!u@h WHISPER #c :secret offer") is None
    # the docs own the decision — docstring and README both say so
    doc = (ADAPTERS / "twitch_irc.py").read_text()
    assert "Whispers (T706)" in doc and "Mentions (T706)" in doc
    readme = (ADAPTERS / "README.md").read_text()
    assert "whispers" in readme.lower() and "T706" in readme
