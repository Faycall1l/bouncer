"""T1239: fail-closed gates over a complete paired evidence bundle.

A missing field is a failed check, never a skip. The gates compare the raw
manifest, the run batch, the derived metrics, and the declared inference side
by hash and identity so a report cannot be assembled from two different runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .manifest import DatasetManifest
from .metrics import MetricsReport
from .runner import RunBatch
from .schema import (
    ACTION_NAMES,
    SOURCE_NAMES,
    SchemaError,
    TaskSpec,
    _bool,
    _dict,
    _keys,
    _str,
    canonical,
    digest,
)
from .stats import BootstrapInterval, SignTestResult


@dataclass(frozen=True)
class Check:
    name: str
    expected: str
    value: Any
    ok: bool

    def __post_init__(self) -> None:
        _str(self.name, "Check.name")
        _str(self.expected, "Check.expected")
        _bool(self.ok, "Check.ok")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "expected": self.expected,
                "value": self.value, "ok": self.ok}

    @classmethod
    def from_dict(cls, value: Any) -> Check:
        obj = _dict(value, "Check")
        _keys(obj, "Check", ("name", "expected", "value", "ok"))
        return cls(name=obj["name"], expected=obj["expected"],
                   value=obj["value"], ok=obj["ok"])


@dataclass(frozen=True)
class Verdict:
    gate: str
    checks: tuple[Check, ...]
    ok: bool
    passed: int
    failed: int

    def __post_init__(self) -> None:
        _str(self.gate, "Verdict.gate")
        _bool(self.ok, "Verdict.ok")
        if self.passed + self.failed != len(self.checks):
            raise SchemaError("Verdict: counts do not match checks")
        if self.ok != (self.failed == 0 and bool(self.checks)):
            raise SchemaError("Verdict: ok must mean all checks passed")

    def to_dict(self) -> dict[str, Any]:
        return {"gate": self.gate, "checks": [c.to_dict() for c in self.checks],
                "ok": self.ok, "passed": self.passed, "failed": self.failed}

    @classmethod
    def from_dict(cls, value: Any) -> Verdict:
        obj = _dict(value, "Verdict")
        _keys(obj, "Verdict", ("gate", "checks", "ok", "passed", "failed"))
        checks = obj["checks"]
        if not isinstance(checks, list):
            raise SchemaError("Verdict.checks: expected list")
        return cls(gate=obj["gate"],
                   checks=tuple(Check.from_dict(c) for c in checks),
                   ok=obj["ok"], passed=obj["passed"], failed=obj["failed"])


@dataclass(frozen=True)
class PairedEvidence:
    """Everything needed to audit one paired comparison, with no loose ends."""

    schema: int
    mode: str
    manifest: DatasetManifest
    batch: RunBatch
    metrics: MetricsReport
    bootstrap: BootstrapInterval
    sign_test: SignTestResult
    excluded_deltas: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema != 1:
            raise SchemaError("PairedEvidence.schema: only 1 is supported")
        if self.mode != "paired":
            raise SchemaError("PairedEvidence.mode: only paired is supported")
        if any(not isinstance(x, str) for x in self.excluded_deltas):
            raise SchemaError("PairedEvidence.excluded_deltas: expected strings")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "mode": self.mode,
                "manifest": self.manifest.to_dict(), "batch": self.batch.to_dict(),
                "metrics": self.metrics.to_dict(),
                "bootstrap": self.bootstrap.to_dict(),
                "sign_test": self.sign_test.to_dict(),
                "excluded_deltas": list(self.excluded_deltas)}

    @classmethod
    def from_dict(cls, value: Any) -> PairedEvidence:
        obj = _dict(value, "PairedEvidence")
        _keys(obj, "PairedEvidence", ("schema", "mode", "manifest", "batch",
                                      "metrics", "bootstrap", "sign_test",
                                      "excluded_deltas"))
        excluded = obj["excluded_deltas"]
        if not isinstance(excluded, list):
            raise SchemaError("PairedEvidence.excluded_deltas: expected list")
        return cls(
            schema=obj["schema"], mode=obj["mode"],
            manifest=DatasetManifest.from_dict(obj["manifest"]),
            batch=RunBatch.from_dict(obj["batch"]),
            metrics=MetricsReport.from_dict(obj["metrics"]),
            bootstrap=BootstrapInterval.from_dict(obj["bootstrap"]),
            sign_test=SignTestResult.from_dict(obj["sign_test"]),
            excluded_deltas=tuple(_str(x, "excluded") for x in excluded),
        )

    def fingerprint(self) -> str:
        return digest(self.to_dict())

    def write(self, path: Any) -> None:
        from pathlib import Path

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical(self.to_dict()) + "\n", encoding="utf-8")


def _verdict(gate: str, checks: list[Check]) -> Verdict:
    passed = sum(1 for c in checks if c.ok)
    return Verdict(gate=gate, checks=tuple(checks), ok=passed == len(checks) and bool(checks),
                   passed=passed, failed=len(checks) - passed)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def _add(checks: list[Check], name: str, expected: Any, value: Any) -> None:
    want, got = _jsonable(expected), _jsonable(value)
    ok = got is not None and got == want
    checks.append(Check(name=name, expected=repr(want), value=got, ok=bool(ok)))


def parity_gate(evidence: PairedEvidence, specs: list[TaskSpec], *,
                variants: tuple[str, ...]) -> Verdict:
    """Check that every artifact describes the same run, or fail."""
    checks: list[Check] = []
    batch = evidence.batch
    manifest = evidence.manifest
    metrics = evidence.metrics
    by_id = {s.instance_id: s for s in specs}
    _add(checks, "manifest_hash", manifest.fingerprint(), batch.manifest_hash)
    _add(checks, "metrics_manifest_hash", batch.manifest_hash,
         metrics.manifest_hash)
    expected_n = manifest.split.n * len(variants)
    _add(checks, "pair_count", expected_n, len(batch.pairs))
    _add(checks, "spec_count", expected_n, len(specs))
    _add(checks, "metrics_n", len(batch.pairs), metrics.n)
    _add(checks, "metrics_mode", "paired", metrics.mode)
    _add(checks, "batch_mode", "paired", batch.mode)
    _add(checks, "variants", tuple(variants), batch.variants)
    _add(checks, "metrics_variants", tuple(variants), metrics.variants)

    instance_ids = {p.instance_id for p in batch.pairs}
    _add(checks, "instance_ids", set(by_id), instance_ids)
    _add(checks, "spec_hashes", True,
         all(p.spec_hash == by_id[p.instance_id].fingerprint()
             for p in batch.pairs if p.instance_id in by_id) and
         len(instance_ids) == len(batch.pairs))
    _add(checks, "config_hashes", True,
         all(p.config_hash == manifest.config_hash
             == by_id[p.instance_id].config_fingerprint()
             for p in batch.pairs if p.instance_id in by_id))
    _add(checks, "router_names", True,
         batch.base != batch.candidate
         and all(p.base.router == batch.base and p.candidate.router == batch.candidate
                 for p in batch.pairs))
    _add(checks, "closed_outcomes", True,
         all(p.base.action in ACTION_NAMES and p.candidate.action in ACTION_NAMES
             and p.base.trace.source in SOURCE_NAMES
             and p.candidate.trace.source in SOURCE_NAMES
             and bool(p.base.trace.cause) and bool(p.candidate.trace.cause)
             for p in batch.pairs))
    coverage = {task: sorted({s.variant for s in specs if s.task_id == task})
                for task in {s.task_id for s in specs}}
    _add(checks, "variant_coverage", True,
         all(value == sorted(variants) for value in coverage.values()))
    return _verdict("parity", checks)


def evidence_gate(evidence: PairedEvidence, *, min_boot: int,
                  min_ci: float) -> Verdict:
    """Check that inference was declared, seeded, and reported honestly."""
    checks: list[Check] = []
    boot = evidence.bootstrap
    sign = evidence.sign_test
    _add(checks, "bootstrap_budget", True,
         isinstance(boot.n_boot, int) and boot.n_boot >= min_boot)
    _add(checks, "bootstrap_ci", True, boot.ci >= min_ci)
    _add(checks, "bootstrap_seed_declared", True, isinstance(boot.seed, int))
    _add(checks, "bootstrap_coverage", evidence.metrics.n,
         boot.n + len(evidence.excluded_deltas))
    _add(checks, "sign_method", "exact", sign.method)
    _add(checks, "sign_metric", boot.metric, sign.metric)
    _add(checks, "sign_support", True, sign.wins + sign.losses > 0)
    _add(checks, "sign_ties_counted", evidence.metrics.n,
         sign.wins + sign.losses + sign.ties)
    return _verdict("evidence", checks)


__all__ = ["Check", "PairedEvidence", "Verdict", "evidence_gate", "parity_gate"]
