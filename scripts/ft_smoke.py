"""T926: `bouncer-ft smoke` — the fine-tune pipeline's CPU smoke path.

Two subprocesses, no weights, no CUDA, no network:
1. train.py --dry-run    — argparse + validate_config (T911/T919)
2. eval/validate_data.py — the dataset schema check the kernel runs (T381/T924)

If either fails here, the 4-5h Kaggle run would fail too — before any quota
is spent. Exit 0 = smoke passed; 1 = a step failed (named on stderr and in
the receipt).

Usage: python scripts/ft_smoke.py [--dataset PATH] [--limit N] [--json]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _last_line(r) -> str:
    """The step's own summary line, stdout first — receipts stay readable."""
    out = (r.stdout or "").strip().splitlines()
    err = (r.stderr or "").strip().splitlines()
    return (out + err)[-1] if (out or err) else f"exit {r.returncode}"


def smoke(dataset: str, limit: int) -> list:
    """(step, ok, detail) receipts — every step runs even after a failure,
    so one look shows ALL the ways this machine is not ready."""
    steps = []

    def _step(name, ok, detail):
        steps.append({"step": name, "ok": bool(ok), "detail": detail})

    ds = Path(dataset)
    if not ds.is_absolute():
        ds = ROOT / dataset
    _step("dataset", ds.is_file(), str(ds) if ds.is_file() else f"{ds} not found")

    r = subprocess.run([sys.executable, str(ROOT / "kaggle/train/train.py"), "--dry-run"],
                       check=False, capture_output=True, text=True, timeout=300,
                       cwd=str(ROOT))
    # exit 0 AND the contract token: an exit 0 without DRY_RUN_OK is not a
    # config validation, it's a script that stopped early
    _step("dry_run", r.returncode == 0 and "DRY_RUN_OK" in r.stdout, _last_line(r))

    r = subprocess.run([sys.executable, str(ROOT / "eval/validate_data.py"), str(ds),
                        "--limit", str(limit), "--json"],
                       check=False, capture_output=True, text=True, timeout=300,
                       cwd=str(ROOT))
    _step("validate_data", r.returncode == 0, _last_line(r))
    return steps


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="bouncer-ft smoke",
        description="CPU smoke path for the fine-tune pipeline (T926): "
                    "config parse + data validate — no weights, no CUDA.")
    ap.add_argument("--dataset", default="data/examples.jsonl",
                    help="JSONL to schema-check (default: the repo's examples)")
    ap.add_argument("--limit", type=int, default=0,
                    help="validate only the first N rows (default: all)")
    ap.add_argument("--json", action="store_true", help="one-line receipt JSON")
    a = ap.parse_args(argv)
    steps = smoke(a.dataset, a.limit)
    ok = all(s["ok"] for s in steps)
    print(json.dumps({"ok": ok, "steps": steps}, indent=None if a.json else 2))
    if not ok:
        bad = " ".join(s["step"] for s in steps if not s["ok"])
        print(f"FT_SMOKE_FAIL: {bad}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
