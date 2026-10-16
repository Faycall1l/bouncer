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


def test_moderate_preset_paths():  # T479+T480
    import pytest

    from gatekeeper import moderate
    from gatekeeper.cache import CACHE
    from gatekeeper.rules import RuleError
    CACHE.clear()

    class S:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    r = moderate("p26 lib preset msg", preset="gaming", router=S())
    assert r["action"] == "allow"
    with pytest.raises(RuleError, match="E_PRESET"):
        moderate("x", {"a": "rule a text"}, preset="gaming", router=S())
    with pytest.raises(RuleError, match="E_PRESET"):
        moderate("x", preset="nope", router=S())


def test_preset_split_thresholds():  # T481
    gatekeeper._router = Stub()
    r = client.post("/predict", json={"message": "p26 thr msg", "preset": "gaming",
                                      "allow_threshold": 0.99, "delete_threshold": 0.99})
    assert r.status_code == 200
    body = r.json()
    assert body["thresholds"] == {"allow": 0.99, "delete": 0.99}


def test_preset_rules_conflict():  # T482
    r = client.post("/predict", json={"message": "hi", "rules": {"a": "rule a text"},
                                      "preset": "gaming"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E_PRESET"


def test_batch_preset():  # T473+T485
    r = client.post("/predict/batch", json={"messages": ["p26 bb1", "p26 bb2"],
                                            "preset": "study"})
    assert r.status_code == 200 and len(r.json()) == 2
    assert all("raw" not in row for row in r.json())


def test_batch_preset_gates():  # T486: preset text really decides, not just 200s
    class Viol:
        def predict(self, state, questions):
            assert "no-cheat" in questions["rule"]["criteria"]  # gaming pack arrived
            return {"answers": {
                "rule": {"choice": "no-cheat", "confidence": 0.95,
                         "probabilities": {"no-cheat": 0.95}},
                "harm": {"score": "harmful", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    gatekeeper._router = Viol()
    r = client.post("/predict/batch", json={"messages": ["p26 bg1"],
                                            "preset": "gaming"})
    assert r.status_code == 200 and r.json()[0]["action"] == "delete"
    gatekeeper._router = Stub()


def test_default_preset_batch(monkeypatch):  # T487
    monkeypatch.setenv("BOUNCER_DEFAULT_PRESET", "stream")
    r = client.post("/predict/batch", json={"messages": ["p26 db1"]})
    assert r.status_code == 200 and len(r.json()) == 1


def test_batch_preset_conflict():  # T488
    r = client.post("/predict/batch", json={"messages": ["hi"],
                                            "rules": {"a": "rule a text"},
                                            "preset": "gaming"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E_PRESET"


def test_default_preset_env(monkeypatch):  # T475
    monkeypatch.setenv("BOUNCER_DEFAULT_PRESET", "study")
    r = client.post("/predict", json={"message": "p26 default msg"})
    assert r.status_code == 200
    monkeypatch.delenv("BOUNCER_DEFAULT_PRESET")
    r = client.post("/predict", json={"message": "p26 nodefault msg"})
    assert r.status_code == 422
