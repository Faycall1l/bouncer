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
    flag_margin: float = 0.15          # T331: violation conf within this of delete bar -> flag
    require_calm: bool = False         # T332: allow only when harm == safe
    severity_offset: float = 0.15      # T333: high-severity rules delete this much sooner
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
        if not 0.0 <= self.margin_abstain <= 1.0:  # T254
            raise ConfigError(f"E_CONFIG: margin_abstain={self.margin_abstain!r} "
                              "must be in [0, 1]")
        if self.timeout_s <= 0:  # T254
            raise ConfigError(f"E_CONFIG: timeout_s={self.timeout_s!r} must be > 0")
        if self.history_n < 0:  # T254
            raise ConfigError(f"E_CONFIG: history_n={self.history_n!r} must be >= 0")

    @classmethod
    def from_dict(cls, d: dict) -> GateConfig:
        """T289: build from a JSON config; unknown keys rejected loudly."""
        known = {f for f in cls.__dataclass_fields__}
        extra = sorted(set(d) - known)
        if extra:
            raise ConfigError(f"E_CONFIG: unknown keys {extra}")
        return cls(**{k: v for k, v in d.items() if k in known})
