"""T639: HF dataset upload with a --dry-run plan. No network unless --yes.

Default behavior is a dry run: prints the upload plan (repo, files, rows,
bytes, missing files) and exits without touching the network. --yes performs
the actual `huggingface-cli upload` (requires HF_TOKEN in the environment).
"""
import argparse
import json
import os
import subprocess
import sys

DEFAULT_FILES = ["data/gatekeeper-12k.jsonl", "data/gatekeeper-12k.train.jsonl",
                 "data/gatekeeper-12k.dev.jsonl", "data/gatekeeper-12k.test.jsonl",
                 "data/CARD.md"]


def plan(repo: str, files: list) -> dict:
    """The upload plan as data — pure, testable, no network."""
    entries = []
    for path in files:
        if os.path.exists(path):
            rows = None
            if path.endswith(".jsonl"):
                with open(path) as f:
                    rows = sum(1 for _ in f)
            entries.append({"path": path, "ok": True,
                            "bytes": os.path.getsize(path), "rows": rows})
        else:
            entries.append({"path": path, "ok": False})
    return {"repo": repo, "files": entries,
            "missing": [e["path"] for e in entries if not e["ok"]],
            "total_bytes": sum(e.get("bytes", 0) for e in entries),
            "token_env": bool(os.environ.get("HF_TOKEN"))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="upload_hf",
                                 description="upload dataset to HF (dry-run default)")
    ap.add_argument("--repo", default="YOUR_HF/gatekeeper-chatmix-12k")
    ap.add_argument("files", nargs="*", help="files to upload (default: build outputs)")
    ap.add_argument("--yes", action="store_true",
                    help="actually upload (without it: dry-run, exit 0)")
    a = ap.parse_args(argv)

    p = plan(a.repo, a.files or DEFAULT_FILES)
    print(json.dumps(p, indent=2))
    if p["missing"]:
        print(f"upload_hf: missing files: {p['missing']}", file=sys.stderr)
        return 1
    if not a.yes:
        print("upload_hf: dry-run only — pass --yes to upload", file=sys.stderr)
        return 0
    if "YOUR_HF" in a.repo:
        print("upload_hf: replace YOUR_HF with your HF namespace", file=sys.stderr)
        return 1
    if not os.environ.get("HF_TOKEN"):
        print("upload_hf: HF_TOKEN not set", file=sys.stderr)
        return 1
    cmd = ["huggingface-cli", "upload", a.repo, "--repo-type", "dataset",
           *[e["path"] for e in p["files"]]]
    print("upload_hf: running:", " ".join(cmd))
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
