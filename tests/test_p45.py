"""P45 tests (T851-T870): adapter depth. All network is stubbed."""
import io
import json
import sys
import urllib.error

sys.path.insert(0, "src")

from gatekeeper.adapters import common, matrix_bot, mattermost, telegram_bot
from gatekeeper.adapters import zulip_bot as zulip


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
