"""T106+T107: latency scripts (need weights). 1-vs-5 questions; batch-size sweep."""
import sys
import time

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def bench(n_q=5, batch=1):
    from gatekeeper import build_questions, get_router
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
    # T107: batch-size sweep entry — run with N=64: `N=64 python eval/bench_latency.py`
    # (moderate_batch chunks at 1/4/8/16 via chunk= arg; compare wall time per message)
