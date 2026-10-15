"""Rule-set validation. Error codes: E_RULES_* (see README)."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
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


def validate_rule_text(rules: dict, max_chars: int = 280) -> None:
    """T005: rule text non-empty, bounded."""
    for rid, text in rules.items():
        if not isinstance(text, str) or not text.strip():
            raise RuleError(f"E_RULES_TEXT: rule {rid!r} has empty text")
        if len(text) > max_chars:
            raise RuleError(f"E_RULES_TEXT: rule {rid!r} exceeds {max_chars} chars")


def validate_rule_count(rules: dict, max_rules: int = 12) -> None:
    """T006: bounded label space keeps options distinguishable (see Banking77 lesson)."""
    if len(rules) > max_rules:
        extra = sorted(rules)[max_rules:]
        raise RuleError(f"E_RULES_COUNT: {len(rules)} rules > {max_rules}; drop e.g. {extra}")


def validate_reserved(rules: dict) -> None:
    """T007: `ok` is the built-in none-violated label."""
    if "ok" in rules:
        raise RuleError("E_RULES_RESERVED: 'ok' is reserved (means no violation)")


def validate_severity(rules: dict, severity: dict) -> None:
    """T251+T252: severity values are low|high and keyed on real rule ids."""
    for rid, level in (severity or {}).items():
        if level not in ("low", "high"):
            raise RuleError(f"E_RULES_SEVERITY: rule {rid!r} severity {level!r} "
                            "(use 'low' or 'high')")
        if rid not in rules:
            raise RuleError(f"E_RULES_SEVERITY: severity for unknown rule {rid!r}")


def warn_overlapping(rules: dict) -> list:
    """T045: rule texts sharing rare words confuse the scorer; return warnings."""
    toks = {rid: {t.lower() for t in text.split() if len(t) >= 4} for rid, text in rules.items()}
    warns = []
    ids = list(rules)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            shared = toks[ids[i]] & toks[ids[j]]
            if len(shared) >= 3:
                warns.append(f"{ids[i]} ~ {ids[j]} share {sorted(shared)[:4]}")
    return warns


def validate_rules(rules: dict, max_rules: int = 12, max_chars: int = 280,
                   severity: dict | None = None) -> dict:
    """Full pass; returns the rules unchanged for chaining."""
    validate_rule_ids(rules)
    validate_rule_text(rules, max_chars)
    validate_rule_count(rules, max_rules)
    validate_reserved(rules)
    validate_severity(rules, severity or {})  # T251+T252
    return rules
