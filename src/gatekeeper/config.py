"""Shared configuration for bouncer decisions."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class GateConfig:
    """Thresholds and limits. One object threads through moderate()/server/CLI."""

    allow_threshold: float = 0.85      # ok + calm -> allow
    delete_threshold: float = 0.85     # violation + confident -> delete
    jailbreak_threshold: float = 0.8   # noul jailbreak always deletes above this
    escalate_threshold: float = 0.7    # escalate_p above this forces review
    margin_abstain: float = 0.15       # top1-top2 gap below this -> abstain/escalate
    max_rules: int = 12
    max_rule_chars: int = 280
    max_msg_chars: int = 2000
    history_n: int = 4
    timeout_s: float = 10.0
    severity: dict = field(default_factory=dict)  # rule_id -> "low" | "high"
