"""P49 tests (T931-T950): observability. All network is stubbed."""
import sys
import time

sys.path.insert(0, "src")

from gatekeeper import serve


def test_t935_metrics_carries_coalesce_and_breaker_detail():
    """T935: /metrics exported only `bouncer_breaker_open` — the fails and
    half_open fields (/stats T522) and the whole coalesce block (/stats
    T754) never reached a scrape. The five series are now integer-valued
    lines beside breaker_open, so an alert can watch fails climbing while
    the breaker sits closed."""
    import json

    from fastapi.testclient import TestClient

    body = TestClient(serve.app).get("/metrics").text
    vals: dict[str, str] = {}
    for line in body.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and not line.startswith("#"):
            vals[parts[0]] = parts[1]
    for name in ("bouncer_breaker_open", "bouncer_breaker_fails",
                 "bouncer_breaker_half_open", "bouncer_coalesce_joined",
                 "bouncer_coalesce_total"):
        assert name in vals, f"{name} missing from:\n{body}"
        int(vals[name])  # every new series is a bare integer — no labels, no floats
    # the scrape mirrors /stats exactly for the same state (one source, two renders)
    stats = json.loads(TestClient(serve.app).get("/stats").text)
    assert int(vals["bouncer_breaker_fails"]) == stats["breaker"]["fails"]
    assert int(vals["bouncer_coalesce_joined"]) == stats["coalesce"]["joined"]
    assert int(vals["bouncer_coalesce_total"]) == stats["coalesce"]["total"]


def test_t936_status_counter_covers_401_413_429():
    """T936: `bouncer_requests_total{status=...}` exists (T885) but only the
    200/404/401 trio was pinned. The three "security" statuses must all
    reach the same series — 413 is raised in the middleware before the body
    is read (T775), 429 inside the route (T841), 401 in the auth gate
    (T885) — so a scrape can alert on probing without log-scraping."""
    from fastapi.testclient import TestClient

    client = TestClient(serve.app)
    orig_key = serve._KEY
    orig_buckets = dict(serve._BUCKETS)
    orig_429 = serve._RATE_429
    serve._KEY, serve._RATE_429 = "", 0

    try:
        # 401: bad key on /predict — needs a key set to be rejectable
        serve._KEY = "secret"
        assert client.post("/predict", json={"message": "hi"},
                           headers={"X-API-Key": "wrong"}).status_code == 401
        serve._KEY = ""
        # 413: oversized POST — rejected by the middleware, body never parsed
        big = b'{"message":"' + b"a" * (serve.MAX_BODY + 10) + b'"}'
        assert client.post("/predict", content=big,
                           headers={"Content-Type": "application/json"}
                           ).status_code == 413
        # 429: pre-stuff this client's bucket past the cap, one more trips it
        # (timestamps must be inside the 60s window or _sweep drops them)
        serve._BUCKETS["testclient"] = [time.time()] * 60
        assert client.post("/predict", json={"message": "hi"}).status_code == 429

        # the three security statuses land on the same series as 200/404
        body = client.get("/metrics").text
        for want in ("401", "413", "429"):
            assert any(line.startswith(f'bouncer_requests_total{{status="{want}"}}')
                       for line in body.splitlines()), (want, body)
        rate = next(line for line in body.splitlines()
                    if line.startswith("bouncer_rate_limited_total "))
        assert float(rate.split()[1]) >= 1
    finally:
        serve._KEY = orig_key
        serve._BUCKETS.clear()
        serve._BUCKETS.update(orig_buckets)
        serve._RATE_429 = orig_429


def test_t939_serve_warns_per_worker_state(capsys):
    """T939: counters/strikes/cache (and therefore /stats + /metrics) are
    per-worker process state — a multi-worker serve silently under-reports
    every scrape. `bouncer serve --workers >1` now says so at startup; a
    warning doctor can never issue (doctor is a separate invocation that
    cannot see serve's flags), so the box's warn lives at serve start."""
    import uvicorn

    from gatekeeper import cli

    orig = uvicorn.run
    uvicorn.run = lambda *a, **k: None  # never actually serve
    try:
        for workers, warned in ((1, False), (3, True)):
            rc = cli.main(["serve", "--workers", str(workers)])
            err = capsys.readouterr().err
            assert rc == 0
            assert ("per-worker" in err) is warned, (workers, err)
    finally:
        uvicorn.run = orig
    # the docs carry the same honest scope
    from pathlib import Path

    assert "under-report" in Path("docs/runbook.md").read_text()


def test_t940_review_queue_depth_in_metrics(tmp_path, monkeypatch):
    """T940: escalations piling up in the review queue were invisible to a
    scrape — the queue depth existed only in `bouncer review` listings.
    `/metrics` now exports `bouncer_review_queue_depth`, counted without
    parsing the rows (they hold raw message text)."""
    from fastapi.testclient import TestClient

    from gatekeeper import review

    qpath = tmp_path / "queue.jsonl"
    monkeypatch.setattr(review, "_PATH", str(qpath))

    def scrape() -> float:
        body = TestClient(serve.app).get("/metrics").text
        line = next(l for l in body.splitlines()
                    if l.startswith("bouncer_review_queue_depth "))
        return float(line.split()[1])

    assert scrape() == 0, "absent file is depth 0, not an error"
    res = {"action": "escalate", "rule": "r", "confidence": 0.4, "cause": "quiet"}
    review.add("msg1", res)
    review.add("msg2", res)
    assert scrape() == 2
    with open(qpath, "a") as f:
        f.write("\n")  # a blank tail line is not a row
    assert scrape() == 2
    review.clear_queue()
    assert scrape() == 0


def test_t941_adapter_counters_reach_the_scrape():
    """T941: T867 records (adapter, action) pairs in stats but only /stats
    showed them. The scrape now carries `bouncer_adapter_decisions_total`
    with both labels — and the series disappears entirely when no adapter
    has recorded (HTTP/CLI decisions are not adapter series, so the label
    set stays bounded by the platform list, not by traffic)."""
    from fastapi.testclient import TestClient

    from gatekeeper.stats import record, reset_stats

    reset_stats()
    try:
        body = TestClient(serve.app).get("/metrics").text
        assert "bouncer_adapter_decisions_total" not in body, body
        record("delete", "no-spam", 3.0, adapter="telegram")
        record("delete", "no-spam", 3.0, adapter="telegram")
        record("flag", "be-kind", 4.0, adapter="discord")
        record("allow", "be-kind", 1.0)  # no adapter: HTTP/CLI, not a series
        body = TestClient(serve.app).get("/metrics").text
        assert ('bouncer_adapter_decisions_total{adapter="telegram",'
                'action="delete"} 2') in body, body
        assert ('bouncer_adapter_decisions_total{adapter="discord",'
                'action="flag"} 1') in body, body
        assert 'adapter=""' not in body, body
    finally:
        reset_stats()
