"""Shared configuration for bouncer decisions."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
from dataclasses import dataclass, field


class ConfigError(ValueError):
    """T255: bad gate configuration. Carries machine-readable code."""

    code = "E_CONFIG"


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
    quiet_hours: tuple = ()  # T185: e.g. (1, 7) UTC -> delete becomes escalate overnight

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """T253+T254: every knob range-checked; safe to call after mutation."""
        for name in ("allow_threshold", "delete_threshold", "jailbreak_threshold",
                     "escalate_threshold"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:  # T253
                raise ConfigError(f"E_CONFIG: {name}={v!r} must be in [0, 1]")
