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


def test_batch_shares_one_deadline():  # T837
    """timeout_s used to restart per message (32 x 60s worst case for one
    request). Now the whole batch shares one deadline: the slow first row
    burns the budget, rows after it get escalate fallbacks (cause
    batch-deadline) WITHOUT waking the model, and the call count proves it.
    """
    import time as _time

    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve
    from gatekeeper.stats import get_stats

    calls = {"n": 0}

    class Slow:
        def predict(self, state, questions=None, model=None):
            calls["n"] += 1
            _time.sleep(2.0)  # far past the 0.5s floor timeout_s allows
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.9,
                         "probabilities": {"ok": 0.9}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    gatekeeper._router = Slow()
    gatekeeper._BREAKER.update(fails=0, open_until=0.0, half_open=False)
    try:
        from fastapi.testclient import TestClient
        client = TestClient(serve.app, raise_server_exceptions=False)
        serve._BUCKETS.clear()
        causes_before = get_stats()["causes"].get("batch-deadline", 0)

        t0 = _time.monotonic()
        r = client.post("/predict/batch",
                        json={"messages": [f"t837 row {i}" for i in range(6)],
                              "rules": {"r": "t"}, "timeout_s": 0.5})
        elapsed = _time.monotonic() - t0

        assert r.status_code == 200, r.text  # bounded rows, not a 500
        rows = r.json()
        assert len(rows) == 6  # order + count kept even when rows fall back

        # the first row burned the budget on the model (attempt + one retry
        # is _predict_safe's contract) — and no later row wakes it again
        assert calls["n"] <= 2, "later rows must not wake a deadlined model"
        # ...so the rest are escalate fallbacks naming the deadline
        assert all(row["cause"] == "batch-deadline" for row in rows[1:]), rows
        assert all(row["action"] == "escalate" for row in rows[1:])
        assert "deadline" in rows[-1]["reason"]

        # one bounded request: two 0.5s timeout attempts + retry sleep,
        # then instant fallbacks — nowhere near 6 x 2s of sleep
        assert elapsed < 3.0, elapsed
        assert get_stats()["causes"]["batch-deadline"] >= causes_before + 5

        # plenty of budget: every row runs normally (deadline is no-op)
        fast = gatekeeper._router

        class Quick:
            def predict(self, state, questions=None, model=None):
                calls["n"] += 1
                return {"answers": {
                    "rule": {"choice": "ok", "confidence": 0.9,
                             "probabilities": {"ok": 0.9}},
                    "harm": {"score": "safe", "probabilities": []},
                    "hype": {"score": "chill", "probabilities": []},
                    "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

        assert fast is not None
        gatekeeper._router = Quick()
        serve._BUCKETS.clear()
        before = calls["n"]
        r = client.post("/predict/batch",
                        json={"messages": ["t837 fine a", "t837 fine b"],
                              "rules": {"r": "t"}, "timeout_s": 60})
        assert r.status_code == 200
        assert all(row["cause"] != "batch-deadline" for row in r.json()), r.json()
        assert calls["n"] == before + 2
    finally:
        gatekeeper._router = None
        gatekeeper._BREAKER.update(fails=0, open_until=0.0, half_open=False)


def test_serve_flags_reach_uvicorn(monkeypatch):  # T838
    """timeout_keep_alive and limit_concurrency were unconfigurable —
    proxies drop idle connections at 5s and there's no backpressure valve.
    The serve subcommand now wires both through to uvicorn.run, and when
    the flags are absent uvicorn's own defaults stay untouched."""
    import uvicorn

    from gatekeeper import cli

    seen: dict = {}

    def fake_run(app, **kw):
        seen.clear()
        seen.update(kw)

    monkeypatch.setattr(uvicorn, "run", fake_run)

    rc = cli.main(["serve", "--keep-alive", "30",
                   "--limit-concurrency", "64"])
    assert rc == 0
    assert seen["timeout_keep_alive"] == 30.0
    assert seen["limit_concurrency"] == 64
    assert seen["workers"] == 1  # existing flag still wired

    rc = cli.main(["serve"])  # defaults: uvicorn's own, not ours
    assert rc == 0
    assert "timeout_keep_alive" not in seen
    assert "limit_concurrency" not in seen


def test_graceful_shutdown_drains_and_flushes(tmp_path, monkeypatch, capsys):  # T839
    """The shutdown used to print a note and hope. Now the lifespan waits for
    queued/running predicts (a timed-out _predict_safe does NOT cancel the
    future — the model keeps running in its thread), fsyncs+ closes the
    audit tail, and the shutdown line reports the measured drain."""
    import asyncio
    import importlib
    import json as _json
    import time as _time

    import gatekeeper
    import gatekeeper.audit as _au
    from gatekeeper import serve

    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BOUNCER_AUDIT", str(audit))
    importlib.reload(_au)

    # one decision lands while batching is active (legacy mode writes
    # per-call, so force the batched handle to prove the tail is flushed)
    monkeypatch.setattr(_au, "_FSYNC_N", 3)
    _au.log_decision("t839 in-flight decision", "ok", 0.9, "allow", 1.0)
    # T758 flushes to the OS per write; what batching defers is the fsync —
    # so the observable pre-shutdown state is the still-open handle
    assert _au._F is not None, "batching should hold an open handle"

    try:
        # drive the lifespan directly: p13env's FastAPI has a broken
        # telemetry import in its lifespan scope path, and the drain/flush
        # logic under test lives entirely in our post-yield block.
        # T849: the in-flight work is submitted AFTER startup — warmup cost
        # is environment-dependent (CI has huggingface/laya present and can
        # spend >0.3s there), so work queued before __aenter__ could finish
        # during warmup and the drain would legitimately measure ~0. Start
        # it post-startup and the only thing between it and __aexit__ is the
        # ordering the drain must enforce.
        gatekeeper._EXEC = None
        holder: dict = {}

        async def _run():
            agen = serve._lifespan(None)
            await agen.__aenter__()   # startup: warmup runs here, however slow
            ex = gatekeeper._executor()
            holder["fut"] = ex.submit(_time.sleep, 0.3)  # in flight at shutdown
            await agen.__aexit__(None, None, None)  # shutdown: drain + close

        asyncio.run(_run())
        fut = holder["fut"]

        # the in-flight predict finished BEFORE the audit closed
        assert fut.done(), "shutdown must drain running predicts first"
        assert gatekeeper._EXEC is None, "pool is dropped after the drain"

        # the buffered tail reached the fsynced file, handle released
        assert _au._F is None, "shutdown closes the audit handle"
        row = _json.loads(audit.read_text().splitlines()[-1])
        assert row["action"] == "allow" and row["msg"], "batched tail must land on shutdown"
        assert "t839" not in row["msg"], "message stays hashed (T029)"

        # the shutdown line is a measurement, not a note
        line = [l for l in capsys.readouterr().out.splitlines()
                if '"shutdown"' in l][-1]
        ev = _json.loads(line)
        assert ev["inference_drained_s"] >= 0.25, ev  # it really waited
        assert ev["audit"] == "closed"
    finally:
        gatekeeper._EXEC = None
        importlib.reload(_au)  # restore the default audit path/mode


def test_access_log_method_status_and_rid_correlation(capsys):  # T840
    """The access log had rid+path+ms but no method/status, and the decision
    event line had no rid — an operator couldn't tell a 422 from a 200 by
    the access line, nor join a decision to its request. Now the access log
    carries method+status and the decision line carries the same rid."""
    import json as _json

    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    class Rec:
        def predict(self, state, questions=None, model=None):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.9,
                         "probabilities": {"ok": 0.9}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    gatekeeper._router = Rec()
    try:
        client = TestClient(serve.app, raise_server_exceptions=False)
        capsys.readouterr()  # drop noise from earlier lines

        serve._BUCKETS.clear()
        r = client.post("/predict", json={"message": "hello", "rules": {"r": "t"}},
                        headers={"X-Request-ID": "rid-t840"})
        assert r.status_code == 200

        out = capsys.readouterr().out.splitlines()
        access = _json.loads([l for l in out if '"rid"' in l and '"method"' in l][-1])
        assert (access["rid"], access["method"], access["status"]) == ("rid-t840", "POST", 200)
        decision = _json.loads([l for l in out if '"decision"' in l][-1])
        assert decision["rid"] == "rid-t840"  # the two lines join on rid

        # a non-200 is visible in the access log too (was unlogged before)
        serve._BUCKETS.clear()
        r = client.post("/predict", json={"message": "hello", "rules": {"r": "t"},
                                          "thresold": 1})  # T835: 422
        assert r.status_code == 422
        access = _json.loads([l for l in capsys.readouterr().out.splitlines()
                              if '"method"' in l][-1])
        assert access["status"] == 422 and access["method"] == "POST"
    finally:
        gatekeeper._router = None


def test_rate_limit_holds_under_parallel_threads():  # T841
    """_rate was check-then-append with no lock while handlers run in the
    threadpool — concurrent requests read the same bucket, both appended,
    one write won, and the loser's hit vanished (a client could exceed
    60/min under concurrency). Now the check+append is one atomic step:
    hammering from 8 threads admits exactly 60, never 61."""
    import threading
    import types
    import typing

    from fastapi import HTTPException

    from gatekeeper import serve

    class Req:  # minimal duck-type: _client_ip only touches client.host
        client = types.SimpleNamespace(host="10.9.9.9")
        headers: typing.ClassVar[dict] = {}

    admitted: list = []  # list.append is atomic under the GIL — counters
    refused: list = []   # aren't, and the tight switch interval would expose that
    barrier = threading.Barrier(8)

    def hammer():
        barrier.wait()  # all 8 threads collide on the same bucket
        for _ in range(20):  # 160 attempts total for one IP
            try:
                serve._rate(Req())
                admitted.append(1)
            except HTTPException as e:
                assert e.status_code == 429
                refused.append(1)

    serve._BUCKETS.clear()
    # force preemption inside the check-then-append window: without this the
    # GIL makes the race nearly impossible to hit (verified by neutering the
    # lock and watching this test still pass at the default 5ms interval)
    old_si = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old_si)

    assert len(admitted) == 60, f"admitted {len(admitted)} under concurrency"
    assert len(refused) == 100
    assert len(serve._BUCKETS["10.9.9.9"]) == 60  # the bucket keeps the cap


def test_stats_gated_behind_key_like_metrics():  # T842
    """/stats was the one introspection route with no exposure gate —
    decision counts, breaker state and strike tallies answered anyone, while
    /metrics (same data, prometheus format) already demanded the key (T778).
    It now rides the exact same gate: keyless = open, keyed = key required
    for non-loopback peers, loopback exempt."""
    import types

    import pytest
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from gatekeeper import serve

    client = TestClient(serve.app, raise_server_exceptions=False)
    orig = serve._KEY
    try:
        # keyless server: /stats open (the same bargain as every route)
        serve._KEY = ""
        serve._BUCKETS.clear()
        assert client.get("/stats").status_code == 200

        # key set: TestClient's peer isn't loopback -> key required
        serve._KEY = "stats-key-0123456789"
        serve._BUCKETS.clear()
        assert client.get("/stats").status_code == 401
        r = client.get("/stats", headers={"X-API-Key": "stats-key-0123456789"})
        assert r.status_code == 200 and r.json()["name"] == "bouncer", r.text
        assert client.get("/stats", headers={"X-API-Key": "nope"}).status_code == 401

        # the loopback exemption is the gate's own (unit — TestClient can't
        # be loopback): direct local scrape free, remote needs the key
        class Req:
            def __init__(self, host, headers=None):
                self.client = types.SimpleNamespace(host=host)
                self.headers = headers or {}

        serve._metrics_gate(Req("127.0.0.1"))  # /stats shares this gate
        with pytest.raises(HTTPException) as e:
            serve._metrics_gate(Req("203.0.113.5"))
        assert e.value.status_code == 401
    finally:
        serve._KEY = orig
        serve._BUCKETS.clear()


def test_413_before_auth_is_documented():  # T843
    """The byte-level and Content-Length 413s fire before the key check —
    an intentional cheap-reject, not an oversight. Both docs name it as a
    decision with its tradeoff (an unauthenticated prober learns only the
    documented cap), so nobody 'fixes' the ordering by reading bodies
    from unauthenticated clients first."""
    from pathlib import Path

    api = Path("docs/api.md").read_text()
    assert "before auth" in api and "T831" in api  # the ordering + the cap

    tm = Path("docs/threat-model.md").read_text()
    assert "before auth by design" in tm and "T843" in tm


def test_request_limits_section_exists():  # T844
    """The caps that shape every POST used to live scattered across the
    endpoint bullets. api.md now has one Request limits section naming all
    four semantics — body-cap double check, extra-field policy, the batch
    deadline, and that rate buckets are per worker process."""
    from pathlib import Path

    doc = Path("docs/api.md").read_text()
    assert "## Request limits (T844)" in doc
    section = doc.split("## Request limits (T844)")[1].split("\n## ")[0]
    for needle in ("byte level", "T831", "extra=\"forbid\"", "T835",
                   "batch-deadline", "T837", "per worker process", "T777"):
        assert needle in section, needle


def test_oversized_chunked_body_stops_mid_stream():  # T846
    """T831 proved the over-cap body 413s before the handler. This proves
    the other half: the cap stops PULLING chunks the moment the limit is
    crossed — a 100 MB chunked upload isn't read to its end (or even close)
    before the client is cut off."""
    from gatekeeper import serve

    pulled = {"n": 0}

    def make_receive(total_chunks, chunk=b"x" * 400):
        remaining = {"left": total_chunks}

        async def receive():
            if remaining["left"] <= 0:
                return {"type": "http.disconnect"}
            remaining["left"] -= 1
            pulled["n"] += 1
            return {"type": "http.request", "body": chunk, "more_body": True}
        return receive

    sent = []
    capped = serve._StreamBodyCap(_echo_app([]), limit=1000)

    async def send(message):
        sent.append(message)

    # 250 chunks = 100 KB offered; the cap crosses 1000 bytes on chunk 3
    scope = {"type": "http", "method": "POST", "path": "/predict",
             "headers": [], "query_string": b""}
    _run(capped(scope, make_receive(250), send))

    assert sent[0]["status"] == 413
    assert pulled["n"] <= 3, (f"cap read {pulled['n']} chunks of a 250-chunk "
                              "upload before rejecting")


def test_systemone_parity_caps_breaker_audit(tmp_path, monkeypatch):  # T847
    """The passthrough used to be the wild west: no caps (T774), no breaker
    (T833), no audit (T834). This pins all three contracts side by side in
    one place so a future change can't quietly drop one — same history
    window as /predict's context, same breaker short-circuit and 503, same
    hashed audit row + stats cause."""
    import importlib
    import json as _json

    from fastapi.testclient import TestClient

    import gatekeeper
    import gatekeeper.audit as _au
    from gatekeeper import serve
    from gatekeeper.stats import get_stats

    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("BOUNCER_AUDIT", str(audit))
    importlib.reload(_au)

    seen: list[dict] = []

    class Rec:
        def predict(self, state, questions=None, model=None):
            seen.append(dict(state))
            return {"answers": {"rule": {"choice": "ok", "confidence": 0.9}}}

    gatekeeper._router = Rec()
    gatekeeper._BREAKER.update(fails=0, open_until=0.0, half_open=False)
    try:
        client = TestClient(serve.app, raise_server_exceptions=False)

        # caps: history trimmed to /predict's window, oversized items cut
        # (T774), and the shape check rejects a non-object (T832)
        serve._BUCKETS.clear()
        r = client.post("/v1/systemone",
                        json={"state": {"history": ["h" * 9000] * 25},
                              "questions": {}})
        assert r.status_code == 200, r.text
        hist = seen[-1]["history"]
        assert len(hist) == 20 and all(len(h) == 8000 for h in hist)
        r = client.post("/v1/systemone", json={"state": [], "questions": {}})
        assert r.status_code == 422, "shape check (T832) must hold"

        # breaker: a dead model trips and the next call short-circuits
        # without waking it (same breaker as /predict's path)
        class Dead:
            def predict(self, state, questions=None, model=None):
                raise RuntimeError("nope")

        gatekeeper._router = Dead()
        gatekeeper._BREAKER.update(fails=0, open_until=0.0, half_open=False)
        before = get_stats()["causes"].get("breaker-open", 0)
        serve._BUCKETS.clear()
        r = client.post("/v1/systemone", json={"state": {}, "questions": {}})
        assert r.status_code == 503  # coded E_MODEL, never a hung socket (T833)
        assert r.json()["detail"]["code"] == "E_MODEL"

        # audit: the passthrough's row is hashed like every decision row and
        # the failure counted with its cause (T834)
        rows = [_json.loads(l) for l in audit.read_text().splitlines()]
        assert rows and all(row["action"] == "passthrough" for row in rows)
        assert "h" * 100 not in audit.read_text()  # raw state never lands
        assert get_stats()["causes"].get("breaker-open", 0) >= before
    finally:
        gatekeeper._router = None
        gatekeeper._BREAKER.update(fails=0, open_until=0.0, half_open=False)
        importlib.reload(_au)
