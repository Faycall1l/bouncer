"""T384: batch-size sweep with stub router (no weights). Prints + saves JSON."""
import json
import os
import sys
import time

sys.path.insert(0, "src")
from gatekeeper import moderate_batch


class Stub:
    def predict(self, state, questions):
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


if __name__ == "__main__":
    rules = {"plain-chat": "normal talk"}
    rows = {}
    for size in (1, 4, 8, 16):
        for chunk in (1, 4, 8, 16):
            msgs = [f"sweep {size}/{chunk} msg {i}" for i in range(size)]  # unique: no cache
            t0 = time.perf_counter()
            moderate_batch(msgs, rules, router=Stub(), chunk=chunk)
            rows[f"batch{size}/chunk{chunk}"] = round((time.perf_counter() - t0) * 1000, 1)
    report = {"rows": rows}
    os.makedirs("eval/reports", exist_ok=True)
    with open("eval/reports/batch-sweep.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
