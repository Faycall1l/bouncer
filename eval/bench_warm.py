"""T751: warm-pool latency bench — documented method, honest modes.

Method (this docstring and the BENCHMARKS entry ARE the documentation):

* COLD — first `get_pooled_router()`: pool miss, checkpoint load included.
  Timed once, as one number.
* WARM — N further end-to-end `pool.get()` + `moderate()` calls through
  the warm resident (pool hit, no rebuild; lookup cost included, exactly
  what a serve request pays). p50/p95 over those N.
* CACHE — replay of the first warm message (same rules): the TTL cache
  serves the decision without waking the router. The report's
  `cache_hit: true` is the receipt that the number is a real cache hit
  (T752), never a model call in disguise.
* Real numbers come from the target hardware with real weights:

      python eval/bench_warm.py --n 50            # weights required
      python eval/bench_warm.py --stub --json     # mechanics only

* `--stub` swaps in the deterministic stub router: proves the script,
  reports structure, and pool accounting — `mode: "stub"` says so in the
  report itself, because stub latency is overhead, not model latency.
* Real mode without weights exits 1 with E_WARM and writes NO report:
  a bench that can't measure must not invent numbers.

Writes eval/reports/warm.json (override with --out).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, "src")

from gatekeeper import moderate
from gatekeeper.pool import RouterPool

RULES = {"be-kind": "no insults", "no-spam": "no ads"}


class _Stub:
    def predict(self, state, questions):
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.95,
                     "probabilities": {"ok": 0.95}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}


def _stub_factory(**kw):
    return _Stub()  # the pool fixes the factory signature; kw is its device


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_warm")
    ap.add_argument("--n", type=int, default=50, help="warm calls to time")
    ap.add_argument("--stub", action="store_true",
                    help="stub router: mechanics only, never model numbers")
    ap.add_argument("--out", default="eval/reports/warm.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.stub:
        mode = "stub"
        pool = RouterPool(max_n=1, factory=_stub_factory)
        t0 = time.perf_counter()
        router = pool.get()  # cold: factory call (instant here)
        cold_ms = (time.perf_counter() - t0) * 1000.0
    else:
        mode = "real"
        from gatekeeper.pool import POOL as real_pool
        try:
            t0 = time.perf_counter()
            router = real_pool.get()  # COLD: build + checkpoint load
            cold_ms = (time.perf_counter() - t0) * 1000.0
        except (ImportError, OSError, ValueError) as e:
            print(f"E_WARM: real mode needs weights (laya + a checkpoint): {e}",
                  file=sys.stderr)
            return 1
        pool = real_pool

    lat = []
    for i in range(args.n):  # WARM: pool.get() is a hit from here — timing
        t0 = time.perf_counter()  # includes the lookup, exactly like serve
        router = pool.get()
        moderate(f"warm-pool bench message {i}", RULES, router=router)
        lat.append((time.perf_counter() - t0) * 1000.0)
    lat.sort()
    n = args.n
    # T752: cache-hit latency — replay warm message 0 with identical rules;
    # it was cached during the loop, so this call must come back cached
    t0 = time.perf_counter()
    replay = moderate("warm-pool bench message 0", RULES, router=pool.get())
    cache_hit_ms = (time.perf_counter() - t0) * 1000.0
    rep = {
        "mode": mode,  # stub = mechanics only; real = measured with weights
        "n": n,
        "cold_ms": round(cold_ms, 2),  # pool miss: incl. checkpoint load
        "p50_ms": round(lat[n // 2], 3),
        "p95_ms": round(lat[min(n - 1, int(n * 0.95))], 3),
        "cache_hit_ms": round(cache_hit_ms, 3),  # T752: repeat-serve cost
        "cache_hit": bool(replay.get("cached")),  # the receipt, not a claim
        "pool": pool.stats(),  # creates==1 + hits==n+1: warm-path proof
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps(rep, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
