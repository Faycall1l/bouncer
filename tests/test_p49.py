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
        assert not any(l.startswith("bouncer_adapter_decisions_total{")
                       for l in body.splitlines()), body  # family declared (T943), no samples
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


def test_t942_rule_label_cardinality_stays_capped():
    """T942: rule ids come from the request body (`rules: {"id": "text"}`),
    so /metrics' `bouncer_rule_total{rule=...}` label set was client-sized:
    a flood of fresh ids grew both the scrape and process memory without
    bound. New ids past stats.MAX_RULE_LABELS now fold into one `_other`
    series — every decision still counts, no new label appears."""
    from fastapi.testclient import TestClient

    from gatekeeper import stats
    from gatekeeper.stats import record, reset_stats

    reset_stats()
    try:
        cap = stats.MAX_RULE_LABELS
        record("delete", "spam", 1.0)  # a known id keeps its own series
        for i in range(cap + 50):
            record("allow", f"adversarial-{i}", 1.0)
        body = TestClient(serve.app).get("/metrics").text
        rule_lines = [l for l in body.splitlines()
                      if l.startswith("bouncer_rule_total{")]
        assert len(rule_lines) <= cap + 1, len(rule_lines)  # +1 = _other
        other = next(l for l in rule_lines
                     if 'rule="_other"' in l)
        assert int(other.split()[1]) == 51, other  # 250 fresh - 199 that fit
        assert 'rule="spam"} 1' in body, body
        # a snapshot with the same flood restores under the same cap
        reset_stats()
        stats.restore({"v": 2,
                       "by_rule": {f"stale-{i}": 1 for i in range(cap + 10)}})
        assert len(stats.get_stats()["rules"]) == cap + 1  # folded, not ignored
        assert stats.get_stats()["rules"][stats._OTHER] == 10
    finally:
        reset_stats()


def test_t943_every_scrape_line_parses_and_families_are_complete():
    """T943: the scrape was samples-only — valid text, but Prometheus typed
    every series `untyped`, so rate() over the counters was a silent wrong
    graph. Now every family carries exactly one HELP + one TYPE, and this
    parser (regex, no deps) refuses anything the exposition format forbids:
    unknown directives, bad label syntax, non-numeric or NaN/Inf values,
    a family without metadata, or a TYPE that disagrees with the samples."""
    import re

    from fastapi.testclient import TestClient

    from gatekeeper.stats import record, reset_stats

    reset_stats()
    record("delete", "no-spam", 5.0, cause="violation", adapter="telegram")
    try:
        body = TestClient(serve.app).get("/metrics").text
    finally:
        reset_stats()

    name_re = r"[a-zA-Z_:][a-zA-Z0-9_:]*"
    label_re = r'[a-zA-Z_][a-zA-Z0-9_]*="(?:[^"\\]|\\.)*"'
    sample_re = re.compile(rf"^({name_re})(?:{{{label_re}(?:,{label_re})*}})? "
                           r"(-?[0-9.eE+]+|NaN|[+-]?Inf)$")
    helps: dict[str, str] = {}
    types: dict[str, str] = {}
    samples: dict[str, int] = {}
    for line in body.splitlines():
        if not line.strip():
            continue
        if line.startswith("# HELP "):
            name, _, text = line[len("# HELP "):].partition(" ")
            assert name and text, line
            assert name not in helps, f"duplicate HELP: {line}"
            helps[name] = text
        elif line.startswith("# TYPE "):
            parts = line[len("# TYPE "):].split(" ")
            assert len(parts) == 2 and parts[1] in ("counter", "gauge",
                                                    "histogram", "summary"), line
            assert parts[0] not in types, f"duplicate TYPE: {line}"
            types[parts[0]] = parts[1]
        elif line.startswith("#"):
            raise AssertionError(f"unknown directive: {line}")
        else:
            m = sample_re.match(line)
            assert m, f"unparsable sample line: {line}"
            samples[m.group(1)] = samples.get(m.group(1), 0) + 1
    # every sampled family is fully declared; HELP and TYPE sets agree 1:1
    assert set(samples) <= set(helps) == set(types), (set(samples) - set(helps),
                                                      set(helps) - set(types))
    # a declaration without samples is legitimate only for families that are
    # conditionally empty (no adapter has recorded yet, T941)
    assert set(types) - set(samples) <= {"bouncer_adapter_decisions_total"}
    # counters only ever grow: the type must match the metric's own name contract
    for name, mtype in types.items():
        if name.endswith("_total"):
            assert mtype == "counter", (name, mtype)
    # and the families this batch added are among the declared
    for name in ("bouncer_rule_total", "bouncer_adapter_decisions_total",
                 "bouncer_review_queue_depth", "bouncer_requests_total",
                 "bouncer_breaker_open", "bouncer_coalesce_joined"):
        assert types.get(name) in ("counter", "gauge"), name


def test_t944_scrape_cardinality_bounded_under_adversarial_input():
    """T944: T942 capped the rule-label map, but the scrape is the surface
    that must stay bounded — a Prometheus text parse of the whole body,
    counting total label-sets across every family, after 5k distinct client
    rule ids × 4 actions, fresh rule/status/cause values and a queue flood.
    The bound is a constant, not a function of traffic: label sets ≤ a few
    hundred regardless of how many distinct ids arrive."""
    from fastapi.testclient import TestClient

    from gatekeeper import stats
    from gatekeeper.stats import record, reset_stats

    reset_stats()
    try:
        # 5k distinct ids across every action — each id×action is a fresh
        # potential label-set in rules, decisions and the joint block
        for i in range(5000):
            for act in ("allow", "flag", "delete", "escalate"):
                record(act, f"flood-{i}", 1.0,
                       cause=f"cause-{i % 7}", adapter="telegram")
        body = TestClient(serve.app).get("/metrics").text
        label_sets = sum(1 for l in body.splitlines()
                         if l and not l.startswith("#") and "{" in l)
        # bound: the four known actions + rules under the cap (200+_other)
        # + 7 causes + 4 telegram actions + statuses + the unlabeled singles
        assert label_sets <= 300, label_sets
        # and the map behind it never exceeded the cap
        assert len(stats.get_stats()["rules"]) <= stats.MAX_RULE_LABELS + 1
    finally:
        reset_stats()
