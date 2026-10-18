"""T762: import-time bench — what `import gatekeeper` costs, cold.

Runs `python -c "import gatekeeper"` N times as fresh subprocesses (new
interpreter every run; only the OS page cache is shared) and reports
p50/p95/max of the import wall time. The property this bench receipts
(T762): the core import must NOT pay for demo extras — gradio is imported
only inside `demo_app.build_app`, so a core install stays fast.

    python eval/bench_import.py [--n 5] [--budget-ms 200] [--json] [--out P]

--budget-ms B: exit 1 when p50 exceeds B ms (report-only when omitted —
T763/T764 wire the budget; the floor is theirs to set honestly). The
report JSON (default eval/reports/import.json) is the receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_import")
    ap.add_argument("--n", type=int, default=5, help="fresh subprocesses")
    ap.add_argument("--budget-ms", type=float, default=0.0,
                    help="fail when p50 exceeds this (0 = report only)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="eval/reports/import.json")
    args = ap.parse_args(argv)

    env = {**os.environ, "PYTHONPATH": os.path.join(_HERE, "..", "src")}
    lat = []
    for _ in range(args.n):
        t0 = time.perf_counter()
        r = subprocess.run([sys.executable, "-c", "import gatekeeper"],
                           check=False, capture_output=True, text=True,
                           timeout=120, env=env)
        if r.returncode != 0:
            print(f"E_IMPORT: {r.stderr.strip()[-300:]}", file=sys.stderr)
            return 2
        lat.append((time.perf_counter() - t0) * 1000.0)
    lat.sort()
    n = len(lat)
    p50 = round(lat[n // 2], 1)
    rep = {"n": n, "p50_ms": p50,
           "p95_ms": round(lat[min(n - 1, int(n * 0.95))], 1),
           "max_ms": round(lat[-1], 1),
           "budget_ms": args.budget_ms or None}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps(rep, indent=None if args.json else 2))
    if args.budget_ms and p50 > args.budget_ms:
        print(f"E_BUDGET: import p50 {p50}ms > budget {args.budget_ms}ms",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
