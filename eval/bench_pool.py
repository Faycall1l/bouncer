"""T572: router-pool benchmark (no weights, fake factory). Shows pooled
construction timing vs naive rebuild + LRU eviction. Writes reports/pool.json."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, "src")

from gatekeeper.pool import RouterPool


def build_delay(**kw):  # fake router build (~checkpoint load)
    time.sleep(0.05)
    return dict(kw)


def main(max_n=2, n_requests=10, n_devices=2):
    p = RouterPool(max_n=max_n, factory=build_delay)
    t0 = time.perf_counter()
    for i in range(n_requests):  # alternating traffic across devices
        p.get(device=f"dev{i % n_devices}")
    pooled_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    for i in range(n_requests):  # naive: rebuild every time
        build_delay(device=f"dev{i % n_devices}")
    naive_s = time.perf_counter() - t0
    s = p.stats()
    # Thrash scenario: more devices than slots -> eviction storm, no hits.
    # This is why BOUNCER_POOL_MAX must cover the languages you actually serve.
    t = RouterPool(max_n=max_n, factory=build_delay)
    t0 = time.perf_counter()
    for i in range(n_requests):
        t.get(device=f"dev{i % (max_n + 1)}")
    thrash_s = time.perf_counter() - t0
    return {"bench": "bench_pool", "schema": 1,  # T765: fixed report keys
            "mode": "stub",  # fake factory — construction timing only
            "max_n": max_n, "requests": n_requests, "devices": n_devices,
            "pooled_s": round(pooled_s, 3), "naive_s": round(naive_s, 3),
            "speedup": round(naive_s / pooled_s, 1) if pooled_s else None,
            "stats": s,
            "thrash": {"requests": n_requests, "pooled_s": round(thrash_s, 3),
                       "stats": t.stats()}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="bench_pool")
    ap.add_argument("--max-n", type=int, default=2)
    ap.add_argument("--requests", type=int, default=10)
    ap.add_argument("--out", default="eval/reports/pool.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = main(a.max_n, a.requests)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps(rep, indent=None if a.json else 2))
