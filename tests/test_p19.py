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
