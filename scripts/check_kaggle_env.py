"""T656: pre-flight for the Kaggle fine-tune run — checks what can be checked
without a GPU, before quota is spent: kaggle CLI + credentials, dataset artifact,
HF token hint. Emits a JSON plan; exit 1 if a required check fails.

Usage: python scripts/check_kaggle_env.py [--dataset PATH] [--json]
"""
import argparse
import json
import os
import shutil
import sys


def checks(dataset: str) -> list:
    out = []
    cli = shutil.which("kaggle")
    out.append({"name": "kaggle_cli", "ok": bool(cli), "required": False,
                "detail": cli or "kaggle CLI not on PATH — pip install kaggle"})
    kjson = os.path.expanduser("~/.kaggle/kaggle.json")
    if os.path.exists(kjson):
        perm_ok = (os.stat(kjson).st_mode & 0o077) == 0
        detail = kjson + ("" if perm_ok
                          else " — chmod 600, the Kaggle CLI refuses world-readable creds")
    else:
        perm_ok, detail = False, "missing ~/.kaggle/kaggle.json (run `kaggle login`)"
    out.append({"name": "kaggle_credentials", "ok": perm_ok, "required": True,
                "detail": detail})
    out.append({"name": "dataset_artifact", "ok": os.path.exists(dataset), "required": True,
                "detail": dataset if os.path.exists(dataset)
                else f"{dataset} not built — python data/build_dataset.py --n 12000 --seed 42"})
    token = bool(os.environ.get("HF_TOKEN"))
    out.append({"name": "hf_token", "ok": token, "required": False,
                "detail": "HF_TOKEN in env (set it as a Kaggle secret too, T655)" if token
                else "no local HF_TOKEN — fine if set as a Kaggle secret (T655)"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="check_kaggle_env",
                                 description="Kaggle fine-tune pre-flight (T656)")
    ap.add_argument("--dataset", default="data/gatekeeper-12k.jsonl")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cks = checks(a.dataset)
    ok = all(c["ok"] for c in cks if c["required"])
    rep = {"ok": ok, "checks": cks,
           "failed_required": [c["name"] for c in cks if c["required"] and not c["ok"]]}
    print(json.dumps(rep, indent=None if a.json else 2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
