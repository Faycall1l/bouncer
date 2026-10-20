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
