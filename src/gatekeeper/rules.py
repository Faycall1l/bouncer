"""Rule-set validation. Error codes: E_RULES_* (see README)."""
from __future__ import annotations

import re

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")


class RuleError(ValueError):
    code = "E_RULES"


def validate_rule_ids(rules: dict) -> None:
    """T004: ids must be slugs: lowercase alnum + dash, <=24 chars."""
    if not isinstance(rules, dict) or not rules:
        raise RuleError("E_RULES_EMPTY: rules must be a non-empty {id: text} mapping")
    for rid in rules:
        if not isinstance(rid, str) or not ID_RE.match(rid):
            raise RuleError(f"E_RULES_ID: bad rule id {rid!r} (use a-z, 0-9, dash, <=24 chars)")
