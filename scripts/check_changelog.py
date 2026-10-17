#!/usr/bin/env python3
"""T749: release-notes check — the current version must be documented.

    python scripts/check_changelog.py

Exit 0 when CHANGELOG.md has a version section for pyproject's version
(heading style: `## 0.3.0 — 2026-10-17 (T626)`); exit 1 naming what's
missing, exit 2 on usage errors. Stdlib only (tomllib → python 3.11+,
CI pins 3.11), no network.

`## Unreleased` alone is not enough: tagging without a dated section
would ship notes nobody wrote.
"""
from __future__ import annotations

import re
import sys

import tomllib


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        print("usage: check_changelog.py", file=sys.stderr)
        return 2
    with open("pyproject.toml", "rb") as f:
        ver = tomllib.load(f)["project"]["version"]
    try:
        with open("CHANGELOG.md", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"E_CHANGELOG: {e}", file=sys.stderr)
        return 1
    if not re.search(rf"^## {re.escape(ver)}(?:\s|—|-|$)", text, re.MULTILINE):
        print(f"E_CHANGELOG: no section for version {ver} in CHANGELOG.md — "
              f"add `## {ver} — YYYY-MM-DD` before tagging",
              file=sys.stderr)
        return 1
    print(f"ok: CHANGELOG documents {ver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
