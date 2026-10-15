"""T277: stub-latency bench (no weights). Times moderate() end-to-end overhead."""
import json
import os
import sys
import time

os.environ.setdefault("BOUNCER_AUDIT", "eval/reports/bench-audit.jsonl")
sys.path.insert(0, "src")
from gatekeeper import moderate  # noqa: E402


class Stub:
    def predict(self, state, questions):
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rules = {"plain-chat": "normal talk"}
    lat = []
    r = Stub()
    for i in range(n):
        t0 = time.perf_counter()
        moderate(f"bench stub msg {i}", rules, router=r)
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    report = {"n": n, "p50_ms": round(lat[n // 2], 2),
              "p95_ms": round(lat[int(n * 0.95)], 2),
              "mean_ms": round(sum(lat) / n, 2)}
    os.makedirs("eval/reports", exist_ok=True)
    with open("eval/reports/stub-latency.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report))
