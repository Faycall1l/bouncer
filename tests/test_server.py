"""Server tests with a stub router (no weights). T051/T132/T133."""
import sys

sys.path.insert(0, "src")

from fastapi.testclient import TestClient

import gatekeeper
from gatekeeper import serve


class Stub:
    def __init__(self):
        self.n = 0

    def predict(self, state, questions):
        self.n += 1
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


gatekeeper._router = Stub()
client = TestClient(serve.app)


import pytest


@pytest.fixture(autouse=True)
def _stub_router():
    gatekeeper._router = Stub()
    from gatekeeper.cache import CACHE
    CACHE.clear()
    yield


def test_health():  # T132
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_version():
    assert client.get("/version").json()["version"] == gatekeeper.__version__


def test_predict_ok():
    r = client.post("/predict", json={"message": "good game", "rules": {"plain-chat": "normal talk"}})
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "allow" and "reason" in body and "raw" not in body


def test_predict_bad_rules_422():  # T133
    r = client.post("/predict", json={"message": "hi", "rules": {"BAD ID!": "x"}})
    assert r.status_code == 422


def test_systemone_passthrough():  # T051
    r = client.post("/v1/systemone", json={"state": {"message": "hi"},
        "questions": {"q": {"type": "noul", "instructions": "hi?"}}})
    assert r.status_code == 200
