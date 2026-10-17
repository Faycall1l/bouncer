"""T760: /stats response time under threaded load (locust-less, in-process).

Method: `--threads` T worker threads, `--requests` R sequential `GET /stats`
each, every worker with its own TestClient (starlette's client is
per-thread). Latency is timed with `time.perf_counter` around each call;
p50/p95/max are over the whole T x R population, rps = population / wall
time. No model is involved: /stats only assembles counters, so this times
OUR bookkeeping under lock contention (strikes/cache/pool/breaker tables).

In-process by design — no socket stack, so these numbers are NOT uvicorn-
over-network numbers; BENCHMARKS records the machine and date, and no
cross-machine claim is made. Exit 1 if any request failed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, "src")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_stats")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--requests", type=int, default=100)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="eval/reports/stats-load.json")
    args = ap.parse_args(argv)

    from fastapi.testclient import TestClient

    from gatekeeper.serve import app

    lat: list[float] = []
    errors: list[str] = []
    oks = [0]
    lock = threading.Lock()

    def worker() -> None:
        client = TestClient(app)  # per-thread client — starlette's contract
        for _ in range(args.requests):
            t0 = time.perf_counter()
            try:
                good = client.get("/stats").status_code == 200
            except Exception as e:  # noqa: BLE001 — report, don't kill the sweep
                good = False
                with lock:
                    errors.append(repr(e))
            with lock:
                if good:
                    oks[0] += 1
                lat.append((time.perf_counter() - t0) * 1000.0)

    t0 = time.perf_counter()
    ts = [threading.Thread(target=worker) for _ in range(args.threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    wall = time.perf_counter() - t0

    lat.sort()
    n = len(lat)
    rep = {"threads": args.threads, "requests": args.requests, "n": n,
           "ok": oks[0], "errors": errors[:3],
           "p50_ms": round(lat[n // 2], 3),
           "p95_ms": round(lat[min(n - 1, int(n * 0.95))], 3),
           "max_ms": round(lat[-1], 3),
           "rps": round(n / max(wall, 1e-9), 1)}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps(rep, indent=None if args.json else 2))
    return 0 if oks[0] == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
