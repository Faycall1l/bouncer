"""Embed bouncer in-process — one moderate() call per message (T806).

    pip install -e .
    python docs/examples/01_in_process.py

Zero-shot: no training, no API server, no network. The printed action is
whatever your checkpoint decides — the script claims nothing about it.
Exit codes are the CLI contract: 0 allow, 2 delete/flag, 3 escalate
(worst over the batch).

Re-run green on the post-P44-P51 surface at T1002.
"""
import sys

from gatekeeper import get_preset, moderate

MESSAGES = [
    "gg that clutch, wp team",   # ordinary chatter
    "you all suck, uninstall",   # hostile
    "FREE NITRO http://x.gg",    # scam bait
]


def main() -> int:
    rules = get_preset("gaming")  # or your own {"slug": "rule text"} dict
    codes = {"allow": 0, "flag": 2, "delete": 2, "escalate": 3}
    worst = 0
    for msg in MESSAGES:
        res = moderate(msg, rules)  # forward pass + gates + evidence
        print(f"{res['action']:9} {msg!r}  rule={res['rule']}")
        worst = max(worst, codes[res["action"]])
    return worst


if __name__ == "__main__":
    sys.exit(main())
