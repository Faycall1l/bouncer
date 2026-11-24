"""T1238: deterministic paired inference over outcome deltas.

No distributional assumption is smuggled in as a default. The bootstrap seed,
count, and interval width are caller-declared; the sign test is exact or it is
not run. Missing deltas are rejected rather than dropped behind the scenes.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from .schema import SchemaError, _dict, _keys, _number, _str


@dataclass(frozen=True)
class BootstrapInterval:
    metric: str
    mean: float
    lo: float
    hi: float
    n: int
    n_boot: int
    ci: float
    seed: int

    def __post_init__(self) -> None:
        _str(self.metric, "BootstrapInterval.metric")
        for name in ("mean", "lo", "hi"):
            _number(getattr(self, name), f"BootstrapInterval.{name}", -1e12, 1e12)
        if not self.lo <= self.mean <= self.hi:
            raise SchemaError("BootstrapInterval: mean outside interval")
        for name in ("n", "n_boot"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise SchemaError(f"BootstrapInterval.{name}: expected positive int")
        _number(self.ci, "BootstrapInterval.ci", 0.0, 1.0)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise SchemaError("BootstrapInterval.seed: expected int")

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "mean": self.mean, "lo": self.lo,
                "hi": self.hi, "n": self.n, "n_boot": self.n_boot,
                "ci": self.ci, "seed": self.seed}

    @classmethod
    def from_dict(cls, value: Any) -> BootstrapInterval:
        obj = _dict(value, "BootstrapInterval")
        _keys(obj, "BootstrapInterval", ("metric", "mean", "lo", "hi", "n",
                                         "n_boot", "ci", "seed"))
        return cls(metric=obj["metric"], mean=obj["mean"], lo=obj["lo"],
                   hi=obj["hi"], n=obj["n"], n_boot=obj["n_boot"],
                   ci=obj["ci"], seed=obj["seed"])


@dataclass(frozen=True)
class SignTestResult:
    metric: str
    wins: int
    losses: int
    ties: int
    p_two_sided: float
    method: str

    def __post_init__(self) -> None:
        _str(self.metric, "SignTestResult.metric")
        for name in ("wins", "losses", "ties"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise SchemaError(f"SignTestResult.{name}: expected non-negative int")
        _number(self.p_two_sided, "SignTestResult.p_two_sided", 0.0, 1.0)
        if self.method != "exact":
            raise SchemaError("SignTestResult.method: only exact is supported")

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "wins": self.wins, "losses": self.losses,
                "ties": self.ties, "p_two_sided": self.p_two_sided,
                "method": self.method}

    @classmethod
    def from_dict(cls, value: Any) -> SignTestResult:
        obj = _dict(value, "SignTestResult")
        _keys(obj, "SignTestResult", ("metric", "wins", "losses", "ties",
                                      "p_two_sided", "method"))
        return cls(metric=obj["metric"], wins=obj["wins"], losses=obj["losses"],
                   ties=obj["ties"], p_two_sided=obj["p_two_sided"],
                   method=obj["method"])


def paired_bootstrap(values: list[float], *, metric: str, n_boot: int,
                     ci: float, seed: int) -> BootstrapInterval:
    """Resample paired deltas with a caller-seeded RNG; no implicit fallbacks."""
    if not values:
        raise SchemaError("paired_bootstrap: no deltas")
    if isinstance(n_boot, bool) or not isinstance(n_boot, int) or n_boot < 100:
        raise SchemaError("paired_bootstrap: n_boot must be >= 100")
    if not 0.0 < ci < 1.0:
        raise SchemaError("paired_bootstrap: ci must be in (0, 1)")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SchemaError("paired_bootstrap: seed must be an int")
    clean = [_number(v, "delta", -1e12, 1e12) for v in values]
    rng = random.Random(seed)
    n = len(clean)
    means = [sum(clean[rng.randrange(n)] for _ in range(n)) / n
             for _ in range(n_boot)]
    means.sort()
    lo_q, hi_q = (1.0 - ci) / 2.0, (1.0 + ci) / 2.0
    lo = means[max(0, math.ceil(lo_q * n_boot) - 1)]
    hi = means[min(n_boot - 1, max(0, math.ceil(hi_q * n_boot) - 1))]
    return BootstrapInterval(metric=metric, mean=sum(clean) / n, lo=lo, hi=hi,
                             n=n, n_boot=n_boot, ci=ci, seed=seed)


def sign_test(values: list[float], *, metric: str) -> SignTestResult:
    """Exact two-sided sign test; ties are counted, never discarded silently."""
    if not values:
        raise SchemaError("sign_test: no deltas")
    clean = [_number(v, "delta", -1e12, 1e12) for v in values]
    wins = sum(1 for v in clean if v > 0)
    losses = sum(1 for v in clean if v < 0)
    ties = len(clean) - wins - losses
    n = wins + losses
    if n == 0:
        raise SchemaError("sign_test: no non-tied pairs")
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return SignTestResult(metric=metric, wins=wins, losses=losses, ties=ties,
                          p_two_sided=min(1.0, 2.0 * tail), method="exact")


def paired_deltas(metrics: dict[str, Any], metric: str) -> tuple[list[float], list[str]]:
    """Extract per-instance deltas for one metric.

    The second return value names instances excluded for a missing value; the
    caller must record it in the report. Nothing is silently dropped here.
    """
    side = metrics.get("delta_series")
    if not isinstance(side, dict) or metric not in side:
        raise SchemaError(f"paired_deltas: metric {metric!r} absent from delta_series")
    series = side[metric]
    if not isinstance(series, list):
        return [], ["delta_series_not_a_list"]
    values: list[float] = []
    excluded: list[str] = []
    for i, v in enumerate(series):
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(v):
            excluded.append(str(i))
        else:
            values.append(float(v))
    return values, excluded


__all__ = [
    "BootstrapInterval", "SignTestResult", "paired_bootstrap", "paired_deltas",
    "sign_test",
]
