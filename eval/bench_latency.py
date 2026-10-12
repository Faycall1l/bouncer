"""T106+T107: latency scripts (need weights). 1-vs-5 questions; batch-size sweep."""
import sys, time

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def bench(n_q=5, batch=1):
    from gatekeeper import get_router, build_questions
    r = get_router()
    rules = {"be-kind": "no insults", "no-spam": "no ads"}
    qs = build_questions(rules)
    if n_q == 1:
        qs = {"rule": qs["rule"]}
    ts = []
    for _ in range(N):
        t = time.time()
        r.predict({"message": "good game all"}, qs)
        ts.append((time.time() - t) * 1000)
    ts.sort()
    print(f"questions={n_q} batch={batch} p50={ts[len(ts)//2]:.0f}ms")


if __name__ == "__main__":
    bench(1)
    bench(5)
