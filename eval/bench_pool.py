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
                       "stats": t.stats()},
            # T909: mixed-language traffic, measured — the folklore was
            # "two languages thrash a 2-slot pool"; the numbers say whether
            # they do, as COUNTABLE facts (hits/creates/evictions/by_model),
            # never as latency assertions
            "languages": mixed_language(n_requests)}


def mixed_language(n_requests: int) -> dict:
    """T909: english + multilingual alternating through the pool — the
    smallest realistic multilingual deployment.

    max_n=2 holds both checkpoints: a steady build-each-once pattern.
    max_n=1 cannot: every language switch evicts the other, so ALL
    requests pay a rebuild. The report names both runs with their
    eviction/hit counts and by_model tags, so an operator can see the
    thrash in their own numbers (GET /stats pool.by_model shows the same
    tags live) instead of taking the README's word for it."""
    results = {}
    for cap, lang in ((2, "fits"), (1, "thrash")):
        pool = RouterPool(max_n=cap, factory=build_delay)
        t0 = time.perf_counter()
        for i in range(n_requests):  # alternating checkpoints, not devices
            pool.get(model="english" if i % 2 == 0 else "multilingual")
        s = pool.stats()
        results[lang] = {
            "max_n": cap,
            "pooled_s": round(time.perf_counter() - t0, 3),
            "hits": s["hits"], "creates": s["creates"],
            "evictions": s["evictions"],  # the thrash number itself
            "by_model": s["by_model"],  # T895: per-checkpoint checkouts
        }
    # the claim under test: one slot free per language => no thrash;
    # fewer slots than languages => every switch is an eviction
    fits, thrash = results["fits"], results["thrash"]
    results["verdict"] = {
        "two_slots_no_thrash": fits["evictions"] == 0 and fits["creates"] == 2,
        "one_slot_full_thrash": thrash["evictions"] > 0
        and thrash["hits"] == 0,
        "eviction_ratio": (round(thrash["evictions"] / fits["evictions"], 1)
                           if fits["evictions"] else None),
    }
    return results


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
