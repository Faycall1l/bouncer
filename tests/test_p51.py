"""P51 tests: security refresh (T971–T990)."""
# Apache-2.0. See LICENSE.

import inspect
import json
from pathlib import Path


def test_t973_adjudicate_is_operator_only_cli(monkeypatch, tmp_path):  # T973
    """T973: the appeal path answers, the operator decides. Pin, not hope:
    serve.py exposes no adjudicate/amnesty route (checked against the live
    app.routes, not just the source), no adapter wires user input to the
    mutating review.adjudicate / strikes.amnesty — the platform-facing
    `appeal` command only RENDERS the user's newest queue row through
    appeal_reply (read-only, T864) — and the only entry points are the
    CLI's cmd_adjudicate (T865) and cmd_amnesty (T881). A platform user
    can ask; only the operator can decide."""
    from gatekeeper import review as rv
    from gatekeeper import serve

    # 1. no HTTP surface at all: route paths never mention adjudication
    paths = [r.path for r in serve.app.routes]
    for word in ("adjudicat", "amnesty", "verdict", "approve"):
        assert not any(word in p for p in paths), (word, paths)

    # 2. the source has no hidden wiring either
    src = inspect.getsource(serve)
    assert "adjudicate" not in src and "amnesty" not in src

    # 3. adapters can neither adjudicate nor amnesty; their `appeal`
    #    command answers via appeal_reply only
    adp = Path("src/gatekeeper/adapters")
    for p in sorted(adp.glob("*.py")):
        text = p.read_text()
        assert "adjudicate" not in text, p.name
        assert "strikes.amnesty" not in text, p.name
    common = (adp / "common.py").read_text()
    assert "appeal_reply" in common  # the read-only renderer (T864)

    # 4. mutating entry points are CLI-only
    cli = Path("src/gatekeeper/cli.py").read_text()
    assert "def cmd_adjudicate" in cli and "def cmd_amnesty" in cli

    # 5. functional: appeal_reply renders without mutating the queue row
    q = str(tmp_path / "t973-q.jsonl")
    monkeypatch.setattr(rv, "_PATH", q)
    row = {"t": 1, "id": "ab12cd34", "user": "telegram:42",
           "message": "hello", "action": "review", "rule": "r1",
           "conf": 0.9, "cause": "", "model": "", "preset": ""}
    with open(q, "w") as f:
        f.write(json.dumps(row) + "\n")
    reply = rv.appeal_reply("telegram:42", {"rules": []})
    assert "ab12cd34" in reply  # the row id links the appeal to adjudication
    after = json.loads(Path(q).read_text().splitlines()[0])
    assert "verdict" not in after and "vt" not in after, after
    assert after == row  # byte-identical: rendering changed nothing


def test_t974_amnesty_operator_only_and_audited(monkeypatch, tmp_path):  # T974
    """T974: strike forgiveness is operator-only and leaves evidence. The
    mutating amnesty exists only on the CLI — no HTTP route, no adapter
    mentions it — and a successful run writes exactly one audit row:
    who = the subject as the standard 16-hex hash (the audit log stays
    hash-only, T029/T883 — plaintext user ids live only in the 0600
    strikes table), when = the row's `t`, why = the applied weight and
    the before->after count in `cause`. The adjudicate-reject path was
    already recorded in-row (verdict/vt/after, T865); this row closes
    the standalone CLI path (T881)."""
    import hashlib
    import importlib
    import inspect

    from gatekeeper import audit as _au
    from gatekeeper import serve
    from gatekeeper import strikes as _st
    from gatekeeper.cli import main

    # operator-only: no route, no source wiring, no adapter command
    assert not any("amnesty" in r.path for r in serve.app.routes)
    assert "amnesty" not in inspect.getsource(serve)
    for p in sorted(Path("src/gatekeeper/adapters").glob("*.py")):
        assert "amnesty" not in p.read_text(), p.name

    # functional: amnesty leaves one hash-only row with who/when/why
    _st.reset()
    _st.add_strike("u1")       # 3 strikes accrued in total
    _st.add_strike("u1")
    _st.add_strike("u1")
    monkeypatch.setattr(_st, "_PATH", str(tmp_path / "strikes.json"))
    monkeypatch.setenv("BOUNCER_AUDIT", str(tmp_path / "audit.jsonl"))
    importlib.reload(_au)
    try:
        assert main(["amnesty", "u1", "--weight", "2"]) == 0
        lines = (tmp_path / "audit.jsonl").read_text().splitlines()
        assert len(lines) == 1, lines
        row = json.loads(lines[0])
        assert row["action"] == "amnesty" and row["rule"] == "amnesty"
        assert row["cause"] == "weight=2 strikes 3->1", row["cause"]
        assert row["t"] > 0  # when: the row's own timestamp
        digest = hashlib.sha256(b"amnesty u1").hexdigest()[:16]
        assert row["msg"] == digest  # who, hashed like every other row
        assert "u1" not in lines[0]  # plaintext user never reaches the audit

        # no effect, no row: a no-strikes amnesty exits 1, logs nothing
        assert main(["amnesty", "nobody"]) == 1
        assert len((tmp_path / "audit.jsonl").read_text().splitlines()) == 1
    finally:
        if _au._F:
            _au._F.close()
        importlib.reload(_au)  # restore the default audit path


def test_t975_systemone_oversized_values_still_refused():  # T975
    """T975: regression pin on the typed systemone door (T832/T774/T775).
    Oversized values are refused at the wire, never forwarded: dict keys
    past MAX_KEY at either top level -> 422 E_STATE (a key can't be
    trimmed coherently), non-object state/questions -> 422 from the
    pydantic shape (not a forwarded 500), bodies past MAX_BODY -> 413
    before parsing. The two values the passthrough deliberately TRIMS
    still trim — history items to MAX_ITEM and the list to the newest
    MAX_CONTEXT (raw-path precedent, structured /predict rejects the
    same bound) — so any future change to these six behaviors is a
    deliberate one, caught here first."""
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    seen: dict = {}

    class Rec:
        def predict(self, state, questions):
            seen["state"] = state
            return {"answers": {}}

    gatekeeper._router = Rec()
    client = TestClient(serve.app, raise_server_exceptions=False)

    def post(payload=None, **kw):
        serve._BUCKETS.clear()
        return client.post("/v1/systemone", json=payload, **kw)

    # refused: oversized keys at both top levels; exactly MAX_KEY passes
    r = post({"state": {"k" * (serve.MAX_KEY + 1): "v"}, "questions": {}})
    assert r.status_code == 422 and "E_STATE" in r.text, r.text
    r = post({"state": {}, "questions": {"q" * (serve.MAX_KEY + 1): {}}})
    assert r.status_code == 422 and "E_STATE" in r.text, r.text
    r = post({"state": {"k" * serve.MAX_KEY: "v"}, "questions": {}})
    assert r.status_code == 200, r.text

    # refused: non-object shapes die at the typed door (T832); explicit
    # null/absent stays the documented "no state" (200)
    for bad in ("oops", ["x"], 5):
        r = post({"state": bad, "questions": {}})
        assert r.status_code == 422, (bad, r.status_code, r.text)
    r = post({"state": {}, "questions": "oops"})
    assert r.status_code == 422, r.text
    assert post({"state": None}).status_code == 200

    # trimmed, not refused: oversized item inside the kept window is cut
    # to MAX_ITEM; the list keeps only the newest MAX_CONTEXT entries
    hist_in = [f"m{i}" for i in range(serve.MAX_CONTEXT + 5)]
    hist_in.append("h" * (serve.MAX_ITEM + 999))  # newest = oversized
    r = post({"state": {"history": hist_in}, "questions": {}})
    assert r.status_code == 200, r.text
    hist = seen["state"]["history"]
    assert len(hist) == serve.MAX_CONTEXT, len(hist)
    assert len(hist[-1]) == serve.MAX_ITEM, len(hist[-1])

    # refused: an oversized body never reaches the door at all — 413 from
    # the request middleware before parsing (T775/T831 pre-check)
    serve._BUCKETS.clear()
    big = ('{"state": {"history": ['
           + ",".join('"' + "y" * 60_000 + '"' for _ in range(18)) + "]}}").encode()
    assert len(big) > serve.MAX_BODY
    r = client.post("/v1/systemone", content=big,
                    headers={"content-type": "application/json"})
    assert r.status_code == 413 and "body too large" in r.text, r.text


def test_t976_preflight_options_side_effect_free_and_auth_free(
        monkeypatch, tmp_path):  # T976
    """T976: a preflight is a question, not an attempt. OPTIONS on the POST
    endpoints gets the framework's 405 + `allow: POST` — the handler never
    runs — so it writes no audit row, spends no rate bucket, and needs no
    key even when one is set; the contrast case (the same POST without the
    key is 401) proves auth is present and working, just not reached by a
    preflight. Auth and limits live inside the handlers; documented in
    docs/api.md."""
    import importlib

    from fastapi.testclient import TestClient

    from gatekeeper import audit as _au
    from gatekeeper import serve

    monkeypatch.setenv("BOUNCER_AUDIT", str(tmp_path / "audit.jsonl"))
    importlib.reload(_au)
    client = TestClient(serve.app, raise_server_exceptions=False)
    orig = (serve._KEY, serve._KEY_OLD)
    try:
        for path in ("/predict", "/v1/systemone"):
            serve._KEY = serve._KEY_OLD = ""
            serve._BUCKETS.clear()
            r = client.options(path)
            assert r.status_code == 405, (path, r.status_code)
            assert r.headers.get("allow") == "POST", r.headers
            assert dict(serve._BUCKETS) == {}, "preflight spent no bucket"

        # with a key set the preflight still answers (auth-free), while
        # the real POST without the key is refused (auth present, working)
        serve._KEY = "preflight-key-0123456789"
        serve._BUCKETS.clear()
        r = client.options("/predict")
        assert r.status_code == 405 and r.headers.get("allow") == "POST"
        r = client.post("/predict", json={"message": "p976",
                                          "rules": {"r": "t"}})
        assert r.status_code == 401, r.text

        # no side effects anywhere: no verdict, no audit row
        assert not (tmp_path / "audit.jsonl").exists()

        # documented where API users look
        assert "OPTIONS" in Path("docs/api.md").read_text()
    finally:
        serve._KEY, serve._KEY_OLD = orig
        if _au._F:
            _au._F.close()
        importlib.reload(_au)  # restore the default audit path


def test_t977_rate_limit_holds_under_parallel_threads():  # T977
    """T977: T841's atomic check-then-append re-verified under load, from
    the angle T841 didn't cover — many buckets in parallel. Six IPs
    hammered concurrently (one thread each, switch interval forced to
    1e-6) each admit exactly their own 60: no cross-bucket leakage, no
    over-admission, bucket lengths stay at the cap — and T885's 429
    counter, incremented under a SEPARATE lock, lands exactly on the
    refused count: every refusal counted once under contention."""
    import sys
    import threading
    import types
    import typing

    from fastapi import HTTPException

    from gatekeeper import serve

    ips = [f"10.7.0.{i}" for i in range(1, 7)]

    class Req:
        headers: typing.ClassVar[dict] = {}

        def __init__(self, ip):
            self.client = types.SimpleNamespace(host=ip)

    admitted: dict = {ip: 0 for ip in ips}
    refused: list = []
    count_lock = threading.Lock()
    barrier = threading.Barrier(len(ips))

    def hammer(ip):
        barrier.wait()  # all six buckets collide from a standing start
        for _ in range(75):  # 15 over the 60/min cap per IP
            try:
                serve._rate(Req(ip))
                with count_lock:  # dict += is read-modify-write, not atomic
                    admitted[ip] += 1
            except HTTPException as e:
                assert e.status_code == 429
                refused.append(1)  # list.append is atomic under the GIL

    serve._BUCKETS.clear()
    before_429 = serve._RATE_429
    old_si = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # force preemption inside the race window
    try:
        threads = [threading.Thread(target=hammer, args=(ip,)) for ip in ips]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old_si)

    assert admitted == {ip: 60 for ip in ips}, admitted
    assert len(refused) == len(ips) * 15
    assert serve._RATE_429 - before_429 == len(ips) * 15, "lost 429 count"
    assert all(len(serve._BUCKETS[ip]) == 60 for ip in ips)


def test_t978_sigterm_drain_vs_force_race(monkeypatch, tmp_path):  # T978
    """T978: the drain-vs-force race, pinned from both sides. Drain side:
    drain_inference() waits out a ran pool, reports measured seconds, and
    resets _EXEC so a later submit lazily rebuilds — the wait is
    unbounded by design (the same unboundedness the interpreter already
    applies to non-daemon threads at exit). Force side: audit rows are
    flushed to the OS per write (T758), so the operator's force-kill
    during a wedged drain loses at most the fsync batching window — the
    row is readable before any close(). The runbook documents the
    procedure: one timeout window, then force; the `inference_drained_s`
    line prints only when the drain completed."""
    import importlib

    import gatekeeper as gk
    from gatekeeper import _executor, drain_inference
    from gatekeeper import audit as _au

    # drain side: waited seconds reported, pool reset, fresh rebuild
    ex = _executor()
    fut = ex.submit(sum, range(10_000))
    assert fut.result() == sum(range(10_000))
    waited = drain_inference()
    assert waited >= 0.0, waited
    assert gk._EXEC is None, "drain resets the pool for a fresh build"
    ex2 = _executor()  # lazy rebuild — a later submit gets a live pool
    assert ex2 is not None and ex2 is not ex
    drain_inference()  # leave the module clean for other tests

    # force side: a per-write-flushed row is on disk before any close()
    monkeypatch.setenv("BOUNCER_AUDIT", str(tmp_path / "audit.jsonl"))
    importlib.reload(_au)
    try:
        _au.log_decision("t978 force-side check", "ok", 0.9, "allow", 1.0)
        raw = (tmp_path / "audit.jsonl").read_text()
        assert len(raw.splitlines()) == 1, "flushed row readable pre-close"
        assert '"action": "allow"' in raw
    finally:
        if _au._F:
            _au._F.close()
        importlib.reload(_au)  # restore the default audit path

    # documented where operators will look for the procedure
    runbook = Path("docs/runbook.md").read_text()
    assert "T978" in runbook and "force" in runbook
