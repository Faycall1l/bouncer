#!/usr/bin/env python3
"""T737: tag-vs-version guard — the pushed tag must match pyproject.

    python scripts/check_tag.py "$GITHUB_REF_NAME"

Exit 0 when the tag (with or without a leading v) equals the project
version; exit 1 naming both when they differ; exit 2 on usage errors.
Stdlib only (needs python 3.11+ for tomllib; CI pins 3.11), no network.
"""
from __future__ import annotations

import sys

import tomllib


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_tag.py TAG", file=sys.stderr)
        return 2
    tag = argv[1].removeprefix("v")
    with open("pyproject.toml", "rb") as f:
        ver = tomllib.load(f)["project"]["version"]
    if tag != ver:
        print(f"E_TAG: tag {argv[1]!r} != pyproject version {ver!r}",
              file=sys.stderr)
        return 1
    print(f"ok: {argv[1]} == {ver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
