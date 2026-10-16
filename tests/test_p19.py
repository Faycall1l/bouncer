"""P19 tests (T331-T350): engine + gates. No weights."""
import sys

sys.path.insert(0, "src")

from gatekeeper import GateConfig, moderate
from gatekeeper.cache import CACHE


class HistStub:
    """Echoes the history it received (proves windowing)."""

    def predict(self, state, questions):
        self.last_hist = state["history"]
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


def test_history_window_respected():  # T345
    CACHE.clear()
    stub = HistStub()
    ctx = [f"u{i}: hello there" for i in range(6)]
    moderate("p19 hist msg", {"plain-chat": "normal talk"}, context=ctx,
             config=GateConfig(history_n=2), router=stub)
    assert stub.last_hist == ["u4: hello there", "u5: hello there"]


def test_severity_deletes_sooner():  # T346
    CACHE.clear()

    class Viol:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "no-scams", "confidence": 0.75,
                         "probabilities": {"no-scams": 0.75, "ok": 0.6}},
                "harm": {"score": "suspicious", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    rules = {"no-scams": "no scams, frauds, or rigged giveaways"}
    plain = moderate("p19 sev msg", rules, router=Viol())
    sev = moderate("p19 sev msg", rules,
                   config=GateConfig(severity={"no-scams": "high"}), router=Viol())
    assert (plain["action"], sev["action"]) == ("flag", "delete")


def test_all_presets_validate():  # T349
    from gatekeeper import get_preset, list_presets
    from gatekeeper.rules import validate_rules
    for name in list_presets():
        rules = get_preset(name)
        validate_rules(rules)
        assert all(len(t) <= 280 for t in rules.values()), name


def test_gate_knobs():  # T331+T332+T333
    CACHE.clear()

    class Viol:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "v", "confidence": 0.8, "probabilities": {"v": 0.8}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    rules = {"v": "violation rule text"}
    narrow = moderate("p19 knob msg", rules, config=GateConfig(flag_margin=0.01),
                      router=Viol())
    assert narrow["action"] == "escalate"  # 0.8 < 0.85 - 0.01
    wide = moderate("p19 knob msg", rules, config=GateConfig(flag_margin=0.3),
                    router=Viol())
    assert wide["action"] == "flag"

    class Sus:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "suspicious", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    calm = moderate("p19 calm msg", rules, config=GateConfig(require_calm=True),
                    router=Sus())
    assert calm["action"] == "escalate"
    assert GateConfig(severity_offset=0.05).severity_offset == 0.05


def test_result_keys():  # T335+T336+T337+T344
    CACHE.clear()

    class S:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.9,
                         "probabilities": {"ok": 0.9, "v": 0.7}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    r = moderate("p19 keys msg", {"v": "violation rule text"}, lang="fr", router=S())
    assert r["margin"] == 0.2 and r["thresholds"] == {"allow": 0.85, "delete": 0.85}
    assert r["lang"] == "fr" and r["quiet_active"] is False


def test_user_strikes():  # T340+T341
    from gatekeeper import strikes
    CACHE.clear()
    strikes.reset()

    class Viol:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "v", "confidence": 0.95, "probabilities": {"v": 0.95}},
                "harm": {"score": "harmful", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    r = moderate("p19 strike msg", {"v": "violation rule text"}, user_id="spammer",
                 router=Viol())
    assert r["strikes"]["strikes"] == 2  # delete weighs 2
    assert strikes.weight_for_action("flag") == 1
    assert strikes.weight_for_action("allow") == 0
    strikes.reset()


def test_questions_lang_line():  # T347+T348
    from gatekeeper import build_questions
    q0 = build_questions({"a": "rule a text"})
    assert "(2 options" in q0["rule"]["instructions"] and "hint" not in q0["rule"]["instructions"]
    ql = build_questions({"a": "rule a text"}, lang="ar")
    assert "ar" in ql["rule"]["instructions"]
