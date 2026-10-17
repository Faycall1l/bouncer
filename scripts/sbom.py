#!/usr/bin/env python3
"""T726: SBOM-ish dependency manifest — declared deps from pyproject only.

Deterministic (no timestamps, no network, no lockfile): a manifest of every
direct dependency with its floor, plus the extras and the python range, in
a CycloneDX-flavoured shape the release workflow attaches next to the wheel
(T736). Needs python 3.11+ (tomllib); CI pins 3.11.

    python scripts/sbom.py --out dist/sbom.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import tomllib

OPS = (">=", "==", "~=", "<=")


def _split(dep: str) -> dict:
    for op in OPS:
        if op in dep:
            name, ver = dep.split(op, 1)
            return {"name": name.strip(), "requirement": op + ver.strip()}
    return {"name": dep.strip(), "requirement": "*"}


def build_manifest(pyproject: Path) -> dict:
    with open(pyproject, "rb") as f:
        py = tomllib.load(f)
    proj = py["project"]
    return {
        "format": "bouncer-sbom/1",  # declared, not resolved: direct deps only
        "package": {
            "name": proj["name"],
            "version": proj["version"],
            "license": proj["license"]["text"],
        },
        "python": {
            "requires": proj["requires-python"],
            "classifiers": [c for c in proj.get("classifiers", [])
                            if c.startswith("Programming Language :: Python :: 3.")],
        },
        "packages": [_split(d) for d in proj["dependencies"]],
        "extras": {group: [_split(d) for d in deps]
                   for group, deps in
                   sorted(proj.get("optional-dependencies", {}).items())},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="export the SBOM-ish dep list")
    ap.add_argument("--pyproject", default="pyproject.toml")
    ap.add_argument("--out", default=None, help="write here instead of stdout")
    args = ap.parse_args(argv)
    text = json.dumps(build_manifest(Path(args.pyproject)),
                      indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
