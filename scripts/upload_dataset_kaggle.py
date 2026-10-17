"""T657: publish the built dataset to Kaggle (`kaggle datasets create/version`).

Dry-run by default (same contract as data/upload_hf.py, T639): prints the plan,
touches nothing. --yes stages the dataset + splits + card into a temp dir and
runs the kaggle CLI (`--version` updates an existing dataset instead of
creating a new one).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

DEFAULT_FILES = ["data/gatekeeper-12k.jsonl", "data/gatekeeper-12k.train.jsonl",
                 "data/gatekeeper-12k.dev.jsonl", "data/gatekeeper-12k.test.jsonl",
                 "data/CARD.md"]


def row_count(path: str):
    if not path.endswith(".jsonl") or not os.path.exists(path):
        return None
    with open(path) as f:
        return sum(1 for _ in f)


def plan(slug: str, files: list) -> dict:
    """The publish plan as data — pure, testable, no network."""
    entries = []
    for path in files:
        exists = os.path.exists(path)
        entries.append({"path": path, "ok": exists,
                        "rows": row_count(path) if exists else None})
    return {"slug": slug, "files": entries,
            "missing": [e["path"] for e in entries if not e["ok"]],
            "total_rows": sum(e["rows"] or 0 for e in entries),
            "kaggle_cli": bool(shutil.which("kaggle")),
            "credentials": os.path.exists(os.path.expanduser("~/.kaggle/kaggle.json"))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="upload_dataset_kaggle",
                                 description="publish dataset to Kaggle (dry-run default)")
    ap.add_argument("--slug", default="gatekeeper-chatmix-12k")
    ap.add_argument("--dataset", default=None,
                    help="override the file list with one dataset path")
    ap.add_argument("--message", default="", help="version message for --version")
    ap.add_argument("--version", action="store_true",
                    help="update an existing dataset instead of creating one")
    ap.add_argument("--yes", action="store_true",
                    help="actually run the kaggle CLI (without it: dry-run)")
    a = ap.parse_args(argv)

    files = [a.dataset] if a.dataset else DEFAULT_FILES
    p = plan(a.slug, files)
    print(json.dumps(p, indent=2))
    if p["missing"]:
        print(f"upload_dataset_kaggle: missing files: {p['missing']}", file=sys.stderr)
        return 1
    if not a.yes:
        print("upload_dataset_kaggle: dry-run only — pass --yes to publish",
              file=sys.stderr)
        return 0
    if not p["kaggle_cli"]:
        print("upload_dataset_kaggle: kaggle CLI not on PATH", file=sys.stderr)
        return 1

    # stage exactly the planned files (never the whole data/ dir)
    with tempfile.TemporaryDirectory() as td:
        stage = os.path.join(td, a.slug)
        os.makedirs(stage)
        for path in files:
            shutil.copy(path, os.path.join(stage, os.path.basename(path)))
        if a.version:
            cmd = ["kaggle", "datasets", "version", "-p", stage, "-m",
                   a.message or "gatekeeper dataset update"]
        else:
            cmd = ["kaggle", "datasets", "create", "-p", stage, "--slug", a.slug]
        print("upload_dataset_kaggle: running:", " ".join(cmd))
        return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
