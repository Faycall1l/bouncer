"""CLI tests with stubbed router (no weights). T134."""
import sys

sys.path.insert(0, "src")

import gatekeeper
from gatekeeper.cli import main


class Stub:
    def __init__(self, choice="ok", conf=0.95):
        self.a = {"rule": {"choice": choice, "confidence": conf,
                           "probabilities": {choice: conf}},
                  "harm": {"score": "safe"}, "hype": {"score": "chill"},
                  "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}

    def predict(self, state, questions):
        return {"answers": self.a}


def test_check_allow_exit_0(capsys):  # T134
    gatekeeper._router = Stub()
    assert main(["check", "good game", "--preset", "gaming"]) == 0


def test_check_delete_exit_2(capsys):
    gatekeeper._router = Stub(choice="no-cheat", conf=0.95)
    assert main(["check", "aimbot for sale", "--preset", "gaming"]) == 2
