"""Your own rule pack, split gates, per-user strikes (T806).

    pip install -e .
    python docs/examples/03_custom_rules.py

The written my-pack.json is exactly what `bouncer check --rules
my-pack.json` reads. Pack shape is what the API enforces (T773): 1-12
slug keys (a-z0-9-, <=24 chars) with texts <= 280 chars — check_pack()
mirrors those caps so a bad pack never becomes a surprise 422.

Re-run green on the post-P44-P51 surface at T1002.
"""
import json
import re
import sys
from pathlib import Path

from gatekeeper import GateConfig, moderate
from gatekeeper.explain import explain

RULES = {
    "no-backseat": "no unasked strategy coaching while someone is playing",
    "no-spoilers": "no story or unlock spoilers without a spoiler warning",
    "keep-chat": "no slurs, harassment, or dogpiling other players",
}
# strict allow bar, lazy delete bar — tune the two independently
GATES = GateConfig(allow_threshold=0.9, delete_threshold=0.6)
EXIT = {"allow": 0, "flag": 2, "delete": 2, "escalate": 3}


def check_pack(rules: dict) -> None:
    """The T773 caps, stated as assertions with their error codes."""
    assert 1 <= len(rules) <= 12, "E_RULES_COUNT: 1-12 rules"
    for rid, text in rules.items():
        assert re.fullmatch(r"[a-z0-9-]{1,24}", rid), f"E_RULES_ID: {rid!r}"
        assert len(text) <= 280, f"E_RULES_TEXT: rule {rid!r} too long"


def main() -> int:
    check_pack(RULES)
    out = Path("my-pack.json")  # the same path `bouncer check --rules` takes
    out.write_text(json.dumps(RULES, indent=2) + "\n")
    print(f"wrote {out} ({len(RULES)} rules)")

    msg = "backseat all you want, but no slurs in chat"
    res = moderate(msg, RULES, config=GATES, user_id="u-42")
    print(f"{res['action']:9} strikes={res.get('strikes')}  {msg!r}")
    print(f"  {explain(res, RULES)}")
    return EXIT[res["action"]]


if __name__ == "__main__":
    sys.exit(main())
