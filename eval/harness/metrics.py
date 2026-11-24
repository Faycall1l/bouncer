"""T1237: metrics computed from paired outcomes and the pinned gold labels.

Every metric is derived from the RunBatch + TaskSpec pair set. Missing support
is reported explicitly (`gate_precision_status`), never filled with a friendly
number. Latency uses nearest-rank quantiles so two runs of the same batch
produce the same report apart from measured timings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .runner import RunBatch
from .schema import (
    VARIANTS,
    SchemaError,
    TaskSpec,
    _dict,
    _keys,
    _str,
    canonical,
    digest,
)

_METRIC_KEYS = (
    "rule_acc", "action_acc", "gate_precision", "gate_n",
    "gate_precision_status", "abstention_rate", "ece", "p50_ms", "p95_ms",
    "per_rule", "mismatches",
)
_DELTA_KEYS = ("rule_acc", "action_acc", "gate_precision", "abstention_rate",
               "ece", "p50_ms", "p95_ms")
_SERIES_KEYS = ("rule_correct", "action_correct", "abstained", "confidence",
                "latency_ms")


@dataclass(frozen=True)
class MetricsConfig:
    """Explicit metric knobs; no silent defaults in the harness."""

    ece_bins: int
    gate_min_n: int

    def __post_init__(self) -> None:
        if isinstance(self.ece_bins, bool) or not isinstance(self.ece_bins, int) \
                or not 2 <= self.ece_bins <= 50:
            raise SchemaError("MetricsConfig.ece_bins: expected int in 2..50")
        if isinstance(self.gate_min_n, bool) or not isinstance(self.gate_min_n, int) \
                or self.gate_min_n < 0:
            raise SchemaError("MetricsConfig.gate_min_n: expected non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {"ece_bins": self.ece_bins, "gate_min_n": self.gate_min_n}

    @classmethod
    def from_dict(cls, value: Any) -> MetricsConfig:
        obj = _dict(value, "MetricsConfig")
        _keys(obj, "MetricsConfig", ("ece_bins", "gate_min_n"))
        return cls(ece_bins=obj["ece_bins"], gate_min_n=obj["gate_min_n"])


@dataclass(frozen=True)
class MetricsReport:
    schema: int
    mode: str
    manifest_hash: str
    n: int
    base: str
    candidate: str
    variants: tuple[str, ...]
    ece_bins: int
    gate_min_n: int
    metrics: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema != 1:
            raise SchemaError("MetricsReport.schema: only 1 is supported")
        if self.mode != "paired":
            raise SchemaError("MetricsReport.mode: only paired is supported")
        if not isinstance(self.manifest_hash, str) or len(self.manifest_hash) != 64:
            raise SchemaError("MetricsReport.manifest_hash: expected sha256 hex")
        if isinstance(self.n, bool) or not isinstance(self.n, int) or self.n < 1:
            raise SchemaError("MetricsReport.n: expected positive int")
        if not self.variants or any(v not in VARIANTS for v in self.variants):
            raise SchemaError("MetricsReport.variants: expected declared variants")
        metrics = _dict(self.metrics, "MetricsReport.metrics")
        _keys(metrics, "MetricsReport.metrics",
              ("base", "candidate", "delta", "delta_series"))
        for side in ("base", "candidate"):
            _keys(_dict(metrics[side], f"MetricsReport.metrics.{side}"),
                  f"MetricsReport.metrics.{side}", _METRIC_KEYS)
        _keys(_dict(metrics["delta"], "MetricsReport.metrics.delta"),
              "MetricsReport.metrics.delta", _DELTA_KEYS)
        _keys(_dict(metrics["delta_series"], "MetricsReport.metrics.delta_series"),
              "MetricsReport.metrics.delta_series", _SERIES_KEYS)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "mode": self.mode,
                "manifest_hash": self.manifest_hash, "n": self.n,
                "base": self.base, "candidate": self.candidate,
                "variants": list(self.variants), "ece_bins": self.ece_bins,
                "gate_min_n": self.gate_min_n, "metrics": dict(self.metrics)}

    @classmethod
    def from_dict(cls, value: Any) -> MetricsReport:
        obj = _dict(value, "MetricsReport")
        _keys(obj, "MetricsReport", ("schema", "mode", "manifest_hash", "n",
                                     "base", "candidate", "variants", "ece_bins",
                                     "gate_min_n", "metrics"))
        variants = obj["variants"]
        if not isinstance(variants, list):
            raise SchemaError("MetricsReport.variants: expected list")
        return cls(
            schema=obj["schema"], mode=obj["mode"],
            manifest_hash=_str(obj["manifest_hash"], "manifest_hash"),
            n=obj["n"], base=_str(obj["base"], "base"),
            candidate=_str(obj["candidate"], "candidate"),
            variants=tuple(_str(v, "variant") for v in variants),
            ece_bins=obj["ece_bins"], gate_min_n=obj["gate_min_n"],
            metrics=obj["metrics"],
        )

    def fingerprint(self) -> str:
        return digest(self.to_dict())

    def write(self, path: Any) -> None:
        from pathlib import Path

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical(self.to_dict()) + "\n", encoding="utf-8")


def _quantile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank quantile; q must be in (0, 1]."""
    if not 0.0 < q <= 1.0:
        raise SchemaError("quantile: q must be in (0, 1]")
    idx = max(0, math.ceil(q * len(sorted_values)) - 1)
    return sorted_values[idx]


def _ece(values: list[tuple[float, bool]], bins: int) -> float:
    """Expected calibration error with equal-width confidence bins."""
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for conf, correct in values:
        idx = min(bins - 1, int(conf * bins))
        buckets[idx].append((conf, correct))
    total = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        avg_conf = sum(c for c, _ in bucket) / len(bucket)
        avg_correct = sum(1 for _, ok in bucket if ok) / len(bucket)
        total += len(bucket) / len(values) * abs(avg_conf - avg_correct)
    return total


def _side(batch: RunBatch, specs: dict[str, TaskSpec], side: str,
          cfg: MetricsConfig) -> dict[str, Any]:
    outcomes = [(getattr(p, side), specs[p.instance_id]) for p in batch.pairs]
    n = len(outcomes)
    rule_ok = [o.rule == s.gold_rule for o, s in outcomes]
    action_ok = [o.action == s.gold_action for o, s in outcomes]
    gated = [(o, s) for o, s in outcomes if o.action in ("delete", "flag")]
    gate_n = len(gated)
    gate_hits = sum(1 for o, s in gated if s.gold_rule != "ok" or s.gold_jailbreak)
    if gate_n == 0:
        precision: float | None = None
        status = "no_gated_decisions"
    elif gate_n < cfg.gate_min_n:
        precision = None
        status = "insufficient_support"
    else:
        precision = gate_hits / gate_n
        status = "measured"
    lat = sorted(o.latency_ms for o, _ in outcomes)
    per_rule: dict[str, list[int]] = {}
    for o, s in outcomes:
        pair = per_rule.setdefault(o.rule, [0, 0])
        pair[0] += int(o.rule == s.gold_rule)
        pair[1] += 1
    return {
        "rule_acc": sum(rule_ok) / n,
        "action_acc": sum(action_ok) / n,
        "gate_precision": precision,
        "gate_n": gate_n,
        "gate_precision_status": status,
        "abstention_rate": sum(1 for o, _ in outcomes if o.abstained) / n,
        "ece": _ece([(o.confidence, ok) for (o, _), ok in zip(outcomes, rule_ok)],
                    cfg.ece_bins),
        "p50_ms": _quantile(lat, 0.5),
        "p95_ms": _quantile(lat, 0.95),
        "per_rule": per_rule,
        "mismatches": [p.instance_id for p in batch.pairs
                       if getattr(p, side).rule != specs[p.instance_id].gold_rule],
    }


def compute_metrics(batch: RunBatch, specs: list[TaskSpec],
                    cfg: MetricsConfig) -> MetricsReport:
    """Compute both sides and their deltas; never invent a missing metric."""
    by_id = {s.instance_id: s for s in specs}
    if len(by_id) != len(specs):
        raise SchemaError("duplicate task instance in spec list")
    expected = {p.instance_id for p in batch.pairs}
    if expected != set(by_id):
        raise SchemaError(f"spec/pair mismatch: only_pairs={sorted(expected - set(by_id))} "
                          f"only_specs={sorted(set(by_id) - expected)}")
    base = _side(batch, by_id, "base", cfg)
    candidate = _side(batch, by_id, "candidate", cfg)
    deltas: dict[str, float | None] = {}
    for name in _DELTA_KEYS:
        left, right = base[name], candidate[name]
        deltas[name] = None if left is None or right is None else right - left
    series: dict[str, list[float]] = {
        name: [] for name in _SERIES_KEYS
    }
    for pair in batch.pairs:
        gold = by_id[pair.instance_id]
        left, right = pair.base, pair.candidate
        series["rule_correct"].append(
            float(right.rule == gold.gold_rule) - float(left.rule == gold.gold_rule))
        series["action_correct"].append(
            float(right.action == gold.gold_action) - float(left.action == gold.gold_action))
        series["abstained"].append(float(right.abstained) - float(left.abstained))
        series["confidence"].append(right.confidence - left.confidence)
        series["latency_ms"].append(right.latency_ms - left.latency_ms)
    return MetricsReport(
        schema=1, mode="paired", manifest_hash=batch.manifest_hash, n=len(batch.pairs),
        base=batch.base, candidate=batch.candidate, variants=batch.variants,
        ece_bins=cfg.ece_bins, gate_min_n=cfg.gate_min_n,
        metrics={"base": base, "candidate": candidate, "delta": deltas,
                 "delta_series": series},
    )


__all__ = ["MetricsConfig", "MetricsReport", "compute_metrics"]
