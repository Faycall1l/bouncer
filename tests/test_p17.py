"""P17 tests (T291-T310): security + server guards. No weights."""
import sys

sys.path.insert(0, "src")

import pytest
from fastapi.testclient import TestClient

import gatekeeper
from gatekeeper import serve


class FakeReq:
    def __init__(self, headers=None, host="1.2.3.4"):
        self.headers = headers or {}

        class C:
            pass
        c = C()
        c.host = host
        self.client = c


@pytest.fixture(autouse=True)
def _iso():
    serve._BUCKETS.clear()
    yield


def test_body_too_big():  # T291
    assert serve._body_too_big(FakeReq({"content-length": "2000000"})) is True
    assert serve._body_too_big(FakeReq({"content-length": "10"})) is False
    assert serve._body_too_big(FakeReq({})) is False


def test_rate_429_has_retry_after():  # T306
    from fastapi import HTTPException
    req = FakeReq()
    with pytest.raises(HTTPException) as ei:
        for _ in range(61):
            serve._rate(req)
    assert ei.value.status_code == 429
    assert ei.value.headers["Retry-After"] == "60"


def test_guards_end_to_end():  # T305+T308+T309+T304
    class S:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    gatekeeper._router = S()
    client = TestClient(serve.app)
    assert client.get("/health").json()["model"] in ("loaded", "unavailable")
    assert client.get("/health").headers["X-Content-Type-Options"] == "nosniff"
    r = client.post("/predict", json={"message": "hi", "rules": {"a": "rule a text"},
                                      "context": ["x"] * 21})
    assert r.status_code == 422
    r = client.post("/predict/batch", json={"messages": ["x" * 8001],
                                            "rules": {"a": "rule a text"}})
    assert r.status_code == 413


def test_internal_handler():  # T269
    class Boom:
        def predict(self, state, questions):
            raise RuntimeError("kaput")
    gatekeeper._router = Boom()
    client = TestClient(serve.app, raise_server_exceptions=False)
    r = client.post("/v1/systemone", json={"state": {}, "questions": {}})
    assert r.status_code == 500 and r.json()["detail"]["code"] == "E_INTERNAL"


def test_webhooks(monkeypatch):  # T293+T294+T295+T301+T302
    import urllib.error

    from gatekeeper.adapters import webhooks as wh
    monkeypatch.setenv("BOUNCER_FORWARD_URL", "http://x/hook")

    seen = {}

    class Resp:
        def read(self):
            return b"ok"

    def _ok(req, timeout):
        seen["req"] = req
        return Resp()
    orig = wh.urllib.request.urlopen
    wh.urllib.request.urlopen = _ok
    try:
        wh.forward("http://x", {"action": "delete"})
        headers = {k.lower(): v for k, v in seen["req"].header_items()}
        assert headers["x-bouncer-event"] == "delete"
        assert headers["user-agent"].startswith("bouncer/")
        assert wh.forward_if_interesting({"action": "escalate", "rule": "r",
                                          "confidence": 0.5, "reason": "why"}, "m") is True
        assert wh.forward_if_interesting({"action": "allow", "rule": "ok",
                                          "confidence": 1.0}, "m") is False
    finally:
        wh.urllib.request.urlopen = orig

    def _boom(req, timeout):
        raise urllib.error.URLError("down")
    wh.urllib.request.urlopen = _boom
    try:
        with pytest.raises(wh.WebhookError, match="E_WEBHOOK"):
            wh.forward("http://x", {"action": "delete"})
    finally:
        wh.urllib.request.urlopen = orig

    with pytest.raises(wh.SlackError, match="E_SLACK"):
        wh.receive_slack_event(["nope"], {})
    with pytest.raises(wh.SlackError, match="E_SLACK"):
        wh.receive_slack_event({"text": 5}, {})
    ignored = wh.receive_slack_event({"text": "hi", "subtype": "bot_message"}, {})
    assert ignored["ignored"] is True and ignored["action"] == "allow"


def test_twitch_helpers():  # T299+T300
    import os

    from gatekeeper.adapters import twitch_irc as tw
    os.environ["TWITCH_TOKEN"] = "secret-token-xyz"
    try:
        assert "***" in tw.redact("PASS secret-token-xyz here")
        assert tw.redact("PASS oauth:abc123 here") == "PASS oauth:*** here"
        line = ":nick!u@h PRIVMSG #c :hello chat"
        assert tw._parse_privmsg(line) == ("nick", "hello chat")
        assert tw._parse_privmsg("PING :tmi") is None
        assert tw._parse_privmsg(":nick!u@h PRIVMSG #c") is None
    finally:
        del os.environ["TWITCH_TOKEN"]
