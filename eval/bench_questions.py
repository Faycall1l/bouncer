"""T278: 1-question vs 5-question payload timing (stub router, no weights)."""
import json
import sys
import time

sys.path.insert(0, "src")
from gatekeeper import build_questions


class Stub:
    def predict(self, state, questions):
        return {"answers": {qid: {"choice": "ok", "confidence": 1.0} for qid in questions}}


def bench(router, state, questions, n=200):
    lat = []
    for _ in range(n):
        t0 = time.perf_counter()
        router.predict(state, questions)
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    return round(lat[n // 2], 3)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    r, state = Stub(), {"message": "bench q-count msg"}
    q1 = {"rule": build_questions({"a": "rule a text"})["rule"]}
    q5 = build_questions({"a": "rule a text"})
    report = {"n": n, "p50_1q_ms": bench(r, state, q1, n), "p50_5q_ms": bench(r, state, q5, n)}
    print(json.dumps(report))
