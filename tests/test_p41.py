"""P41 tests (T771-T790): security & ops. The threat model is pinned
textually — security claims live and die with the docs, so the tests
check the doc's honesty structure (assets/actors/boundaries present,
gaps tracked, every cited box real) rather than runtime exploits."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")

DOCS = Path("docs")


def test_threat_model_doc():  # T771
    doc = (DOCS / "threat-model.md").read_text()
    # the three requested views exist
    for section in ("## Assets", "## Actors", "## Trust boundaries"):
        assert section in doc, section
    # assets cover the real attack surface: the secret, the verdicts, the
    # evidence trail, the weights, payload privacy, availability
    for needle in ("BOUNCER_KEY", "verdict integrity", "audit log",
                   "checkpoint", "confidential", "availability"):
        assert needle in doc, needle
    # actors include the unauthenticated caller and the supply chain —
    # not just "users might be naughty"
    for needle in ("operator", "API client", "anonymous", "supply chain"):
        assert needle in doc, needle
    # boundaries cite their enforcement boxes (no hand-waving protections)
    for needle in ("constant-time", "T292", "T308", "T224", "T756",
                   "T459", "T515"):
        assert needle in doc, needle
    # gaps are TRACKED, not hidden: each follow-up box is listed by number,
    # and the systemone passthrough gap is named for what it actually is
    for needle in ("Known gaps", "not hidden", "/v1/systemone",
                   "T772", "T773", "T774", "T775"):
        assert needle in doc, needle
    # every T-number cited must exist in TODO.md — no invented boxes
    todo = Path("TODO.md").read_text()
    for t in sorted(set(re.findall(r"T\d{3,4}", doc))):
        assert t in todo, f"threat model cites unknown box {t}"
    # discoverable from both entry points
    assert "docs/threat-model.md" in Path("README.md").read_text()
    assert "threat-model.md" in (DOCS / "SECURITY.md").read_text()


class _FuzzStub:
    """Weightless: the verdict doesn't matter, survival does (T772)."""

    def predict(self, state, questions):
        return {"answers": {"rule": {"choice": "ok", "confidence": 0.9,
                                     "probabilities": {"ok": 0.9}},
                            "harm": {"score": "safe", "probabilities": []},
                            "hype": {"score": "chill", "probabilities": []},
                            "jailbreak": {"noul": 0.0},
                            "escalate": {"noul": 0.0}}}


def test_fuzz_predict_random_bytes_and_deep_nesting():  # T772
    import random

    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    gatekeeper._router = _FuzzStub()
    client = TestClient(serve.app, raise_server_exceptions=False)
    rules = {"fuzz-rule": "fuzz body must stay on topic"}
    rng = random.Random(0xF022)  # seeded: reproducible fuzz, not theater
    H = {"content-type": "application/json"}

    # 1. random bytes as the message field: any 2xx/4xx is an answer,
    #    5xx never is
    serve._BUCKETS.clear()
    for _ in range(50):
        blob = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 200)))
        r = client.post("/predict",
                        json={"message": blob.decode("utf-8", "replace"),
                              "rules": rules})
        assert r.status_code < 500, (r.status_code, r.text[:200])

    # 2. random bytes as the RAW body: malformed JSON is a clean 4xx
    serve._BUCKETS.clear()
    for _ in range(20):
        blob = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 500)))
        r = client.post("/predict", content=blob, headers=H)
        assert r.status_code in (400, 413, 422), r.status_code

    # 3. deep nesting (JSON bomb): 422 from validation, never a recursion
    #    crash -> 500
    serve._BUCKETS.clear()
    for depth in (100, 1000):
        body = json.dumps({"message": "x", "rules": rules,
                           "context": depth * [[]] + ["deep"]}).encode()
        r = client.post("/predict", content=body, headers=H)
        assert r.status_code == 422, (depth, r.status_code)

    # 4. lone surrogates (legal in JSON \ud800 escapes) — the pre-T772
    #    fuzz run found UnicodeEncodeError -> 500 here (CACHE.key encode).
    #    Sent as raw escaped JSON (httpx's json= can't encode surrogates
    #    client-side; a hostile client has no such limitation). Message/
    #    history/lang are sanitized to valid text; rule text is operator-
    #    set and gets rejected instead (E_RULES_TEXT, 422).
    serve._BUCKETS.clear()

    def _raw(payload):  # ensure_ascii escapes -> the wire carries \ud800
        return json.dumps(payload).encode("utf-8")

    r = client.post("/predict", content=_raw(
        {"message": "lone \ud800 surrogate", "rules": rules}), headers=H)
    assert r.status_code == 200, r.text
    r = client.post("/predict", content=_raw(
        {"message": "x", "rules": rules, "context": ["user: \ud800line"]}),
        headers=H)
    assert r.status_code == 200, r.text
    r = client.post("/predict", content=_raw(
        {"message": "x", "rules": rules, "lang": "\ud800"}), headers=H)
    # lang is validated by format anyway — a surrogate hint is rejected 422
    assert r.status_code == 422 and "E_LANG" in r.text, r.text
    r = client.post("/predict", content=_raw(
        {"message": "x", "rules": {"r": "rule \ud800 text"}}), headers=H)
    assert r.status_code == 422 and "E_RULES_TEXT" in r.text, r.text

    # 5. the server is still exactly as alive as before the storm
    r = client.post("/predict", json={"message": "p772 normal msg",
                                      "rules": rules})
    assert r.status_code == 200 and r.json()["action"] == "allow"

    # engine-level: the same inputs never raise, with or without the server
    from gatekeeper import moderate
    res = moderate("engine \ud800 path", rules, router=_FuzzStub())
    assert res["action"] == "allow"


def test_rules_bombs_rejected():  # T773: existed (T004-T006), now pinned
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    gatekeeper._router = _FuzzStub()
    client = TestClient(serve.app, raise_server_exceptions=False)

    def post(payload):
        serve._BUCKETS.clear()
        return client.post("/predict", json=payload)

    # value bomb (>280 chars) with a valid slug id
    r = post({"message": "p773 value bomb",
              "rules": {"spam": "A" * 5000}})
    assert r.status_code == 422 and "E_RULES_TEXT" in r.text, r.text
    # id bomb (>24 chars / non-slug)
    r = post({"message": "p773 id bomb",
              "rules": {"k" * 5000: "valid text"}})
    assert r.status_code == 422 and "E_RULES_ID" in r.text, r.text
    # count bomb (>12 rules)
    r = post({"message": "p773 count bomb",
              "rules": {f"r{i}": f"rule {i} text" for i in range(13)}})
    assert r.status_code == 422 and "E_RULES_COUNT" in r.text, r.text
    # a non-str value is named, not coerced (T266)
    r = post({"message": "p773 int bomb", "rules": {"spam": 12345}})
    assert r.status_code == 422, r.text
    # exactly at the caps: still allowed (the bound is a bound, not a wall)
    r = post({"message": "p773 at caps",
              "rules": {"a" * 24: "B" * 280}})
    assert r.status_code == 200, r.text
    # engine-level too: the same bomb raises RuleError before any model work
    import pytest

    from gatekeeper.rules import RuleError
    with pytest.raises(RuleError):
        gatekeeper.moderate("p773 engine bomb", {"spam": "C" * 300},
                            router=_FuzzStub())
    # documented in the API reference (undocumented caps drift silently)
    assert "E_RULES_TEXT" in Path("docs/api.md").read_text()


def test_systemone_history_cap_server_side():  # T774: not just docs
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    seen = {}

    class Rec:
        def predict(self, state, questions):
            seen["state"] = state
            return {"answers": {}}

    gatekeeper._router = Rec()
    client = TestClient(serve.app, raise_server_exceptions=False)

    # over the cap: the raw path trims to the newest MAX_CONTEXT items —
    # same window as /predict's context (T308) and engine [-history_n:]
    serve._BUCKETS.clear()
    hist = [f"h{i}" for i in range(50)]
    r = client.post("/v1/systemone",
                    json={"state": {"message": "m", "history": hist},
                          "questions": {}})
    assert r.status_code == 200, r.text
    got = seen["state"]["history"]
    assert len(got) == serve.MAX_CONTEXT
    assert got == hist[-serve.MAX_CONTEXT:]  # newest kept, oldest dropped

    # under the cap: untouched — the Jev wire contract survives the cap
    serve._BUCKETS.clear()
    hist2 = hist[:5]
    client.post("/v1/systemone",
                json={"state": {"history": hist2}, "questions": {}})
    assert seen["state"]["history"] == hist2

    # non-list history passes through untouched: this box is the COUNT
    # cap; per-item/content validation is T775's
    serve._BUCKETS.clear()
    client.post("/v1/systemone",
                json={"state": {"history": "not-a-list"}, "questions": {}})
    assert seen["state"]["history"] == "not-a-list"

    # /predict still rejects >20 context outright (T308 unchanged)
    serve._BUCKETS.clear()
    r = client.post("/predict", json={"message": "p774 cap check",
                                      "rules": {"r": "rule text"},
                                      "context": [f"c{i}" for i in range(21)]})
    assert r.status_code == 422 and "E_CONTEXT" in r.text, r.text

    # and the cap is documented where the endpoint is
    assert "history" in Path("docs/api.md").read_text()


def test_context_item_and_key_length_hardening():  # T775
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    seen = {}

    class Rec:
        def predict(self, state, questions):
            seen["state"] = state
            return _FuzzStub().predict(state, questions)

    gatekeeper._router = Rec()
    client = TestClient(serve.app, raise_server_exceptions=False)
    rules = {"no-spam": "no ads or links"}

    def post(path, payload=None, **kw):
        serve._BUCKETS.clear()
        return client.post(path, json=payload, **kw)

    # context ITEM length: the 20-item count cap misses one 500k-char item
    r = post("/predict", {"message": "p775 item cap", "rules": rules,
                          "context": ["x" * (serve.MAX_ITEM + 1)]})
    assert r.status_code == 422 and "E_CONTEXT" in r.text, r.text
    # exactly at the bound still passes — a bound is a bound, not a wall
    r = post("/predict", {"message": "p775 at item cap", "rules": rules,
                          "context": ["x" * serve.MAX_ITEM]})
    assert r.status_code == 200, r.text

    # systemone dict KEYS: bounded at both top levels, rejected (a key
    # can't be trimmed coherently), 64 chars exactly still passes
    r = post("/v1/systemone", {"state": {"k" * (serve.MAX_KEY + 1): "v"},
                               "questions": {}})
    assert r.status_code == 422 and "E_STATE" in r.text, r.text
    r = post("/v1/systemone", {"state": {},
                               "questions": {"q" * (serve.MAX_KEY + 1): {}}})
    assert r.status_code == 422 and "E_STATE" in r.text, r.text
    r = post("/v1/systemone", {"state": {"k" * serve.MAX_KEY: "v"},
                               "questions": {}})
    assert r.status_code == 200, r.text

    # systemone history ITEMS: trimmed to the same bound (T774's trim
    # precedent — /predict rejects this, the raw passthrough trims)
    r = post("/v1/systemone", {"state": {"history": ["h" * (serve.MAX_ITEM + 999)]},
                               "questions": {}})
    assert r.status_code == 200, r.text
    assert [len(h) for h in seen["state"]["history"]] == [serve.MAX_ITEM]

    # body-size pre-check: Content-Length over 1MB is 413 from the request
    # middleware — before any parsing (the old T291 helper only ran inside
    # the batch handler, after the body was already read)
    serve._BUCKETS.clear()
    big = ('{"message": "p775 big", "rules": {"r": "text"}, "context": ['
           + ",".join('"' + "y" * 60_000 + '"' for _ in range(18)) + "]}").encode()
    assert len(big) > serve.MAX_BODY
    r = client.post("/predict", content=big,
                    headers={"content-type": "application/json"})
    assert r.status_code == 413 and "body too large" in r.text, r.text
    # under the limit, same shape answers normally (the bound didn't eat
    # legitimate traffic)
    r = post("/predict", {"message": "p775 normal after storms", "rules": rules})
    assert r.status_code == 200 and r.json()["action"] == "allow"

    # both caps are documented where people look for them
    api = Path("docs/api.md").read_text()
    assert "E_STATE" in api and "8000 chars" in api
    readme = Path("README.md").read_text()
    assert "before they're parsed" in readme


def test_two_key_rotation_window():  # T776
    import inspect

    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    gatekeeper._router = _FuzzStub()
    client = TestClient(serve.app, raise_server_exceptions=False)
    payload = {"message": "p776 rotation window",
               "rules": {"no-spam": "no ads or links"}}
    orig = (serve._KEY, serve._KEY_OLD)

    def attempt(key):  # key=None → no header at all
        serve._BUCKETS.clear()
        h = {} if key is None else {"X-API-Key": key}
        return client.post("/predict", json=payload, headers=h)

    try:
        # window open: both keys carry full weight, everything else 401
        serve._KEY, serve._KEY_OLD = "new-key-0123456789", "old-key-0123456789"
        assert attempt("new-key-0123456789").status_code == 200
        assert attempt("old-key-0123456789").status_code == 200
        assert attempt("wrong-key-0123456789").status_code == 401
        assert attempt(None).status_code == 401
        # hostile non-ASCII header: 401, never compare_digest(str) TypeError
        # -> 500 (the pre-T776 line did exactly that)
        assert attempt(b"\xff\xfe-key-bytes").status_code == 401
        # both comparisons always run — no short-circuit `or` that would
        # let timing say which key was close
        src = inspect.getsource(serve._auth)
        assert "compare_digest(got, _KEY_OLD.encode" in src
        assert " or hmac" not in src and "and hmac.compare" not in src

        # window closed: the old key dies the instant the var is gone
        serve._KEY, serve._KEY_OLD = "new-key-0123456789", ""
        assert attempt("new-key-0123456789").status_code == 200
        assert attempt("old-key-0123456789").status_code == 401

        # auth off entirely (no primary) still means open API — the old
        # key alone never turns the check on
        serve._KEY, serve._KEY_OLD = "", "old-key-0123456789"
        assert attempt(None).status_code == 200
    finally:
        serve._KEY, serve._KEY_OLD = orig

    # the runbook lives where operators look for it
    sec = Path("docs/SECURITY.md").read_text()
    for needle in ("two-key window", "BOUNCER_KEY_OLD", "constant-time",
                   "T776", "/ready", "step 3"):
        assert needle in sec, needle


def test_short_old_key_warns_at_boot():  # T776: T292's warning, window key too
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if k != "BOUNCER_KEY"}
    env["BOUNCER_KEY_OLD"] = "short"
    env["PYTHONPATH"] = "src" + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, "-c", "import gatekeeper.serve"],
                       capture_output=True, text=True, timeout=60,
                       check=False, env=env)
    assert "BOUNCER_KEY_OLD shorter than 16 chars" in p.stdout, p.stdout
    assert "BOUNCER_KEY shorter" not in p.stdout  # the primary is unset here


def test_trusted_proxy_client_ip():  # T777
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    orig_trusted = list(serve._TRUSTED)

    class Peer:
        def __init__(self, host):
            self.host = host

    class Req:
        def __init__(self, host, headers=None):
            self.client = Peer(host) if host is not None else None
            self.headers = headers or {}

    try:
        # trusted peer: the rightmost XFF hop wins — that's the one OUR
        # proxy appended; client-sent entries to its left never count
        serve._TRUSTED[:] = ["10.0.0.1"]
        got = serve._client_ip(Req("10.0.0.1",
                                   {"x-forwarded-for": "spoofed, 203.0.113.9"}))
        assert got == "203.0.113.9", got
        # trusted peer with no header, or a blank rightmost hop: fall back
        # to the socket peer rather than an empty bucket key
        assert serve._client_ip(Req("10.0.0.1")) == "10.0.0.1"
        assert serve._client_ip(Req("10.0.0.1",
                                    {"x-forwarded-for": "  "})) == "10.0.0.1"

        # untrusted peer: forwarding headers are ignored outright — the
        # spoof attempt changes nothing
        assert serve._client_ip(Req("203.0.113.66",
                                    {"x-forwarded-for": "1.2.3.4"})) == "203.0.113.66"
        # no config at all (the default): never trust, whatever the peer
        serve._TRUSTED[:] = []
        assert serve._client_ip(Req("10.0.0.1",
                                    {"x-forwarded-for": "1.2.3.4"})) == "10.0.0.1"
        assert serve._client_ip(Req(None)) == "?"  # client=None safe
    finally:
        serve._TRUSTED[:] = orig_trusted

    # end-to-end: with the TestClient peer trusted, buckets key by the
    # forwarded client — one IP can still hit the wall, another still walks
    gatekeeper._router = _FuzzStub()
    client = TestClient(serve.app, raise_server_exceptions=False)
    payload = {"message": "p777 proxy rate", "rules": {"no-spam": "no ads or links"}}
    serve._TRUSTED[:] = ["testclient"]
    try:
        serve._BUCKETS.clear()
        wall = None
        for i in range(61):
            r = client.post("/predict", json=payload,
                            headers={"X-Forwarded-For": "198.51.100.7"})
            if r.status_code == 429:
                wall = i
                break
        assert wall == 60, f"forwarded client hit the wall at request {wall}"
        # a different forwarded client is a different bucket: untouched
        r = client.post("/predict", json=payload,
                        headers={"X-Forwarded-For": "198.51.100.8"})
        assert r.status_code == 200, r.status_code
        # ...and the doc tells operators how to switch this on
        sec = Path("docs/SECURITY.md").read_text()
        assert "BOUNCER_TRUSTED_PROXY" in sec and "rightmost" in sec
    finally:
        serve._TRUSTED[:] = orig_trusted
        serve._BUCKETS.clear()


def test_metrics_exposure_gate():  # T778
    import pytest
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    gatekeeper._router = _FuzzStub()
    client = TestClient(serve.app, raise_server_exceptions=False)
    orig = (serve._KEY, serve._KEY_OLD)

    try:
        # keyless server = open server: metrics open too (same bargain
        # as every other route) — this is also what keeps the old tests
        # and a default Prometheus scrape working
        serve._KEY = serve._KEY_OLD = ""
        serve._BUCKETS.clear()
        assert client.get("/metrics").status_code == 200

        # key set: the TestClient peer isn't loopback → key required
        serve._KEY = "metrics-key-0123456789"
        serve._BUCKETS.clear()
        assert client.get("/metrics").status_code == 401
        r = client.get("/metrics",
                       headers={"X-API-Key": "metrics-key-0123456789"})
        assert r.status_code == 200 and "bouncer_" in r.text, r.text
        assert client.get("/metrics", headers={"X-API-Key": "nope"}).status_code == 401
        # this box gates metrics alone: LB-facing GETs keep their contract
        for path in ("/health", "/ready", "/version", "/stats"):
            assert client.get(path).status_code == 200, path

        # loopback exemptions (unit — TestClient's peer can't be loopback)
        class Peer:
            def __init__(self, host):
                self.host = host

        class Req:
            def __init__(self, host, headers=None):
                self.client = Peer(host)
                self.headers = headers or {}

        serve._metrics_gate(Req("127.0.0.1"))        # direct local scrape: free
        serve._metrics_gate(Req("::1"))              # v6 loopback too
        with pytest.raises(HTTPException) as e:      # remote, no key
            serve._metrics_gate(Req("203.0.113.5"))
        assert e.value.status_code == 401
        with pytest.raises(HTTPException) as e:      # loopback THROUGH a local
            serve._metrics_gate(Req("127.0.0.1",    # proxy: forwarded hop seen
                                    {"x-forwarded-for": "203.0.113.5"}))
        assert e.value.status_code == 401
        # ...and a forwarded header can't fake loopback from outside
        with pytest.raises(HTTPException) as e:
            serve._metrics_gate(Req("203.0.113.5",
                                    {"x-forwarded-for": "127.0.0.1"}))
        assert e.value.status_code == 401
        # keyless again: the gate is off entirely, even remote
        serve._KEY = ""
        serve._metrics_gate(Req("203.0.113.5"))
    finally:
        serve._KEY, serve._KEY_OLD = orig
        serve._BUCKETS.clear()

    # documented where operators and integrators look
    assert "T778" in Path("docs/SECURITY.md").read_text()
    assert "T778" in Path("docs/api.md").read_text()


def test_log_injection_guard(capfd, monkeypatch):  # T779
    import io
    import json as _json

    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve
    from gatekeeper.cli import main as cli_main
    from gatekeeper.explain import explain
    from gatekeeper.normalize import strip_controls

    # reasons are scrubbed at the SOURCE: operator rule text carrying an
    # ANSI screen-wipe, bells, a newline and a bidi override never survives
    s = explain({"action": "flag", "rule": "no-spam", "confidence": 0.9,
                 "rule_dist": {}},
                {"no-spam": "no ads\x1b[2J\x07\nor \u202eevil"})
    assert all(c.isprintable() for c in s), repr(s)
    assert "no ads[2J" in s and "or evil" in s  # printable text intact
    assert strip_controls("hi\x1b[2J there\t") == "hi[2J there"

    # watch: the message preview is raw user text on a TTY — scrubbed too
    gatekeeper._router = _FuzzStub()
    monkeypatch.setattr("sys.stdin", io.StringIO("preview \x1b[2J wipe here\n"))
    assert cli_main(["watch", "--preset", "gaming"]) == 0
    out = capfd.readouterr().out
    assert "preview [2J wipe here" in out, out
    assert "\x1b[2J" not in out  # the only ESC left are the color codes

    # server log lines parse as JSON no matter what rides in: a quote in
    # the request id can't close its string and forge fields, keys are fixed
    client = TestClient(serve.app, raise_server_exceptions=False)
    serve._BUCKETS.clear()
    r = client.get('/foo%22bar', headers={"X-Request-ID": 'evil","forged":true'})
    # printable chars (quotes included) are echoed intact — only the LOG
    # encoding changes, not the contract
    assert r.headers["X-Request-ID"] == 'evil","forged":true'
    line = [ln for ln in capfd.readouterr().out.splitlines() if '"rid"' in ln][-1]
    obj = _json.loads(line)  # the old f-string made this unparseable/forged
    assert set(obj) == {"rid", "path", "ms"}
    assert obj["rid"] == 'evil","forged":true'

    # the internal-error line is dumped too
    class Boom:
        def predict(self, state, questions):
            raise RuntimeError("nope")

    gatekeeper._router = Boom()
    serve._BUCKETS.clear()
    r = client.post("/v1/systemone", json={"state": {}, "questions": {}})
    assert r.status_code == 500 and r.json()["detail"]["code"] == "E_INTERNAL"
    line = [ln for ln in capfd.readouterr().out.splitlines()
            if '"internal-error"' in ln][-1]
    obj = _json.loads(line)
    assert set(obj) == {"event", "path", "err"} and obj["err"] == "RuntimeError"

    # documented where operators look
    assert "T779" in Path("docs/SECURITY.md").read_text()


def test_demo_share_warning(capsys):  # T780
    import inspect

    from gatekeeper import demo_app

    demo_app.share_warning(False)
    assert capsys.readouterr().out == ""  # local demos stay quiet
    demo_app.share_warning(True)
    out = capsys.readouterr().out
    assert '"warn"' in out and "PUBLIC" in out and "URL" in out

    # wired into the launch path, and BEFORE the gradio import — a missing
    # or slow gradio can't swallow the warning
    src = inspect.getsource(demo_app.launch)
    assert src.index("share_warning(share)") < src.index("import gradio")

    # documented where operators and users look
    assert "T780" in Path("docs/SECURITY.md").read_text()
    assert "demo --share" in Path("README.md").read_text()


def test_dependency_audit_job():  # T781
    text = Path(".github/workflows/ci.yml").read_text()
    i = text.index("audit:")  # job key — first occurrence is the T781 job
    job = text[i:i + 700]
    # resolver-only scan of the declared runtime tree: no install, no weights
    assert "pip-audit -r pyproject.toml" in job, job[:200]
    assert "T781" in job
    assert "T781" in Path("docs/threat-model.md").read_text()


def test_rate_limit_xff_spoof_bypass():  # T782: the attack, not the mechanism
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    gatekeeper._router = _FuzzStub()
    client = TestClient(serve.app, raise_server_exceptions=False)
    payload = {"message": "p782 spoof burst", "rules": {"no-spam": "no ads"}}
    orig = list(serve._TRUSTED)

    def wall(headers_fn, tries=61):
        for i in range(tries):
            if client.post("/predict", json=payload,
                           headers=headers_fn(i)).status_code == 429:
                return i
        return None  # no wall at all — the bypass worked

    try:
        # 1. untrusted peer rotating a FRESH forwarded ip per request: the
        # header is ignored wholesale, so it's still one socket-peer bucket
        # and the wall lands exactly where it would with no header at all
        serve._TRUSTED[:] = ["10.0.0.1"]
        serve._BUCKETS.clear()
        n = wall(lambda i: {"X-Forwarded-For": f"203.0.113.{i % 250}"})
        assert n == 60, f"rotating spoofed XFF bought {n} requests before the wall"

        # 2. attacker BEHIND a trusted proxy prepending fake hops: the proxy
        # appends the real client last, and the rightmost hop is the only
        # one counted — fake prefixes can't fragment the bucket
        serve._TRUSTED[:] = ["testclient"]  # TestClient peer plays the proxy
        serve._BUCKETS.clear()
        n = wall(lambda i: {"X-Forwarded-For": f"fake{i}, 198.51.100.42"})
        assert n == 60, f"fake XFF prefixes bought {n} requests behind the proxy"

        # 3. same attack with a full chain of lies: one counted hop, one
        # bucket, same wall — the length of the header is free to waste
        serve._BUCKETS.clear()
        n = wall(lambda i: {"X-Forwarded-For":
                            ", ".join(f"lie{i}-{j}" for j in range(20))
                            + ", 198.51.100.42"})
        assert n == 60, f"a 20-lie chain bought {n} requests"
    finally:
        serve._TRUSTED[:] = orig
        serve._BUCKETS.clear()

    # the threat model claims this attack is dead — keep the claim cited
    assert "T782" in Path("docs/threat-model.md").read_text()
