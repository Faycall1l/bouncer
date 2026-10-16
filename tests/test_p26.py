"""P26 tests (T471-T490): server multitenancy. No weights."""
import sys

sys.path.insert(0, "src")

import pytest
from fastapi.testclient import TestClient

import gatekeeper
from gatekeeper import serve


class Stub:
    def predict(self, state, questions):
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


@pytest.fixture(autouse=True)
def _iso():
    gatekeeper._router = Stub()
    from gatekeeper.cache import CACHE
    CACHE.clear()
    serve._BUCKETS.clear()
    yield


client = TestClient(serve.app)


def test_preset_predict_and_log(capsys):  # T472+T474
    r = client.post("/predict", json={"message": "p26 preset msg", "preset": "gaming"})
    assert r.status_code == 200 and r.json()["action"] == "allow"
    assert '"preset": "gaming"' in capsys.readouterr().out


def test_unknown_preset_422():  # T472+T476
    r = client.post("/predict", json={"message": "hi", "preset": "nope"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E_PRESET"
    r = client.post("/predict", json={"message": "hi", "preset": 42})  # T476: type guard
    assert r.status_code == 422


def test_preset_singleton_endpoint():  # T477+T478
    r = client.get("/presets/gaming")
    assert r.status_code == 200 and "no-spam" in r.json()["rules"]
    r = client.get("/presets/nope")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E_PRESET"


def test_default_preset_env(monkeypatch):  # T475
    monkeypatch.setenv("BOUNCER_DEFAULT_PRESET", "study")
    r = client.post("/predict", json={"message": "p26 default msg"})
    assert r.status_code == 200
    monkeypatch.delenv("BOUNCER_DEFAULT_PRESET")
    r = client.post("/predict", json={"message": "p26 nodefault msg"})
    assert r.status_code == 422
