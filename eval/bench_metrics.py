"""T948: /metrics scrape cost + exposition-format check (in-process).

Method: one TestClient, one GET /metrics, timed with time.perf_counter.
The scrape assembles every P49 family — per-rule (capped), per-cause,
per-adapter, breaker, coalesce, review depth, pool, cache — so this times
OUR aggregation + the exposition render under a single lock. The p50_ms is
gated against --max-metrics-p50-ms (~10x the in-process measurement, the
T766 budget rule).

The report ALSO carries the format verdict: the body must parse as
Prometheus exposition (every sample line `name{labels} value`, every
family with exactly one # HELP + one # TYPE). A broken scrape is a FAIL
that never depends on machine speed, so it catches on slow CI too.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, "src")

_NAME = r"[a-zA-Z_:][a-zA-Z0-9_:]*"
_LABEL = r'[a-zA-Z_][a-zA-Z0-9_]*="(?:[^"\\]|\\.)*"'
_SAMPLE = re.compile(rf"^{_NAME}(?:{{{_LABEL}(?:,{_LABEL})*}})? "
                     r"(-?[0-9.eE+]+|NaN|[+-]?Inf)$")


def parse_exposition(body: str) -> dict:
    """Parse /metrics text; returns format verdict, never raises on bad text."""
    helps: set[str] = set()
    types: set[str] = set()
    samples: set[str] = set()
    bad_lines: list[str] = []
    for line in body.splitlines():
        if not line.strip():
            continue
        if line.startswith("# HELP "):
            name = line[len("# HELP "):].split(" ")[0]
            helps.add(name)
        elif line.startswith("# TYPE "):
            parts = line[len("# TYPE "):].split(" ")
            types.add(parts[0] if parts else "")
        elif line.startswith("#"):
            bad_lines.append(line[:40])
        elif _SAMPLE.match(line):
            samples.add(line.split("{")[0].split(" ")[0])
        else:
            bad_lines.append(line[:40])
    return {"families": len(samples), "helps": len(helps), "types": len(types),
            "samples": len(samples), "format_ok": not bad_lines,
            "bad_lines": bad_lines[:3],
            "help_complete": bool(samples) and samples <= helps and helps == types}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_metrics")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="eval/reports/metrics.json")
    ap.add_argument("--max-metrics-p50-ms", type=float, default=100.0)
    args = ap.parse_args(argv)

    from fastapi.testclient import TestClient

    from gatekeeper.serve import app

    client = TestClient(app)
    t0 = time.perf_counter()
    resp = client.get("/metrics")
    ms = (time.perf_counter() - t0) * 1000.0
    if resp.status_code != 200:
        print(f"bench_metrics: /metrics -> {resp.status_code}", file=sys.stderr)
        return 1
    fmt = parse_exposition(resp.text)
    rep = {"bench": "bench_metrics", "schema": 1, "mode": "n/a",  # T765
           "p50_ms": round(ms, 3), **fmt}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps(rep, indent=None if args.json else 2))
    if not fmt["format_ok"] or not fmt["help_complete"]:
        return 1  # a broken exposition is a fail regardless of speed
    return 0 if ms <= args.max_metrics_p50_ms else 1


if __name__ == "__main__":
    raise SystemExit(main())
