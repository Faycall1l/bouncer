"""T278+T755: question-count payload timing (stub router, no weights)."""
import json
import sys
import time

sys.path.insert(0, "src")
from gatekeeper import GateConfig, build_questions, moderate


class Stub:
    def predict(self, state, questions):
        return {"answers": {qid: {"choice": "ok", "confidence": 1.0} for qid in questions}}


class FullStub:  # T755: moderate()-shaped answers for the end-to-end knob legs
    def predict(self, state, questions):
        return {"answers": {
            qid: ({"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}}
                  if qid == "rule" else
                  {"noul": 0.0} if qid in ("jailbreak", "escalate") else
                  {"score": "safe", "probabilities": []})
            for qid in questions}}


def bench(router, state, questions, n=200):
    lat = []
    for _ in range(n):
        t0 = time.perf_counter()
        router.predict(state, questions)
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    return round(lat[n // 2], 3)


def bench_knob(questions_n, n=200):  # T755: the knob itself, end-to-end
    cfg, lat = GateConfig(questions=questions_n), []
    for i in range(n):
        t0 = time.perf_counter()
        # unique messages: every call misses the decision cache on purpose
        moderate(f"knob {questions_n} msg {i}", {"plain-chat": "normal talk"},
                 config=cfg, router=FullStub())
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    return round(lat[n // 2], 3)


if __name__ == "__main__":
    import os  # T383
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    r, state = Stub(), {"message": "bench q-count msg"}
    q1 = {"rule": build_questions({"a": "rule a text"})["rule"]}
    q5 = build_questions({"a": "rule a text"})
    report = {"n": n, "p50_1q_ms": bench(r, state, q1, n), "p50_5q_ms": bench(r, state, q5, n),
              "p50_knob_3q_ms": bench_knob(3, n),  # T755: BOUNCER_QUESTIONS knob
              "p50_knob_5q_ms": bench_knob(5, n)}
    os.makedirs("eval/reports", exist_ok=True)  # T383: persist, don't just print
    with open("eval/reports/questions.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report))
