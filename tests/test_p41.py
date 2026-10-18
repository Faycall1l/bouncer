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
