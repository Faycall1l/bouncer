"""P47 tests (T891-T910): multilingual routing. All network is stubbed."""
import sys

sys.path.insert(0, "src")


class _RouteProbe:
    """Router stub that records which checkpoint moderate() asked for."""

    def __init__(self):
        self.seen = []

    def predict(self, state, questions, model=None):
        self.seen.append({"model": model, "script": state.get("script"),
                          "lang_hint": state.get("lang_hint")})
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95,
                     "probabilities": {"ok": 0.95}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


def _mod(msg, lang=None, model=None, probe=None):
    from gatekeeper import moderate
    from gatekeeper.cache import CACHE

    probe = probe or _RouteProbe()
    CACHE.clear()  # each call decides fresh — routing is per-message
    return moderate(msg, {"no-spam": "no spam here"}, lang=lang, model=model,
                    router=probe), probe


def test_checkpoint_routing_keys_off_script_without_lang():  # T891
    """With no lang hint the detected script still picks the checkpoint:
    arabic/cyrillic/cjk ride multilingual, latin stays auto-route (model
    None — we never claim a language from a script), a hint that routes
    (ar) wins over a mismatched script, and an explicit model= beats both."""
    # no lang: the message's script decides
    _, probe = _mod("هذا الرسالة تحتوي على رسائل مزعجة كثيرة")
    assert probe.seen[-1]["model"] == "multilingual", probe.seen
    assert probe.seen[-1]["script"] == "arabic"
    assert probe.seen[-1]["lang_hint"] is None, "detection never fakes a hint"

    _, probe = _mod("это спам сообщение со ссылкой на спам")
    assert probe.seen[-1]["model"] == "multilingual"
    assert probe.seen[-1]["script"] == "cyrillic"

    _, probe = _mod("这是垃圾垃圾垃圾信息")
    assert probe.seen[-1]["model"] == "multilingual"
    assert probe.seen[-1]["script"] == "cjk"

    # latin: auto-route stays the default — no model pin invented
    _, probe = _mod("just a normal friendly message about gardening")
    assert probe.seen[-1]["model"] is None, probe.seen
    assert probe.seen[-1]["script"] == "latin"

    # a lang hint that routes (ar/zh/ru...) wins outright; a hint that has
    # no checkpoint opinion (en, fr...) still lets the message's own script
    # pick — an "en" default over Arabic characters is the stale-hint case
    # T891 exists for, and T897's per-adapter lang override is the escape
    # that beats detection
    _, probe = _mod("هذا الرسالة تحتوي على رسائل مزعجة كثيرة", lang="en")
    assert probe.seen[-1]["model"] == "multilingual", probe.seen
    assert probe.seen[-1]["lang_hint"] == "en", "the hint still travels"

    # an explicit non-latin lang hint routes even when script is latin
    _, probe = _mod("a latin-script transliteration tihdhar al-tarafdaria",
                      lang="ar")
    assert probe.seen[-1]["model"] == "multilingual"
    assert probe.seen[-1]["lang_hint"] == "ar"

    # explicit model= beats both (pinned checkpoint, T455)
    _, probe = _mod("هذا الرسالة تحتوي على رسائل مزعجة كثيرة",
                      lang="ar", model="english")
    assert probe.seen[-1]["model"] == "english"


def test_model_for_script_checkpoint_table():  # T891 unit
    from gatekeeper.pool import model_for_script

    assert model_for_script("arabic") == "multilingual"
    assert model_for_script("cyrillic") == "multilingual"
    assert model_for_script("cjk") == "multilingual"
    assert model_for_script("latin") is None
    assert model_for_script("other") is None
    assert model_for_script(None) is None
    # lang routing itself is untouched (T457 regression guard)
    from gatekeeper.pool import model_for_lang

    assert model_for_lang("ar") == "multilingual" and model_for_lang("en") is None
