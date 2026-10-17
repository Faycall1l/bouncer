#!/usr/bin/env python3
"""T746: secret scan — grep-based, stdlib-only, zero config.

Scans every git-tracked text file for unambiguous credential shapes
(GitHub/OpenAI/Google/AWS/Slack tokens, private keys, telegram bot tokens).
It never guesses: only patterns that cannot appear in clean code are
matched, so there is no allowlist to rot and the scan runs identically
local and in CI. Hits are reported as file:line:LABEL — the credential
itself is never printed (doctor's presence-only policy, applied):

    python scripts/secret_scan.py     # exit 1 lists file:line:pattern
"""
from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = {
    "github token": re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    "openai key": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "google api key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "private key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"),
    # a telegram bot token is exactly 8-10 digits, colon, 35 chars
    "telegram token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
}


def main(argv: list[str] | None = None) -> int:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True,
    ).stdout.decode().split("\0")
    names = [n for n in tracked if n]
    hits: list[str] = []
    for name in names:
        try:
            with open(name, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        if b"\0" in raw[:8192]:
            continue  # binary
        lines = raw.decode("utf-8", "replace").splitlines()
        for lineno, line in enumerate(lines, 1):
            for label, pat in PATTERNS.items():
                if pat.search(line):
                    hits.append(f"{name}:{lineno}: {label}")
    for h in hits:
        print(h)
    if hits:
        print(f"secret-scan: {len(hits)} hit(s) — rotate the credential and "
              "purge it from history", file=sys.stderr)
        return 1
    print(f"secret-scan: clean ({len(names)} tracked files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
