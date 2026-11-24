"""T1240: self-stability gate over two identical paired runs.

The same specs, bindings, and manifest are executed twice. The gate compares
timing-free decision digests; latency is recorded but never used as a hidden
retry trigger. A run that cannot be reproduced fails the gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .gates import Verdict, _add, _verdict
from .runner import RouterBinding, RunBatch, run_pairs
from .schema import (
    SchemaError,
    TaskSpec,
    _dict,
    _keys,
    _str,
    canonical,
)


@dataclass(frozen=True)
class StabilityReport:
    schema: int
    mode: str
    manifest_hash: str
    run_a_hash: str
    run_b_hash: str
    drifted_instances: tuple[str, ...]
    verdict: Verdict

    def __post_init__(self) -> None:
        if self.schema != 1:
            raise SchemaError("StabilityReport.schema: only 1 is supported")
        if self.mode != "stability":
            raise SchemaError("StabilityReport.mode: only stability is supported")
        for name in ("manifest_hash", "run_a_hash", "run_b_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 64:
                raise SchemaError(f"StabilityReport.{name}: expected sha256 hex")
        if any(not isinstance(x, str) for x in self.drifted_instances):
            raise SchemaError("StabilityReport.drifted_instances: expected strings")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "mode": self.mode,
                "manifest_hash": self.manifest_hash,
                "run_a_hash": self.run_a_hash, "run_b_hash": self.run_b_hash,
                "drifted_instances": list(self.drifted_instances),
                "verdict": self.verdict.to_dict()}

    @classmethod
    def from_dict(cls, value: Any) -> StabilityReport:
        obj = _dict(value, "StabilityReport")
        _keys(obj, "StabilityReport", ("schema", "mode", "manifest_hash",
                                       "run_a_hash", "run_b_hash",
                                       "drifted_instances", "verdict"))
        drift = obj["drifted_instances"]
        if not isinstance(drift, list):
            raise SchemaError("StabilityReport.drifted_instances: expected list")
        return cls(
            schema=obj["schema"], mode=obj["mode"],
            manifest_hash=obj["manifest_hash"], run_a_hash=obj["run_a_hash"],
            run_b_hash=obj["run_b_hash"],
            drifted_instances=tuple(_str(x, "instance") for x in drift),
            verdict=Verdict.from_dict(obj["verdict"]),
        )

    def write(self, path: Any) -> None:
        from pathlib import Path

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical(self.to_dict()) + "\n", encoding="utf-8")


def run_twice(specs: list[TaskSpec], *, base: RouterBinding,
              candidate: RouterBinding, manifest_hash: str,
              variants: tuple[str, ...]) -> tuple[RunBatch, RunBatch]:
    """Two independent calls to the same declared runner; no silent retry."""
    left = run_pairs(specs, base=base, candidate=candidate,
                     manifest_hash=manifest_hash, variants=variants)
    right = run_pairs(specs, base=base, candidate=candidate,
                      manifest_hash=manifest_hash, variants=variants)
    return left, right


def stability_gate(run_a: RunBatch, run_b: RunBatch, *,
                   manifest_hash: str) -> StabilityReport:
    """Fail if any timing-free decision changed between the two runs."""
    checks = []
    _add(checks, "manifest_hash", manifest_hash, run_a.manifest_hash)
    _add(checks, "manifest_hash_b", manifest_hash, run_b.manifest_hash)
    _add(checks, "variants", list(run_b.variants), list(run_a.variants))
    _add(checks, "pair_counts", len(run_b.pairs), len(run_a.pairs))
    ids_a = [p.instance_id for p in run_a.pairs]
    ids_b = [p.instance_id for p in run_b.pairs]
    _add(checks, "instance_ids", ids_b, ids_a)
    hash_a, hash_b = run_a.decision_digest(), run_b.decision_digest()
    _add(checks, "decision_hash", hash_b, hash_a)
    by_b = {p.instance_id: p for p in run_b.pairs}
    drift = [p.instance_id for p in run_a.pairs
             if p.instance_id not in by_b
             or p.base.decision_digest() != by_b[p.instance_id].base.decision_digest()
             or p.candidate.decision_digest()
             != by_b[p.instance_id].candidate.decision_digest()]
    _add(checks, "drift_count", 0, len(drift))
    _add(checks, "spec_hashes", True,
         all(p.spec_hash == by_b[p.instance_id].spec_hash
             for p in run_a.pairs if p.instance_id in by_b))
    return StabilityReport(
        schema=1, mode="stability", manifest_hash=manifest_hash,
        run_a_hash=hash_a, run_b_hash=hash_b,
        drifted_instances=tuple(drift), verdict=_verdict("stability", checks),
    )


__all__ = ["StabilityReport", "run_twice", "stability_gate"]
