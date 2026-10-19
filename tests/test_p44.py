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
