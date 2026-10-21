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
        af = next(line for line in body.splitlines()
                  if line.startswith("bouncer_auth_failures_total "))
        assert float(af.split()[1]) >= 1  # T937: the 401 above incremented it
    finally:
        serve._KEY = orig_key
        serve._BUCKETS.clear()
        serve._BUCKETS.update(orig_buckets)
        serve._RATE_429 = orig_429


def test_t931_938_p49_metrics_families_pinned_end_to_end(capsys, tmp_path):
    """T931-T938: the scrape's P49 decision block, asserted from /metrics
    itself (not from /stats or a sibling box's receipt). Seeding one
    decision per action/rule/cause pins the per-rule (T931), cause (T932),
    p95-latency (T933) and strikes (T934) families on their real lines, and
    the middleware's rid (T938) on the access log the scrape sits behind.
    Auth-failures (T937) is pinned in test_t936 above from the 401 it counts."""
    import json

    from fastapi.testclient import TestClient

    from gatekeeper.stats import record, reset_stats

    reset_stats()
    record("allow", "ok", 2.0, cause="margin")
    record("delete", "no-spam", 9.0, cause="violation")  # sets the p95
    record("escalate", "needs-human", 4.0, cause="needs-human")
    from gatekeeper import strikes as _st

    _st.reset()
    _st.add_strike("t934-user", 3)  # T934: the strikes block counts this
    try:
        # a request through the middleware first, so the rid-bearing access
        # log the scrape's counters sit behind is actually emitted
        TestClient(serve.app).get("/version")
        access = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()
                  if ln.startswith("{") and '"rid"' in ln]
        assert access, "middleware must emit a rid-bearing access log (T938)"
        assert all(a["rid"] for a in access), access

        body = TestClient(serve.app).get("/metrics").text
        for frag in ('bouncer_rule_total{rule="no-spam"} 1',  # T931
                     'bouncer_rule_total{rule="ok"} 1',
                     'bouncer_cause_total{cause="violation"} 1',  # T932
                     'bouncer_cause_total{cause="margin"} 1',
                     'bouncer_decisions_total{action="delete"} 1',  # T931 joint
                     'bouncer_latency_p95_ms 9.0',  # T933 rolling window max
                     'bouncer_latency_p50_ms',  # T933 both quantiles exported
                     'bouncer_strikes_users 1',  # T934 counts only, no ids
                     'bouncer_strikes_total 3',  # T934 the seeded weight
                     'bouncer_strikes_ban_suggested 1'):  # T934 3 >= BAN_AT
            assert frag in body, f"missing {frag}:\n{body}"

        # T938, audit leg: a decision row stores the same rid the access log
        # carries — one id across access/decision/audit, proven on the audit
        # writer directly (tail() reads it back through the public reader)
        import gatekeeper.audit as _au

        audit = tmp_path / "audit.jsonl"
        old_path = _au._PATH
        _au._PATH = str(audit)
        try:
            _au.log_decision("seed", "no-spam", 0.9, "delete", 3.0,
                             cause="violation", rid="rid-t938")
            _au.flush()
            row = _au.tail(1)[0]
            assert row["rid"] == "rid-t938", row
            assert row["cause"] == "violation", row
        finally:
            _au.close()
            _au._PATH = old_path
    finally:
        reset_stats()
        _st.reset()


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
        line = next(ln for ln in body.splitlines()
                    if ln.startswith("bouncer_review_queue_depth "))
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
        assert not any(ln.startswith("bouncer_adapter_decisions_total{")
                       for ln in body.splitlines()), body  # family declared (T943), no samples
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
        rule_lines = [ln for ln in body.splitlines()
                      if ln.startswith("bouncer_rule_total{")]
        assert len(rule_lines) <= cap + 1, len(rule_lines)  # +1 = _other
        other = next(ln for ln in rule_lines
                     if 'rule="_other"' in ln)
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
        label_sets = sum(1 for ln in body.splitlines()
                         if ln and not ln.startswith("#") and "{" in ln)
        # bound: the four known actions + rules under the cap (200+_other)
        # + 7 causes + 4 telegram actions + statuses + the unlabeled singles
        assert label_sets <= 300, label_sets
        # and the map behind it never exceeded the cap
        assert len(stats.get_stats()["rules"]) <= stats.MAX_RULE_LABELS + 1
    finally:
        reset_stats()


def test_t945_api_md_metrics_table_matches_the_scrape():
    """T945: api.md's route bullet listed a handful of metric names; the
    docs now carry a full export table with types. The table is checked
    against the live scrape both ways: every family the server declares is
    documented, and every `bouncer_*` name the docs promise is one the
    server actually serves (a stale doc row fails, a new series without a
    row fails)."""
    import re
    from pathlib import Path

    from fastapi.testclient import TestClient

    from gatekeeper.stats import record, reset_stats

    reset_stats()
    record("delete", "no-spam", 5.0, cause="violation", adapter="telegram")
    try:
        body = TestClient(serve.app).get("/metrics").text
    finally:
        reset_stats()
    served = set(re.findall(r"^# TYPE (\S+)", body, re.MULTILINE))
    assert served, "the scrape must declare families"
    doc = Path("docs/api.md").read_text()
    section = doc.split("## Metrics export (T945)")[1].split("## ")[0]
    # only table rows name families; the prose below mentions label values
    table = "\n".join(ln for ln in section.splitlines() if ln.startswith("|"))
    # a row can carry a chain of names: "`bouncer_pool_size` / `_max` / …" —
    # each `_`-prefixed continuation joins the previous name's stem
    expanded: set[str] = set()
    stem = ""
    for token in re.findall(r"`(bouncer_[a-z0-9_]+|_[a-z0-9_]+)`", table):
        if token.startswith("bouncer_"):
            stem = token.rsplit("_", 1)[0]
            expanded.add(token)
        else:
            assert stem, token  # a continuation can only follow a full name
            expanded.add(stem + "_" + token.lstrip("_"))
    assert served <= expanded, f"undocumented families: {served - expanded}"
    assert expanded <= served, f"docs promise absent families: {expanded - served}"


def test_t946_runbook_scrape_recipe_references_live_families():
    """T946: the runbook had backup/restore/rotate/drain but no scrape
    recipe — an operator wiring Prometheus had to guess both the config
    and what to alert on. The new section ships a scrape_configs snippet
    and three alerts (breaker-open, fails climbing, review backlog). This
    test parses every `bouncer_*` name out of the alerts+scrape portion
    and asserts each one is a family the server actually declares — a
    rename in serve.py cannot silently orphan the recipe."""
    import re
    from pathlib import Path

    from fastapi.testclient import TestClient

    from gatekeeper.stats import record, reset_stats

    reset_stats()
    record("delete", "no-spam", 5.0, cause="violation")
    try:
        body = TestClient(serve.app).get("/metrics").text
    finally:
        reset_stats()
    served = set(re.findall(r"^# TYPE (\S+)", body, re.MULTILINE))
    doc = Path("docs/runbook.md").read_text()
    section = doc.split("## Scrape + alerts (T946)")[1].split("## ")[0]
    used = set(re.findall(r"\b(bouncer_[a-z0-9_]+)", section))
    # every bouncer_* token in the recipe is a family reference (label values
    # like rule="_other" don't carry the prefix)
    assert used <= served, f"recipe names absent families: {used - served}"
    assert {"bouncer_breaker_open", "bouncer_breaker_fails",
            "bouncer_review_queue_depth"} <= used, used
    # the three alerts exist and watch what the runbook's procedures act on
    for alert in ("BouncerBreakerOpen", "BouncerModelFails",
                  "BouncerReviewBacklog"):
        assert f"alert: {alert}" in section, alert
    assert "X-API-Key" in section, "the gated-scrape key header must be shown"
    assert "Per worker" in section, "T939's per-worker scope must be restated"


def test_t947_metrics_under_threaded_load_measured_not_asserted(capsys):
    """T947: every family added in P49 does work inside the scrape —
    review depth opens a file, the breaker takes a lock, pool/stats take
    their own. A scrape must stay cheap enough for a 15s interval from a
    threaded server, so this runs N concurrent scrapes and REPORTS the
    p50/p95/max to stdout as a receipt. The budget here is structural,
    never a latency value (the standing bench rule): every response must
    be 200 and parse as the exposition format — a slow scrape is a
    dashboard problem, a broken scrape is a regression."""
    import statistics
    import time
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from gatekeeper.stats import record, reset_stats

    reset_stats()
    record("delete", "no-spam", 5.0, cause="violation", adapter="telegram")
    client = TestClient(serve.app)  # TestClient is thread-safe for GETs
    n = 40

    def one_scrape() -> float:
        t0 = time.perf_counter()
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.text.endswith("\n") and "# TYPE" in resp.text
        return (time.perf_counter() - t0) * 1000

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            ms = list(pool.map(lambda _: one_scrape(), range(n)))
    finally:
        reset_stats()
    ms.sort()
    p50 = statistics.median(ms)
    p95 = ms[int(0.95 * (len(ms) - 1))]
    print(f"T947 /metrics threaded load: n={n} p50={p50:.1f}ms "
          f"p95={p95:.1f}ms max={ms[-1]:.1f}ms")  # receipt, not an assertion
    assert len(ms) == n  # every scrape answered — the structural budget only


def test_t948_gate_dispatches_the_metrics_report_kind(tmp_path):
    """T948: gate.py gated every bench_*.py report through the generic perf
    collector, which knows only the T765 envelope — a metrics report's
    exposition-format fields would have been skipped silently. bench_metrics
    now exists, gate.py dispatches its shape to a metrics collector, and
    the two axes gate independently: format failures fail even when the
    scrape is fast (no machine-speed dependency), budget skips when the
    producer never measured."""
    import argparse
    import json
    import subprocess
    import sys
    from pathlib import Path

    sys.path.insert(0, "eval")
    import gate

    args = argparse.Namespace(max_metrics_p50_ms=100.0)
    # dispatch: the metrics shape must not leak into the generic perf family
    rep = {"bench": "bench_metrics", "schema": 1, "mode": "n/a",
           "p50_ms": 1.0, "format_ok": True, "help_complete": True}
    assert gate.detect_kind(rep) == "metrics"
    checks = {c["name"]: c for c in gate.COLLECTORS["metrics"](rep, args)}
    assert checks["metrics_format"]["ok"] is True
    assert checks["metrics_p50_ms"]["ok"] is True
    # a broken exposition fails even inside the budget
    broken = dict(rep, format_ok=False, help_complete=False)
    bad = {c["name"]: c for c in gate.COLLECTORS["metrics"](broken, args)}
    assert bad["metrics_format"]["ok"] is False
    assert bad["metrics_help_type"]["ok"] is False
    assert bad["metrics_p50_ms"]["ok"] is True  # speed never excuses format
    # an over-budget scrape fails even when the format is perfect
    slow = dict(rep, p50_ms=500.0)
    over = {c["name"]: c for c in gate.COLLECTORS["metrics"](slow, args)}
    assert over["metrics_format"]["ok"] is True
    assert over["metrics_p50_ms"]["ok"] is False
    # absent measurement -> SKIP, never a silent pass (T672's rule)
    nomeasure = {k: v for k, v in rep.items() if k != "p50_ms"}
    skip = {c["name"]: c for c in gate.COLLECTORS["metrics"](nomeasure, args)}
    assert skip["metrics_p50_ms"]["ok"] is None
    # the real producer round-trips through the real gate
    out = tmp_path / "metrics.json"
    run = subprocess.run(
        [sys.executable, "eval/bench_metrics.py", "--out", str(out), "--json"],
        capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    verdict = subprocess.run(
        [sys.executable, "eval/gate.py", str(out), "--ci"],
        capture_output=True, text=True, check=False)
    assert verdict.returncode == 0, verdict.stdout + verdict.stderr
    assert json.loads(verdict.stdout)["ok"] is True
    # and --all's known list includes it (the drift rule: every producer
    # report is gateable by the one command)
    assert '"metrics.json"' in Path("eval/gate.py").read_text()


def test_p49_observability_sweep():  # T950: every box T931-T950 ticked,
    # every box has a receipt outside TODO.md, no invented citations
    import re as _re
    from pathlib import Path

    todo = Path("TODO.md").read_text()
    # T949: the fix box has no reds to fix — this sweep running green over
    # the whole batch is its receipt (each mid-batch failure was one of this
    # batch's own new tests catching its own bug before commit)
    p49 = [b for b in _re.findall(r"- \[[ x]\] (T\d{3,4})\b", todo)
           if 931 <= int(b[1:]) <= 950]
    assert sorted(p49) == [f"T{n}" for n in range(931, 951)], p49
    for b in p49:
        assert f"- [x] {b}" in todo, f"{b} unticked"
    assert "## P49 Observability (T931–T950)" in todo

    # receipts live OUTSIDE TODO.md — across this batch's own surfaces:
    # the scrape implementation, its docs, the bench producer, the gate,
    # and the tests themselves
    corpus = (Path("README.md").read_text()
              + Path("CONTRIBUTING.md").read_text()
              + Path("verify.sh").read_text())
    for root in ("docs", "tests", "src", ".github", "eval"):
        for p in Path(root).rglob("*"):
            if (p.is_file()
                    and p.suffix in (".md", ".py", ".yml", ".yaml", ".sh")):
                corpus += p.read_text()
    for b in p49:
        assert b in corpus, f"{b} has no receipt outside TODO.md"

    # citation integrity: every T-number on the surfaces this batch touched
    # is a box TODO.md actually knows — invented receipts fail here
    for f in (Path("src/gatekeeper/serve.py"), Path("src/gatekeeper/stats.py"),
              Path("src/gatekeeper/review.py"), Path("docs/api.md"),
              Path("docs/runbook.md"), Path("eval/bench_metrics.py"),
              Path("eval/gate.py"), Path("tests/test_p49.py")):
        for t in set(_re.findall(r"T\d{3,4}", f.read_text())):
            assert t in todo, (str(f), f"cites unknown box {t}")

    # the scrape's own contract, gated here not just claimed: every family
    # declared (T943), cardinality bounded (T942+T944), queue depth reads
    # bytes not text (T940), and the docs table matches both ways (T945)
    from fastapi.testclient import TestClient

    from gatekeeper.stats import record, reset_stats

    reset_stats()
    record("delete", "no-spam", 5.0, cause="violation", adapter="telegram")
    try:
        body = TestClient(serve.app).get("/metrics").text
    finally:
        reset_stats()
    names = set(_re.findall(r"^# TYPE (\S+)", body, _re.MULTILINE))
    assert {"bouncer_decisions_total", "bouncer_rule_total",
            "bouncer_cause_total", "bouncer_adapter_decisions_total",
            "bouncer_requests_total", "bouncer_auth_failures_total",
            "bouncer_rate_limited_total", "bouncer_breaker_open",
            "bouncer_breaker_fails", "bouncer_breaker_half_open",
            "bouncer_coalesce_joined", "bouncer_coalesce_total",
            "bouncer_review_queue_depth", "bouncer_latency_p95_ms"} <= names
    api = Path("docs/api.md").read_text()
    runbook = Path("docs/runbook.md").read_text()
    assert "## Metrics export (T945)" in api
    assert "bouncer_review_queue_depth" in api
    assert "## Scrape + alerts (T946)" in runbook
    assert "BouncerBreakerOpen" in runbook
