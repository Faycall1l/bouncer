"""P45 tests (T851-T870): adapter depth. All network is stubbed."""
import io
import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, "src")

from gatekeeper.adapters import common, matrix_bot, mattermost, telegram_bot
from gatekeeper.adapters import zulip_bot as zulip

ADAPTERS = Path("src/gatekeeper/adapters")


class _Resp:
    """Minimal context-managed JSON response (what urlopen yields)."""

    def __init__(self, payload: bytes):
        self._body = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _http_error(code: int, headers: dict | None = None):
    return urllib.error.HTTPError(
        "http://stub", code, "stub", headers or {}, io.BytesIO(b""))


def test_http_json_retries_429_honoring_retry_after():  # T851
    """429 with Retry-After: retried, the wait is the header value."""
    calls = {"n": 0}
    slept = []

    def open_(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, {"Retry-After": "1.5"})
        return _Resp(json.dumps({"ok": True}).encode())

    out = common.http_json(urllib.request.Request("http://stub/x"),
                           opener=open_, sleep=slept.append, attempts=3)
    assert out == {"ok": True}
    assert calls["n"] == 2, "one failure, one success"
    assert slept == [1.5], f"Retry-After must drive the wait, got {slept}"


def test_http_json_5xx_retries_then_gives_up():  # T851
    """5xx is transient per the server; the budget is real, not infinite."""
    calls = {"n": 0}
    slept = []

    def open_(req, timeout=None):
        calls["n"] += 1
        raise _http_error(503)

    try:
        common.http_json(urllib.request.Request("http://stub/x"),
                         opener=open_, sleep=slept.append, attempts=3)
        raise AssertionError("exhausted budget must raise")
    except urllib.error.HTTPError as e:
        assert e.code == 503, "the caller sees the real status"
    assert calls["n"] == 3, "exactly `attempts` tries"
    assert len(slept) == 2, "two waits between three tries"
    assert all(0 < w <= 8.0 for w in slept), slept


def test_http_json_4xx_raises_on_first_try():  # T851
    """A 404/401 doesn't improve by retrying — one call, then raise."""
    calls = {"n": 0}

    def open_(req, timeout=None):
        calls["n"] += 1
        raise _http_error(404)

    try:
        common.http_json(urllib.request.Request("http://stub/x"),
                         opener=open_, sleep=lambda s: None, attempts=3)
        raise AssertionError("404 must raise")
    except urllib.error.HTTPError as e:
        assert e.code == 404
    assert calls["n"] == 1, "non-retryable statuses cost one call"


def test_http_json_network_error_raises_immediately():  # T851
    """URLError (DNS/TLS/timeout) propagates as the docstrings promise —
    run_loop backs off network blips at the loop level (T696), not here."""
    calls = {"n": 0}

    def open_(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.URLError("down")

    try:
        common.http_json(urllib.request.Request("http://stub/x"),
                         opener=open_, sleep=lambda s: None, attempts=3)
        raise AssertionError("URLError must raise")
    except urllib.error.URLError:
        pass
    assert calls["n"] == 1, "transport errors are not status retries"


def test_all_four_api_copies_use_the_shared_helper(monkeypatch):  # T851
    """The point of the box: one retry implementation, not five copies."""
    seen = []

    def fake_http_json(req, *, timeout, **kw):
        seen.append((req.full_url, timeout))
        return {"stub": True}

    monkeypatch.setattr(common, "http_json", fake_http_json)
    assert telegram_bot.api("tok", "sendMessage", chat_id=1) == {"stub": True}
    assert mattermost.api("tok", "https://mm", "POST", "/posts") == {"stub": True}
    assert matrix_bot.api("tok", "https://hs", "PUT", "/send") == {"stub": True}
    assert zulip.api("bot@x", "key", "https://z", "POST", "/messages") == {"stub": True}
    assert len(seen) == 4, "every bot api() must route through http_json"


def test_backoff_wait_doubles_caps_and_jitters():  # T852 (T853 reuses it)
    """The shared ladder: exponential, capped, jittered into [half, full] —
    never 0 (that's a hot loop against a dead server), never past the cap."""

    def full(attempt, base_s=1.0, cap_s=60.0):
        return common.backoff_wait(attempt, base_s=base_s, cap_s=cap_s,
                                   rand=lambda: 1.0)

    def half(attempt, base_s=1.0, cap_s=60.0):
        return common.backoff_wait(attempt, base_s=base_s, cap_s=cap_s,
                                   rand=lambda: 0.0)

    assert full(0) == 1.0 and half(0) == 0.5, "attempt 0 waits base (halved)"
    assert full(3) == 8.0, "the span doubles per attempt"
    assert full(10, cap_s=8.0) == 8.0, "the cap is a ceiling, not a target"
    assert half(10, cap_s=8.0) == 4.0, "jitter still halves the capped span"
    assert full(10 ** 9) == 60.0, "a week of failures must not OverflowError"
    for r in (0.0, 0.25, 0.5, 1.0):  # every jitter lands inside the span
        w = common.backoff_wait(4, base_s=1.0, cap_s=60.0, rand=lambda r=r: r)
        assert 8.0 <= w <= 16.0, w


def test_areconnect_redials_with_escalating_capped_backoff(capsys):  # T852
    """A dropped socket used to end the process; now it costs one redacted
    line, one health error, and a jittered wait — escalating while sessions
    stay short-lived, resetting once one stays up (time, not frames: a
    server can send `hello` before rejecting your token, and an idle
    healthy channel sends nothing for hours)."""
    import asyncio

    t = {"now": 0.0}
    slept, dials = [], {"n": 0}
    stop = {"v": False}

    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    def dial():
        dials["n"] += 1
        return _Conn()

    async def consume(conn):
        n = dials["n"]
        if n == 1:
            raise ConnectionError("reset by peer")  # short-lived drop
        if n == 2:
            return  # server closed us — also short-lived
        if n == 3:
            t["now"] += 60  # stable session: proves the path, resets ladder
            return
        if n == 4:
            raise ConnectionError("reset by peer")  # short again
        t["now"] += 60  # session 5 stays up ...
        stop["v"] = True  # ... until SIGTERM lands

    async def fake_sleep(s):
        slept.append(s)

    class _Health:
        def __init__(self):
            self.errors = []

        def error(self, msg):
            self.errors.append(str(msg))

    health = _Health()
    asyncio.run(common.areconnect(
        dial, consume, name="t852", sleep=fake_sleep, clock=lambda: t["now"],
        rand=lambda: 1.0, health=health, stopping=lambda: stop["v"]))

    assert dials["n"] == 5, "four dead sessions, four redials, then shutdown"
    # 1, 2 escalate across short sessions; the stable session 3 resets the
    # ladder so session 4 waits 1.0 again — not 4.0 — and 2.0 once more
    assert slept == [1.0, 2.0, 1.0, 2.0], f"ladder shape: {slept}"
    err = capsys.readouterr().err
    assert err.count("t852 connection error:") == 4, "one line per dead session"
    assert "reset by peer" in err and "server closed the connection" in err
    assert len(health.errors) == 4, "every drop lands in health (T699/T700)"
    assert "t852: shutdown requested — exiting cleanly" in err


def test_areconnect_lets_ctrl_c_through():  # T852: BaseException is sacred
    import asyncio

    slept = []
    stop = {"v": False}

    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def consume(conn):
        raise KeyboardInterrupt

    async def fake_sleep(s):
        slept.append(s)
        stop["v"] = True  # only reachable if KeyboardInterrupt were swallowed

    try:
        asyncio.run(common.areconnect(lambda: _Conn(), consume, name="t852",
                                      sleep=fake_sleep,
                                      stopping=lambda: stop["v"]))
        raise AssertionError("Ctrl-C must end a bot, not reconnect it")
    except KeyboardInterrupt:
        pass
    assert slept == [], "no backoff after Ctrl-C"


def test_areconnect_exits_cleanly_before_dialing(capsys):  # T852 + T702
    """SIGTERM while disconnected: no new connection, one clean-exit line."""
    import asyncio

    dials = {"n": 0}
    slept = []

    def dial():
        dials["n"] += 1
        raise AssertionError("shutdown must not open connections")

    async def fake_sleep(s):
        slept.append(s)

    asyncio.run(common.areconnect(dial, lambda c: None, name="t852",
                                  sleep=fake_sleep, stopping=lambda: True))
    err = capsys.readouterr().err
    assert dials["n"] == 0 and slept == [], "exit before the ladder runs"
    assert "t852: shutdown requested — exiting cleanly" in err


def test_mattermost_run_wires_areconnect():  # T852
    """run() owns no loop anymore — the redial ladder lives in common.py
    (test_p37 pins: no `while True` in mattermost, `async for` stays here)."""
    src = (ADAPTERS / "mattermost.py").read_text()
    assert "asyncio.run(areconnect(_dial, _consume" in src
    assert "async def _loop" not in src, "the old single-shot closure is gone"


def test_mattermost_session_streams_posts_until_shutdown(monkeypatch):  # T852
    """The extracted session body behaves exactly as _loop did: auth frame
    first, non-posted frames skipped, one decision per moderated post, and
    a message-boundary exit when SIGTERM flips the flag."""
    import asyncio

    handled = []
    stop = {"v": False}

    def fake_handle_post(post, rules, *, token=None, server=None,
                         can_delete=False, api_fn=None, out=None, cap=None):
        handled.append(post["id"])
        stop["v"] = True  # SIGTERM lands mid-session
        return {"action": "normal"}

    monkeypatch.setattr(mattermost, "handle_post", fake_handle_post)

    class _WS:
        def __init__(self, frames):
            self.frames = list(frames)
            self.sent = []

        async def send(self, payload):
            self.sent.append(json.loads(payload))

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.frames:
                raise StopAsyncIteration
            return json.dumps(self.frames.pop(0))

    class _Health:
        def __init__(self):
            self.decisions = 0
            self.errors = []

        def decision(self):
            self.decisions += 1

        def error(self, msg):
            self.errors.append(str(msg))

        def maybe_log(self):
            pass

    ws = _WS([
        {"event": "hello"},  # not a posted event: skipped, not a decision
        {"event": "posted", "data": {}},  # no post: skipped
        {"event": "posted",
         "data": {"post": json.dumps({"id": "p1", "message": "hi"})}},
        {"event": "posted",
         "data": {"post": json.dumps({"id": "p2", "message": "unread"})}},
    ])
    health = _Health()
    asyncio.run(mattermost._session(ws, token="tok", rules={}, server="https://mm",
                                    can_delete=False, cap=None, health=health,
                                    stopping=lambda: stop["v"]))
    assert ws.sent and ws.sent[0]["action"] == "authentication", "auth first"
    assert ws.sent[0]["data"]["token"] == "tok"
    assert handled == ["p1"], "the boundary exit wins before p2 is moderated"
    assert health.decisions == 1 and health.errors == []


def test_run_loop_backoff_escalates_to_the_cap_and_keeps_trying(capsys):  # T853
    """Infinite retries with a shape: 5, 10, 20, 40, 60, 60 — exponential,
    capped, one redacted line per failure, and no give-up exception (an
    outage is not something the bot can fix by exiting)."""
    sleeps = []
    stop = {"v": False}

    def fetch():
        raise OSError("server down")

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 6:
            stop["v"] = True  # operator gives up; the ladder never does

    common.run_loop(fetch, lambda ev: None, name="t853", sleep=fake_sleep,
                    rand=lambda: 1.0, stopping=lambda: stop["v"])
    assert sleeps == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0], sleeps
    err = capsys.readouterr().err
    assert err.count("t853 error:") == 6, "one line per failure, no crash"
    assert "t853: shutdown requested — exiting cleanly" in err


def test_run_loop_backoff_resets_after_a_good_fetch(capsys):  # T853
    """Jitter lands at [half, full] of the span, and one good fetch resets
    the ladder: the second failure waits the half-base again (2.5), not the
    doubled half (5.0) it would wait if successes counted for nothing."""
    calls = {"n": 0}
    sleeps = []
    stop = {"v": False}

    def fetch():
        calls["n"] += 1
        if calls["n"] == 5:
            stop["v"] = True  # SIGTERM lands while the long-poll dies
            raise OSError("dying during shutdown")
        if calls["n"] in (1, 3):
            raise OSError("blip")
        return []

    common.run_loop(fetch, lambda ev: None, name="t853", sleep=sleeps.append,
                    rand=lambda: 0.0, stopping=lambda: stop["v"])
    assert sleeps == [2.5, 2.5], f"half-jitter, ladder reset: {sleeps}"
    err = capsys.readouterr().err
    assert err.count("t853 error:") == 3, "blip, blip, shutdown-time failure"
    # T702 ordering intact: the shutdown-time failure exits before sleeping
    assert "t853: shutdown requested — exiting cleanly" in err


def test_discord_wires_health_and_ratecap():  # T854
    """Parity box: discord reports Health and enforces RateCap like every
    other acting adapter — built in run(), enforced in moderate_message."""
    src = (ADAPTERS / "discord_bot.py").read_text()
    assert 'Health("discord")' in src and "rate_cap_from_env(cfg)" in src
    assert "moderate_message(msg.content, msg.author.id," in src
    assert "health=health, cap=cap" in src
    assert "health.decision()" in src and "health.error(" in src
    assert "health.maybe_log()" in src and "cap.allow(" in src


def test_discord_moderate_message_caps_then_counts(monkeypatch, capsys):  # T854
    """RateCap runs before the model (a flood never reaches it), Health
    counts real decisions but not capped or ignored traffic, and
    maybe_log() fires on every message — the guards the pollers had."""
    import gatekeeper
    from gatekeeper.adapters import discord_bot as db
    from gatekeeper.adapters.common import RateCap

    calls = []

    def fake_moderate(text, rules, **kw):
        calls.append(text)
        return {"action": "delete", "rule": "r", "confidence": 0.9}

    monkeypatch.setattr(gatekeeper, "moderate", fake_moderate)

    class _Health:
        def __init__(self):
            self.decisions = 0
            self.logged = 0

        def decision(self):
            self.decisions += 1

        def maybe_log(self):
            self.logged += 1

        def error(self, e):
            raise AssertionError("no errors in this session")

    health = _Health()
    cap = RateCap(max_calls=2, window_s=60.0, clock=lambda: 0.0)
    out = [db.moderate_message("spam one", 42, {}, health=health, cap=cap),
           db.moderate_message("spam two", 42, {}, health=health, cap=cap),
           db.moderate_message("spam three", 42, {}, health=health, cap=cap)]
    assert [r["action"] for r in out] == ["delete", "delete", "ignored"]
    assert out[2]["reason"] == "rate-limited"
    assert calls == ["spam one", "spam two"], "the capped call never hits the model"
    assert health.decisions == 2 and health.logged == 3
    assert "[rate-limited] <42> over the per-user cap" in capsys.readouterr().out
    # cap=None (BOUNCER_RATE_CAP=0) disables the guard — straight to the model
    assert db.moderate_message("x", 42, {}, health=health,
                               cap=None)["action"] == "delete"
    assert calls == ["spam one", "spam two", "x"]


def test_discord_moderate_message_survives_model_failure(monkeypatch, capsys):  # T854
    """A model crash costs one redacted line plus one recorded health
    error, answers ignored, and keeps the health line due — the per-event
    guard run_loop gives its traffic, now on discord too."""
    import gatekeeper
    from gatekeeper.adapters import discord_bot as db

    def boom(text, rules, **kw):
        raise RuntimeError("model down")

    monkeypatch.setattr(gatekeeper, "moderate", boom)

    class _Health:
        def __init__(self):
            self.errors = []
            self.logged = 0

        def decision(self):
            raise AssertionError("a crash is no decision")

        def maybe_log(self):
            self.logged += 1

        def error(self, e):
            self.errors.append(str(e))

    health = _Health()
    res = db.moderate_message("hello", "u1", {}, health=health, cap=None)
    assert res == {"action": "ignored", "reason": "moderate-error"}
    err = capsys.readouterr().err
    assert "discord event error: model down" in err
    assert health.errors == ["model down"] and health.logged == 1


def test_twitch_wires_health_reporting():  # T855
    """Never bans, but reports: run() builds Health and hands it to the
    session, which counts, records and logs like every other adapter."""
    src = (ADAPTERS / "twitch_irc.py").read_text()
    assert 'Health("twitch")' in src
    assert "_watch_once(sock, rules, health=health)" in src
    assert "health.decision()" in src and "health.error(" in src
    assert "health.maybe_log()" in src


def test_twitch_watch_once_counts_decisions_and_errors(monkeypatch, capsys):  # T855
    """A full IRC transcript through _watch_once: delete and allows are
    decisions, a model crash is one printed line plus one recorded error,
    maybe_log() sees every message, and the PONG keepalive still fires."""
    import gatekeeper
    from gatekeeper.adapters import twitch_irc as tw

    def fake_moderate(text, rules, **kw):
        if "buy followers" in text:
            return {"action": "delete", "rule": "no-spam", "confidence": 0.99}
        if text == "boom":
            raise RuntimeError("model down")
        return {"action": "allow", "rule": "ok", "confidence": 1.0}

    monkeypatch.setattr(gatekeeper, "moderate", fake_moderate)

    class _Sock:  # test_p37 T708's scripted transcript, then "closes"
        def __init__(self, lines):
            self._data = "".join(l + "\r\n" for l in lines).encode()
            self._pos = 0
            self.sent = []

        def recv(self, n):
            if self._pos >= len(self._data):
                raise OSError("transcript over")
            chunk = self._data[self._pos:self._pos + n]
            self._pos += len(chunk)
            return chunk

        def sendall(self, b):
            self.sent.append(b)

    class _Health:
        def __init__(self):
            self.decisions = 0
            self.errors = []
            self.logged = 0

        def decision(self):
            self.decisions += 1

        def error(self, e):
            self.errors.append(str(e))

        def maybe_log(self):
            self.logged += 1

    sock = _Sock(["PING :tmi.twitch.tv",
                  ":u!u@h PRIVMSG #c :buy followers now",
                  ":u!u@h PRIVMSG #c :hello chat",
                  ":u!u@h PRIVMSG #c :boom",
                  ":u!u@h PRIVMSG #c :one more"])
    health = _Health()
    try:
        tw._watch_once(sock, {"no-spam": "t"}, health=health)
    except OSError:
        pass  # the transcript ends; run()'s retry loop owns reconnects
    out = capsys.readouterr()
    assert sock.sent == [b"PONG :tmi.twitch.tv\r\n"]
    assert "[delete] <u> buy followers now" in out.out
    assert "mod error" in out.err and "model down" in out.err
    assert health.decisions == 3, "delete + two allows are decisions"
    assert health.errors == ["model down"], "the crash is recorded once"
    assert health.logged == 4, "every message keeps the health line on time"


def test_as_user_id_normalizes_for_the_strike_table():  # T856
    """Strikes keys round-trip through JSON: ints become str or today's
    live count would split from its reloaded key — and a payload without
    a sender stays None, never the literal strike target "None"."""
    from gatekeeper.adapters.common import as_user_id
    assert as_user_id(42) == "42" and as_user_id("u1") == "u1"
    assert as_user_id(None) is None and as_user_id(0) == "0"


def test_every_adapter_passes_the_platform_user_to_moderate(monkeypatch):  # T856
    """Per-user strikes accrue from platform traffic (CLI-only before):
    all seven moderate() call sites hand the platform's user over, already
    normalized as moderate()'s str | None signature demands."""
    import gatekeeper
    from gatekeeper.adapters import discord_bot as db
    from gatekeeper.adapters import matrix_bot, mattermost, webhooks
    from gatekeeper.adapters import telegram_bot as tg
    from gatekeeper.adapters import twitch_irc as tw
    from gatekeeper.adapters import zulip_bot as zl

    seen = []

    def record(text, rules, **kw):
        seen.append(kw.get("user_id"))
        return {"action": "allow", "rule": "ok", "confidence": 1.0}

    monkeypatch.setattr(gatekeeper, "moderate", record)
    rules = {"r": "t"}

    # 1) telegram: message.from.id  2) matrix: event.sender
    tg.handle_update({"message": {"text": "hi", "message_id": 7,
                                  "chat": {"id": 1}, "from": {"id": 99}}}, rules)
    matrix_bot.handle_event(
        {"type": "m.room.message", "event_id": "$e", "room_id": "!r",
         "sender": "@user:example.org",
         "content": {"msgtype": "m.text", "body": "hi"}}, rules)
    # 3) zulip: message.sender_id  4) mattermost: post.user_id
    zl.handle_event({"type": "message",
                     "message": {"type": "stream", "content": "hi",
                                 "sender_id": 42, "id": 11}}, rules)
    mattermost.handle_post({"id": "p1", "message": "hi",
                            "user_id": "mm-user"}, rules)
    # 5) discord: msg.author.id (through moderate_message)
    class _H:
        def decision(self):
            pass

        def maybe_log(self):
            pass

        def error(self, e):
            pass

    db.moderate_message("hi", 4242, rules, health=_H(), cap=None)

    # 6) twitch: the PRIVMSG nick (transcript ends -> OSError, not ours)
    class _Sock:
        def __init__(self, lines):
            self._data = "".join(l + "\r\n" for l in lines).encode()
            self._pos = 0

        def recv(self, n):
            if self._pos >= len(self._data):
                raise OSError("transcript over")
            chunk = self._data[self._pos:self._pos + n]
            self._pos += len(chunk)
            return chunk

        def sendall(self, b):
            pass

    try:
        tw._watch_once(_Sock([":u!u@h PRIVMSG #c :hi"]), rules)
    except OSError:
        pass
    # 7) slack: event.user
    webhooks.receive_slack_event({"text": "hi", "user": "U123"}, rules)

    assert seen == ["99", "@user:example.org", "42", "mm-user", "4242",
                    "u", "U123"], seen
    assert all(isinstance(u, str) for u in seen), "str keys, always (T340)"


def test_platform_traffic_accrues_real_strikes(monkeypatch):  # T856
    """The point of the box: a delete issued for a platform user lands in
    the same strike table the CLI writes — and res tells the operator."""
    from test_cli import Stub  # the deterministic router shape (T134)

    import gatekeeper
    from gatekeeper import strikes
    from gatekeeper.adapters.telegram_bot import handle_update

    monkeypatch.setattr(gatekeeper, "_router", Stub(choice="no-cheat",
                                                    conf=0.99))
    strikes.reset()
    try:
        res = handle_update(
            {"message": {"text": "aimbot for sale", "message_id": 7,
                         "chat": {"id": 1}, "from": {"id": 77}}},
            gatekeeper.get_preset("gaming"))
        assert res["action"] == "delete", res
        assert res["strikes"]["user"] == "77", res["strikes"]
        assert res["strikes"]["strikes"] == strikes.standing("77")["strikes"] >= 1
        assert strikes.standing(77)["strikes"] == 0, "int key would split the table"
    finally:
        strikes.reset()  # T249: test isolation


def test_detect_lang_maps_script_to_checkpoint_tags():  # T857
    """Script hint -> routing tag: arabic/cjk/cyrillic become ar/zh/ru (all
    three pin the same multilingual checkpoint), latin/other stay None so
    nothing claims a language detect_script refuses to claim."""
    from gatekeeper.adapters.common import detect_lang
    from gatekeeper.pool import model_for_lang
    assert detect_lang("hello world") is None, "latin keeps laya's auto route"
    assert detect_lang("مباراة جيدة") == "ar"
    assert detect_lang("привет") == "ru"
    assert detect_lang("你好世界") == "zh"
    assert detect_lang("123 !!!") is None and detect_lang("") is None
    assert detect_lang(None) is None
    for msg in ("مرحبا", "你好", "привет"):  # the point: these stop auto-routing
        assert model_for_lang(detect_lang(msg)) == "multilingual", msg


def test_adapters_pass_detected_lang_to_moderate(monkeypatch):  # T857
    """Platform traffic stops routing as auto: every moderate() call carries
    lang= from detect_lang — non-latin text gets the tag that pins the
    multilingual checkpoint, latin text passes None (documented auto)."""
    import gatekeeper
    from gatekeeper.adapters import discord_bot as db
    from gatekeeper.adapters import matrix_bot, mattermost, webhooks
    from gatekeeper.adapters import telegram_bot as tg
    from gatekeeper.adapters import twitch_irc as tw
    from gatekeeper.adapters import zulip_bot as zl

    seen = []

    def record(text, rules, **kw):
        seen.append(kw.get("lang"))
        return {"action": "allow", "rule": "ok", "confidence": 1.0}

    monkeypatch.setattr(gatekeeper, "moderate", record)
    rules = {"r": "t"}

    tg.handle_update({"message": {"text": "مباراة جميلة", "message_id": 7,
                                  "chat": {"id": 1}, "from": {"id": 99}}}, rules)
    matrix_bot.handle_event(
        {"type": "m.room.message", "event_id": "$e", "room_id": "!r",
         "sender": "@user:example.org",
         "content": {"msgtype": "m.text", "body": "привет всем"}}, rules)
    zl.handle_event({"type": "message",
                     "message": {"type": "stream", "content": "你好世界",
                                 "sender_id": 42, "id": 11}}, rules)
    mattermost.handle_post({"id": "p1", "message": "hello channel",
                            "user_id": "mm-user"}, rules)

    class _H:
        def decision(self):
            pass

        def maybe_log(self):
            pass

        def error(self, e):
            pass

    db.moderate_message("مرحبا بالجميع", 4242, rules, health=_H(), cap=None)

    class _Sock:  # test_p37 T708's scripted transcript, then "closes"
        def __init__(self, lines):
            self._data = "".join(l + "\r\n" for l in lines).encode()
            self._pos = 0

        def recv(self, n):
            if self._pos >= len(self._data):
                raise OSError("transcript over")
            chunk = self._data[self._pos:self._pos + n]
            self._pos += len(chunk)
            return chunk

        def sendall(self, b):
            pass

    try:
        tw._watch_once(_Sock([":u!u@h PRIVMSG #c :привет"]), rules)
    except OSError:
        pass
    webhooks.receive_slack_event({"text": "你好", "user": "U123"}, rules)

    assert seen == ["ar", "ru", "zh", None, "ar", "ru", "zh"], seen
    for name in ("telegram_bot", "matrix_bot", "zulip_bot", "mattermost",
                 "discord_bot", "twitch_irc", "webhooks"):  # all seven wired
        assert "detect_lang(" in (ADAPTERS / f"{name}.py").read_text(), name
