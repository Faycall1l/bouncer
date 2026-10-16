"""P27 tests (T491-T510): multilingual wiring. No weights."""
import sys

sys.path.insert(0, "src")

from gatekeeper import moderate
from gatekeeper.cache import CACHE
from gatekeeper.normalize import detect_script


class ModelStub:
    def __init__(self):
        self.seen = {}

    def predict(self, state, questions, model=None):
        self.seen = {"model": model, "script": state.get("script"),
                     "hint": state.get("lang_hint"),
                     "instructions": questions["rule"]["instructions"]}
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


def test_auto_model_ar():  # T500
    CACHE.clear()
    stub = ModelStub()
    r = moderate("مباراة رائعة جدا p27", {"khalik-latif": "ممنوع الشتائم"}, lang="ar",
                 router=stub)
    assert stub.seen["model"] == "multilingual"  # auto-pinned
    assert stub.seen["script"] == "arabic" and stub.seen["hint"] == "ar"
    assert "ar" in stub.seen["instructions"]  # T503
    assert r["script"] == "arabic" and "[lang=ar]" in r["reason"]  # T491+T494


def test_detect_script():  # T492
    assert detect_script("hello world") == "latin"
    assert detect_script("مباراة جيدة") == "arabic"
    assert detect_script("привет") == "cyrillic"
    assert detect_script("你好世界") == "cjk"
    assert detect_script("123 !!!") == "other"
    assert detect_script(None) == "other"
