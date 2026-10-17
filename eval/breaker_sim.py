"""T571: breaker simulation (no weights). Failure storm -> breaker opens,
recovers after cooldown. Writes eval/reports/breaker.json."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, "src")

import gatekeeper  # noqa: E402
from gatekeeper import GateConfig, moderate  # noqa: E402
from gatekeeper.cache import CACHE  # noqa: E402


class DownRouter:
    """Model that is down: every predict raises."""

    calls = 0

    def predict(self, state, questions):
        type(self).calls += 1
        raise RuntimeError("simulated outage")


class UpRouter:
    """Recovered model: answers normally."""

    def predict(self, state, questions):
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


def main(storm=3, cool=0.2, n_open=4):
    CACHE.clear()
    gatekeeper._BREAKER.update({"fails": 0, "open_until": 0.0, "half_open": False})
    rules = {"plain-chat": "normal talk"}
    cfg = GateConfig(breaker_n=storm, breaker_cool_s=cool)
    events, down = [], DownRouter()
    for i in range(n_open):
        r = moderate(f"sim storm {i}", rules, config=cfg, router=down)
        events.append({"phase": "storm", "i": i, "cause": r["cause"],
                       "model_calls": down.calls})
    tripped = gatekeeper._breaker_tripped()
    time.sleep(cool + 0.05)  # cooldown passes -> half-open probe
    r = moderate("sim probe", rules, config=cfg, router=UpRouter())
    events.append({"phase": "probe", "cause": r["cause"], "action": r["action"]})
    closed = not gatekeeper._breaker_tripped()
    gatekeeper._BREAKER.update({"fails": 0, "open_until": 0.0, "half_open": False})
    return {"storm_n": storm, "cool_s": cool, "tripped": tripped, "closed": closed,
            "last_cause": r["cause"], "events": events}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="breaker_sim")
    ap.add_argument("--storm", type=int, default=3)
    ap.add_argument("--cool", type=float, default=0.2)
    ap.add_argument("--out", default="eval/reports/breaker.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = main(a.storm, a.cool)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps(rep, indent=None if a.json else 2))
