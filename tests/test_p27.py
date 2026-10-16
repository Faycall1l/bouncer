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


def test_question_hints_all_langs():  # T503
    from gatekeeper import build_questions
    for lang in ("en", "es", "fr", "ar"):
        q = build_questions({"a": "rule a text"}, lang)
        assert lang in q["rule"]["instructions"]
    assert "hint" not in build_questions({"a": "rule a text"})["rule"]["instructions"]


def test_preset_lang_tags():  # T501+T506
    import pytest

    from gatekeeper import list_presets
    from gatekeeper.presets import preset_lang
    assert preset_lang("es") == "es" and preset_lang("ar") == "ar"
    assert preset_lang("gaming") == "en"
    assert {preset_lang(n) for n in list_presets()} <= {"en", "es", "fr", "ar"}
    with pytest.raises(KeyError):
        preset_lang("nope")


def test_preset_lang_autofill():  # T502+T507
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    class S:
        def predict(self, state, questions):
            assert state.get("lang_hint") == "ar"
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    gatekeeper._router = S()
    serve._BUCKETS.clear()
    r = TestClient(serve.app).post("/predict", json={"message": "p27 autofill مباراة",
                                                     "preset": "ar"})
    assert r.status_code == 200 and r.json()["lang"] == "ar"


def test_cli_lang_mismatch_note(capsys):  # T504+T508
    import gatekeeper
    from gatekeeper.cli import main

    class S:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    gatekeeper._router = S()
    assert main(["check", "p27 mismatch msg", "--preset", "es", "--lang", "fr"]) == 0
    assert "note" in capsys.readouterr().err


def test_i18n_script_parity(tmp_path):  # T509
    import json as _json
    import os as _os
    import subprocess
    import sys as _sys
    env = dict(_os.environ, PYTHONPATH="src:eval")
    r = subprocess.run([_sys.executable, "eval/eval_i18n.py", "--help"], check=False,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "--limit" in r.stdout and "--out" in r.stdout
    out = tmp_path / "i.json"
    r = subprocess.run([_sys.executable, "eval/eval_i18n.py", "--limit", "4",
                        "--out", str(out), "--json"], check=False, capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0 and _json.loads(out.read_text())["n"] == 4


def test_lang_format_422():  # T496+T510
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    class S:
        def predict(self, state, questions):
            raise AssertionError("unreachable")
    gatekeeper._router = S()
    serve._BUCKETS.clear()
    r = TestClient(serve.app).post("/predict", json={"message": "hi",
                                                     "rules": {"a": "rule a text"},
                                                     "lang": "not a language!!"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E_LANG"
