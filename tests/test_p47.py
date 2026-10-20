"""P47 tests (T891-T910): multilingual routing. All network is stubbed."""
import sys

sys.path.insert(0, "src")

from gatekeeper.cli import main


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


def test_predict_autofills_lang_from_script():  # T892
    """With neither lang nor a preset, /predict autofills the hint from the
    message's own script: arabic/cyrillic/cjk messages route and echo like
    ones that were told, latin messages stay None (no language claim from a
    script), and explicit lang and preset fills still beat detection."""
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    seen: list[dict] = []

    class Rec:
        def predict(self, state, questions, model=None):
            seen.append(dict(state))
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.9,
                         "probabilities": {"ok": 0.9}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    gatekeeper._router = Rec()
    try:
        client = TestClient(serve.app, raise_server_exceptions=False)
        rules = {"no-spam": "spam"}  # rule word in every msg -> model path

        serve._BUCKETS.clear()
        r = client.post("/predict", json={
            "message": "هذا الرسالة تحتوي على رسائل مزعجة كثيرة",
            "rules": rules})
        assert r.status_code == 200, r.text
        assert r.json()["lang"] == "ar", "autofill echoes the detected tag"
        assert seen[-1].get("lang_hint") == "ar", "and reaches the router"
        assert r.json()["script"] == "arabic", "script stays the honest label"

        # latin: no hint invented, no checkpoint claim
        serve._BUCKETS.clear()
        r = client.post("/predict", json={
            "message": "gardening spam advice nobody asked for",
            "rules": rules})
        assert r.status_code == 200, r.text
        assert r.json()["lang"] is None
        assert "lang_hint" not in seen[-1]

        # explicit lang beats detection
        serve._BUCKETS.clear()
        r = client.post("/predict", json={
            "message": "هذا الرسالة تحتوي على رسائل مزعجة كثيرة",
            "rules": rules, "lang": "fr"})
        assert r.status_code == 200 and r.json()["lang"] == "fr"

        # a preset's pack language (T502) beats detection too
        serve._BUCKETS.clear()
        r = client.post("/predict", json={
            "message": "مباراة حماسية اليوم في الدوري", "preset": "es"})
        assert r.status_code == 200 and r.json()["lang"] == "es"
    finally:
        gatekeeper._router = None


def test_cli_lang_auto_detects_per_message(tmp_path, monkeypatch,
                                           capsys):  # T893
    """`--lang auto` on check/watch is script detection said out loud: an
    Arabic message gets the ar hint (so the row echoes and routes like a
    told one), a latin message stays unhinted, an explicit tag still wins,
    and a preset + auto no longer prints the mismatch note (auto has no
    opinion to disagree with)."""
    import json as _json

    monkeypatch.setattr("gatekeeper.get_router", lambda **kw: _RouteProbe())
    rules = str(tmp_path / "r.json")
    tmp_path.joinpath("r.json").write_text(
        _json.dumps({"no-spam": "spam"}))

    # single message: auto detects arabic -> lang ar in the JSON row
    assert main(["check", "مباراة حماسية اليوم في الدوري spam",
                 "--rules", rules, "--lang", "auto", "--json"]) == 0
    row = _json.loads(capsys.readouterr().out)
    assert row["lang"] == "ar" and row["script"] == "arabic", row

    # latin message: auto stays unhinted (no language claim from a script)
    assert main(["check", "gardening spam advice nobody asked for",
                 "--rules", rules, "--lang", "auto", "--json"]) == 0
    row = _json.loads(capsys.readouterr().out)
    assert row["lang"] is None and row["script"] == "latin", row

    # an explicit tag is still the explicit tag
    assert main(["check", "مباراة حماسية اليوم في الدوري spam",
                 "--rules", rules, "--lang", "fr", "--json"]) == 0
    row = _json.loads(capsys.readouterr().out)
    assert row["lang"] == "fr", row

    # preset + auto: no mismatch note (auto never disagrees, T504 guard)
    assert main(["check", "spam spam", "--preset", "es",
                 "--lang", "auto"]) == 0
    out = capsys.readouterr()
    assert "mismatch" not in out.err and "but --lang" not in out.err, out.err
    # preset + an explicit mismatching tag still notes it (T504 regression)
    assert main(["check", "spam spam", "--preset", "es",
                 "--lang", "fr"]) == 0
    assert "but --lang" in capsys.readouterr().err

    # check --file: auto tags per LINE, not once for the batch
    f = tmp_path / "msgs.txt"
    f.write_text("هذا كلام عادي spam\nnormal latin spam line\n")
    assert main(["check", "--file", str(f), "--rules", rules,
                 "--lang", "auto"]) == 0
    rows = [_json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert [r["lang"] for r in rows] == ["ar", None], rows

    # watch: same detection per piped line
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(
        "هذا كلام عادي spam\nnormal latin spam line\n"))
    assert main(["watch", "--rules", rules, "--lang", "auto",
                 "--json-in"]) == 0
    capsys.readouterr()


def test_preset_lang_covers_every_routed_language():  # T894
    """Every language routing can act on either has a pack or is listed
    packless — the gap is named, not hidden: lang_coverage() maps each
    routed language to its packs (or None), docs/presets.md names each
    packless one, and no routed language falls off both lists."""
    from pathlib import Path

    from gatekeeper.pool import model_for_lang
    from gatekeeper.presets import PACKLESS, PRESET_LANG, ROUTED_LANGS, lang_coverage, list_presets

    cov = lang_coverage()
    assert set(cov) == set(ROUTED_LANGS), "one entry per routed language"

    # every routed language has a pack or is explicitly packless
    for lang in ROUTED_LANGS:
        assert cov[lang] or lang in PACKLESS, f"{lang} neither packed nor listed"
    # packless is not a quiet synonym for "missing": every name is routed
    assert set(PACKLESS) <= set(ROUTED_LANGS)
    # and the map agrees with PRESET_LANG on the languages that DO ship
    assert cov["ar"] == ["ar"]
    assert all(model_for_lang(l) == "multilingual" for l in ROUTED_LANGS)

    # docs own the packless list: each name appears in presets.md
    doc = Path("docs/presets.md").read_text()
    for lang in PACKLESS:
        assert f"`{lang}`" in doc, f"{lang} not listed packless in presets.md"
    assert "Routed-but-packless" in doc, "the gap has a named section"

    # packless languages are exactly the routed ones WITHOUT a preset pack
    packed_langs = set(PRESET_LANG.values())
    assert {l for l in ROUTED_LANGS if l not in packed_langs} == set(PACKLESS)
    assert len(list_presets()) == len(PRESET_LANG), "catalogue is the tag table"
