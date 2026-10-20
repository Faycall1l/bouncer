"""P49 tests (T931-T950): observability. All network is stubbed."""
import sys

sys.path.insert(0, "src")

from gatekeeper import serve


def test_t935_metrics_carries_coalesce_and_breaker_detail():
    """T935: /metrics exported only `bouncer_breaker_open` — the fails and
    half_open fields (/stats T522) and the whole coalesce block (/stats
    T754) never reached a scrape. The five series are now integer-valued
    lines beside breaker_open, so an alert can watch fails climbing while
    the breaker sits closed."""
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
    import json

    stats = json.loads(TestClient(serve.app).get("/stats").text)
    assert int(vals["bouncer_breaker_fails"]) == stats["breaker"]["fails"]
    assert int(vals["bouncer_coalesce_joined"]) == stats["coalesce"]["joined"]
    assert int(vals["bouncer_coalesce_total"]) == stats["coalesce"]["total"]
