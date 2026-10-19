"""P44 tests (T831-T850): server hardening. Weightless."""
import asyncio
import sys

sys.path.insert(0, "src")


def _run(coro):
    return asyncio.run(coro)


def _post_through(cap_app, chunks, send_list):
    """Drive one POST through the middleware with a canned chunk list."""

    async def receive():
        if chunks:
            return chunks.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        send_list.append(message)

    scope = {"type": "http", "method": "POST", "path": "/predict",
             "headers": [], "query_string": b""}
    _run(cap_app(scope, receive, send))


def _echo_app(reached):
    """Inner app that reads the full body like FastAPI does, then 200s."""

    async def app(scope, receive, send):
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        reached.append(len(body))
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})

    return app


def test_stream_cap_rejects_chunked_oversize():  # T831
    """Content-Length is client-trust: a chunked POST sends no header at
    all and used to sail past T775's check untouched. The stream cap
    counts real bytes and 413s past the limit — before the handler runs."""
    from gatekeeper import serve

    reached, sent = [], []
    capped = serve._StreamBodyCap(_echo_app(reached), limit=1000)
    chunks = [{"type": "http.request", "body": b"x" * 400, "more_body": True}
              for _ in range(4)]  # 1600 real bytes, no Content-Length anywhere
    _post_through(capped, chunks, sent)
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
    assert reached == [], "the handler ran on an over-cap body"


def test_stream_cap_passes_undersized_body():  # T831
    """Under the cap the body flows through untouched — the handler sees
    every byte and the response is the app's own."""
    from gatekeeper import serve

    reached, sent = [], []
    capped = serve._StreamBodyCap(_echo_app(reached), limit=1000)
    chunks = [{"type": "http.request", "body": b"x" * 400, "more_body": True},
              {"type": "http.request", "body": b"y" * 400, "more_body": False}]
    _post_through(capped, chunks, sent)
    assert reached == [800]
    assert sent[0]["status"] == 200


def test_stream_cap_ignores_non_post_and_disconnect():  # T831
    """GETs and the disconnect message take the pass-through path — the
    cap only ever counts http.request bytes on POST."""
    from gatekeeper import serve

    reached, sent = [], []

    async def app_pass(scope, receive, send):
        reached.append("called")
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    capped = serve._StreamBodyCap(app_pass, limit=1000)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": "/health", "headers": []}
    _run(capped(scope, receive, send))
    assert reached == ["called"] and sent[0]["status"] == 204


def test_header_413_still_holds():  # T831: T775's fast path unchanged
    """The Content-Length fast path still 413s before a byte is read — the
    stream cap is the fallback for bodies that lie or send no header."""
    from fastapi.testclient import TestClient

    from gatekeeper.serve import MAX_BODY, app

    client = TestClient(app)
    r = client.post("/predict/batch", content=b"x" * (MAX_BODY + 1),
                    headers={"content-type": "application/json"})
    assert r.status_code == 413 and "body too large" in r.text


def test_systemone_typed_shape_passthrough_contents():  # T832
    """state/questions must be JSON objects — a string or list used to be
    forwarded raw into the router and died as a 500. Contents stay
    passthrough (the T774 contract): non-list history still reaches the
    router untouched, and explicit null means absent."""
    import gatekeeper
    from gatekeeper import serve

    seen = {}

    class Rec:
        def predict(self, state, questions):
            seen["state"], seen["questions"] = state, questions
            return {"answers": {}}

    gatekeeper._router = Rec()
    try:
        from fastapi.testclient import TestClient
        client = TestClient(serve.app, raise_server_exceptions=False)

        # non-object state/questions: 422 at the door, not a router 500
        for bad in ("oops", ["a"], 7):
            serve._BUCKETS.clear()
            r = client.post("/v1/systemone",
                            json={"state": bad, "questions": {}})
            assert r.status_code == 422, (bad, r.status_code)
            serve._BUCKETS.clear()
            r = client.post("/v1/systemone",
                            json={"state": {}, "questions": bad})
            assert r.status_code == 422, (bad, r.status_code)

        # explicit null == absent (wire compat with SDKs that send nulls)
        serve._BUCKETS.clear()
        r = client.post("/v1/systemone", json={"state": None, "questions": None})
        assert r.status_code == 200 and seen["state"] == {}

        # contents still pass through — the T774 pin, re-asserted here
        serve._BUCKETS.clear()
        client.post("/v1/systemone",
                    json={"state": {"history": "not-a-list"}, "questions": {}})
        assert seen["state"]["history"] == "not-a-list"
    finally:
        gatekeeper._router = None


def test_systemone_safe_path_timeout_retry_breaker():  # T833
    """The passthrough used to call r.predict raw — no timeout, breaker or
    retry. Now: a slow model times out (twice, then coded 503), failures
    feed the breaker, and once it trips the next call short-circuits
    without touching the model. Success closes the circuit again."""
    import os
    import time

    import gatekeeper
    from gatekeeper import serve

    calls = {"n": 0}

    class Slow:
        def predict(self, state, questions):
            calls["n"] += 1
            time.sleep(1.0)  # > the 0.5s floor the timeout is clamped to
            return {"answers": {}}

    gatekeeper._router = Slow()
    os.environ["BOUNCER_TIMEOUT"] = "0.5"
    # fresh breaker state for this test
    gatekeeper._BREAKER.update(fails=0, open_until=0.0, half_open=False)
    try:
        from fastapi.testclient import TestClient
        client = TestClient(serve.app, raise_server_exceptions=False)
        serve._BUCKETS.clear()
        r = client.post("/v1/systemone", json={"state": {}, "questions": {}})
        assert r.status_code == 503, r.text
        assert "E_MODEL" in r.text and "timed out" in r.text
        assert calls["n"] == 2, "timeout must retry exactly once"

        # failures now feed the breaker: trip it (default n=5)
        class Dead:
            def predict(self, state, questions):
                calls["n"] += 1
                raise RuntimeError("model exploded")

        gatekeeper._router = Dead()
        for _ in range(4):
            serve._BUCKETS.clear()
            r = client.post("/v1/systemone", json={"state": {}, "questions": {}})
            assert r.status_code == 503
        assert gatekeeper._BREAKER["fails"] >= 5, "failures must count"

        # breaker open: the next call short-circuits — model untouched
        before = calls["n"]
        serve._BUCKETS.clear()
        r = client.post("/v1/systemone", json={"state": {}, "questions": {}})
        assert r.status_code == 503 and "breaker open" in r.text
        assert calls["n"] == before, "the model was called while open"

        # a success closes the circuit (fresh stub that answers)
        class Good:
            def predict(self, state, questions):
                return {"answers": {"rule": "ok"}}

        gatekeeper._router = Good()
        # wait out half-open transition: cooldown already set — force it
        gatekeeper._BREAKER["open_until"] = 0.0
        gatekeeper._BREAKER["half_open"] = True
        serve._BUCKETS.clear()
        r = client.post("/v1/systemone", json={"state": {}, "questions": {}})
        assert r.status_code == 200 and r.json()["answers"]["rule"] == "ok"
        assert gatekeeper._BREAKER["fails"] == 0, "success must close the breaker"
    finally:
        gatekeeper._router = None
        os.environ.pop("BOUNCER_TIMEOUT", None)
        gatekeeper._BREAKER.update(fails=0, open_until=0.0, half_open=False)


def test_systemone_records_decisions_and_audit(tmp_path, monkeypatch):  # T834
    """The raw path used to be invisible to /stats and the audit log.
    Now every passthrough call is one decision row: action 'passthrough'
    in /stats, a hashed-message line in audit (never the text), and
    failures carry a cause like /predict's fallback rows."""
    import importlib

    import gatekeeper
    import gatekeeper.audit as _au
    from gatekeeper import serve
    from gatekeeper.stats import get_stats

    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BOUNCER_AUDIT", str(audit))
    importlib.reload(_au)

    class Rec:
        def predict(self, state, questions):
            return {"answers": {"rule": "ok"}}

    gatekeeper._router = Rec()
    gatekeeper._BREAKER.update(fails=0, open_until=0.0, half_open=False)
    try:
        from fastapi.testclient import TestClient
        client = TestClient(serve.app, raise_server_exceptions=False)
        before = get_stats()["actions"].get("passthrough", 0)

        # success: counted + one hashed audit row (message never stored)
        serve._BUCKETS.clear()
        r = client.post("/v1/systemone",
                        json={"state": {"message": "secret words here"},
                              "questions": {}})
        assert r.status_code == 200
        assert get_stats()["actions"]["passthrough"] == before + 1
        row = audit.read_text().splitlines()[-1]
        assert "secret words here" not in row  # hashed, like every row (T029)
        import json as _json
        obj = _json.loads(row)
        assert obj["action"] == "passthrough" and obj["msg"]  # hash present

        # failure: 503 + a cause-counted row, breaker fed
        class Dead:
            def predict(self, state, questions):
                raise RuntimeError("dead")

        gatekeeper._router = Dead()
        serve._BUCKETS.clear()
        r = client.post("/v1/systemone", json={"state": {}, "questions": {}})
        assert r.status_code == 503
        stats = get_stats()
        assert stats["causes"].get("model-error", 0) >= 1, stats["causes"]
        obj = _json.loads(audit.read_text().splitlines()[-1])
        assert obj["action"] == "passthrough"  # the failure row lands too
    finally:
        gatekeeper._router = None
        gatekeeper._BREAKER.update(fails=0, open_until=0.0, half_open=False)
        importlib.reload(_au)  # restore the default audit path


def test_unknown_request_fields_are_rejected():  # T835
    """A typo like "thresold" used to be silently dropped — the request
    fell back to defaults and the client never learned. ModReq and
    BatchReq now forbid extras (422 naming the field). The Jev passthrough
    stays permissive on purpose: SDK metadata rides along (T832 contract).
    """
    from fastapi.testclient import TestClient

    from gatekeeper import serve

    client = TestClient(serve.app, raise_server_exceptions=False)
    serve._BUCKETS.clear()
    r = client.post("/predict",
                    json={"message": "hi", "rules": {"r": "t"},
                          "thresold": 0.5})  # the typo
    assert r.status_code == 422, r.text
    assert "thresold" in r.text  # the offender is named, not swallowed

    serve._BUCKETS.clear()
    r = client.post("/predict/batch",
                    json={"messages": ["hi"], "rules": {"r": "t"},
                          "langg": "en"})  # another typo
    assert r.status_code == 422 and "langg" in r.text

    # the passthrough tolerates extra top-level keys — ignored, never a 422
    import gatekeeper

    class Rec:
        def predict(self, state, questions):
            return {"answers": {}}

    gatekeeper._router = Rec()
    try:
        serve._BUCKETS.clear()
        r = client.post("/v1/systemone",
                        json={"state": {}, "questions": {}, "trace_id": "abc"})
        assert r.status_code == 200, r.text  # extras ignored, no 422
    finally:
        gatekeeper._router = None


def test_batch_lang_parity_with_single():  # T836
    """Batch rows used to route as auto no matter what the client said.
    Now BatchReq takes lang (validated like /predict's), a preset autofills
    its pack's language (T502 parity), and both reach the router state as
    lang_hint on every message in the batch."""
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    seen: list[dict] = []

    class Rec:
        def predict(self, state, questions=None, model=None):
            seen.append(dict(state))
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.9,
                         "probabilities": {"ok": 0.9}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    gatekeeper._router = Rec()
    try:
        client = TestClient(serve.app, raise_server_exceptions=False)

        # explicit lang lands in every row's state
        serve._BUCKETS.clear()
        r = client.post("/predict/batch",
                        json={"messages": ["a", "b"], "rules": {"r": "t"},
                              "lang": "es"})
        assert r.status_code == 200, r.text
        assert [s.get("lang_hint") for s in seen] == ["es", "es"]

        # a preset autofills its pack's language (gaming -> en)
        seen.clear()
        serve._BUCKETS.clear()
        r = client.post("/predict/batch",
                        json={"messages": ["a"], "preset": "gaming"})
        assert r.status_code == 200, r.text
        assert seen[0].get("lang_hint") == "en", seen[0]

        # bad hint: same 422 as /predict (T496 shape)
        serve._BUCKETS.clear()
        r = client.post("/predict/batch",
                        json={"messages": ["a"], "rules": {"r": "t"},
                              "lang": "not a slug"})
        assert r.status_code == 422 and "E_LANG" in r.text
    finally:
        gatekeeper._router = None
