"""T1236: paired runner over identical task specs.

Each router is an explicit binding: a stub callable supplied by the caller, or
a real Router resolved with a declared device and model path. There is no
"try the stub if the model is missing" path. The model string also enters the
engine cache key (T1236 in src/gatekeeper/cache.py), so two routers cannot
answer each other's cached requests.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import (
    SOURCE_NAMES,
    VARIANTS,
    GoldPolicy,
    Outcome,
    PairOutcome,
    SchemaError,
    TaskSpec,
    _dict,
    _keys,
    _str,
    canonical,
    digest,
)

_DEVICES = ("cpu", "cuda", "mps")
# Cause -> declared gate path. Unknown causes are errors, not guesses.
_CAUSE_PATHS = (
    ("jailbreak", "JAILBREAK"),
    ("needs-human", "NEEDS_HUMAN"),
    ("escalate", "NEEDS_HUMAN"),
    ("breaker-open", "FALLBACK"),
    ("fallback", "FALLBACK"),
    ("batch-deadline", "FALLBACK"),
    ("margin", "MARGIN"),
    ("quiet", "QUIET"),
    ("low-conf", "LOW_CONF"),
    ("suspected", "SUSPECTED_FLAG"),
    ("flag", "SUSPECTED_FLAG"),
    ("violation", "VIOLATION_DELETE"),
    ("delete", "VIOLATION_DELETE"),
    ("ok", "CALM_ALLOW"),
    ("allow", "CALM_ALLOW"),
    ("empty", "EMPTY"),
    ("fastpath", "FASTPATH"),
)


def path_for_cause(cause: str) -> str:
    low = cause.lower()
    for prefix, path in _CAUSE_PATHS:
        if low.startswith(prefix):
            return path
    raise SchemaError(f"undeclared cause path: {cause!r}")


@dataclass(frozen=True)
class RouterBinding:
    """A caller-declared router and the path it is expected to take."""

    name: str
    kind: str
    source: str
    attempts: int
    model: str | None
    device: str | None
    router: Any
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _str(self.name, "RouterBinding.name")
        if not self.name:
            raise SchemaError("RouterBinding.name: empty")
        if self.kind not in ("stub", "real"):
            raise SchemaError("RouterBinding.kind: expected stub or real")
        if self.source not in SOURCE_NAMES:
            raise SchemaError("RouterBinding.source: unknown decision source")
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int) \
                or self.attempts < 1:
            raise SchemaError("RouterBinding.attempts: expected positive int")
        if self.kind == "stub":
            if self.router is None:
                raise SchemaError("RouterBinding: stub requires an explicit callable")
            if self.model is not None or self.device is not None:
                raise SchemaError("RouterBinding: stub cannot declare model/device")
        else:
            if self.router is not None:
                raise SchemaError("RouterBinding: real router must be resolved, not passed")
            if not isinstance(self.model, str) or not self.model:
                raise SchemaError("RouterBinding: real requires an explicit model")
            if self.device not in _DEVICES:
                raise SchemaError("RouterBinding.device: expected cpu/cuda/mps")
        if any(not isinstance(x, str) for x in self.notes):
            raise SchemaError("RouterBinding.notes: expected strings")

    @property
    def identity(self) -> str:
        """Value passed to moderate(model=...) and therefore to the cache key."""
        return self.model if self.kind == "real" else f"stub:{self.name}"

    def resolve(self) -> Any:
        if self.kind == "stub":
            return self.router
        from gatekeeper import get_router  # imported only for a declared real run
        return get_router(device=self.device)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "source": self.source,
                "attempts": self.attempts, "model": self.model,
                "device": self.device, "notes": list(self.notes)}

    @classmethod
    def from_dict(cls, value: Any, *, router: Any = None) -> RouterBinding:
        obj = _dict(value, "RouterBinding")
        _keys(obj, "RouterBinding", ("name", "kind", "source", "attempts",
                                     "model", "device", "notes"))
        notes = obj["notes"]
        if not isinstance(notes, list):
            raise SchemaError("RouterBinding.notes: expected list")
        return cls(
            name=obj["name"], kind=obj["kind"], source=obj["source"],
            attempts=obj["attempts"], model=obj["model"], device=obj["device"],
            router=router, notes=tuple(_str(x, "note") for x in notes),
        )


@dataclass(frozen=True)
class RunBatch:
    """All paired outcomes from one run over one pinned manifest."""

    schema: int
    mode: str
    manifest_hash: str
    variants: tuple[str, ...]
    base: str
    candidate: str
    pairs: tuple[PairOutcome, ...]

    def __post_init__(self) -> None:
        if self.schema != 1:
            raise SchemaError("RunBatch.schema: only 1 is supported")
        if self.mode != "paired":
            raise SchemaError("RunBatch.mode: only paired is supported")
        if not isinstance(self.manifest_hash, str) or len(self.manifest_hash) != 64:
            raise SchemaError("RunBatch.manifest_hash: expected sha256 hex")
        if not self.variants or any(v not in VARIANTS for v in self.variants):
            raise SchemaError("RunBatch.variants: expected declared variants")
        if not self.pairs:
            raise SchemaError("RunBatch.pairs: empty run")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "mode": self.mode,
                "manifest_hash": self.manifest_hash,
                "variants": list(self.variants), "base": self.base,
                "candidate": self.candidate,
                "pairs": [p.to_dict() for p in self.pairs]}

    @classmethod
    def from_dict(cls, value: Any) -> RunBatch:
        obj = _dict(value, "RunBatch")
        _keys(obj, "RunBatch", ("schema", "mode", "manifest_hash", "variants",
                                "base", "candidate", "pairs"))
        variants = obj["variants"]
        if not isinstance(variants, list):
            raise SchemaError("RunBatch.variants: expected list")
        pairs = obj["pairs"]
        if not isinstance(pairs, list):
            raise SchemaError("RunBatch.pairs: expected list")
        return cls(
            schema=obj["schema"], mode=obj["mode"],
            manifest_hash=_str(obj["manifest_hash"], "RunBatch.manifest_hash"),
            variants=tuple(_str(v, "variant") for v in variants),
            base=_str(obj["base"], "RunBatch.base"),
            candidate=_str(obj["candidate"], "RunBatch.candidate"),
            pairs=tuple(PairOutcome.from_dict(p) for p in pairs),
        )

    def decision_digest(self) -> str:
        """Timing-free digest used by the self-stability gate."""
        body = [{
            "instance_id": p.instance_id, "spec_hash": p.spec_hash,
            "base": p.base.decision_digest(),
            "candidate": p.candidate.decision_digest(),
        } for p in self.pairs]
        return digest(body)

    def write(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical(self.to_dict()) + "\n", encoding="utf-8")


def load_specs(path: str | Path, *, dataset: str, split: str, policy: GoldPolicy,
               config: dict[str, Any], variants: tuple[str, ...]) -> list[TaskSpec]:
    """Read a JSONL dataset into one task per declared variant."""
    if not variants or any(v not in VARIANTS for v in variants) \
            or len(set(variants)) != len(variants):
        raise SchemaError("variants: expected distinct declared variants")
    specs: list[TaskSpec] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise SchemaError(f"{path}:{line_no}: invalid JSON") from exc
            base = TaskSpec.from_data_row(
                row, dataset=dataset, split=split, policy=policy, config=config)
            for variant in variants:
                spec = base.with_variant(variant)
                if spec.instance_id in seen:
                    raise SchemaError(f"duplicate task instance {spec.instance_id}")
                seen.add(spec.instance_id)
                specs.append(spec)
    if not specs:
        raise SchemaError(f"{path}: no task rows")
    return specs


def _validate(specs: list[TaskSpec], variants: tuple[str, ...],
              bindings: tuple[RouterBinding, RouterBinding],
              manifest_hash: str) -> None:
    if not specs:
        raise SchemaError("no tasks supplied")
    if not isinstance(manifest_hash, str) or len(manifest_hash) != 64:
        raise SchemaError("manifest_hash: expected sha256 hex")
    if bindings[0].name == bindings[1].name:
        raise SchemaError("base and candidate routers must have distinct names")
    configs = {s.config_fingerprint() for s in specs}
    if len(configs) != 1:
        raise SchemaError("specs do not share one config fingerprint")
    by_task: dict[str, set[str]] = {}
    for spec in specs:
        by_task.setdefault(spec.task_id, set()).add(spec.variant)
    for task_id, got in by_task.items():
        if got != set(variants):
            raise SchemaError(f"{task_id}: variant coverage {sorted(got)} != "
                              f"{sorted(variants)}")


def _outcome(spec: TaskSpec, binding: RouterBinding, router: Any) -> Outcome:
    from gatekeeper import GateConfig, moderate  # imported per declared run

    cfg = GateConfig.from_dict(spec.config)
    result = moderate(
        spec.message, spec.rules, context=list(spec.history), config=cfg,
        lang=spec.lang, router=router, model=binding.identity,
        rid=f"{spec.instance_id}:{binding.name}",
    )
    cause = result.get("cause")
    if not isinstance(cause, str) or not cause:
        raise SchemaError(f"{binding.name}/{spec.instance_id}: engine returned no cause")
    return Outcome.from_moderate(
        binding.name, result, source=binding.source,
        decision_path=path_for_cause(cause), attempts=binding.attempts,
        fallback_cause=cause if binding.source == "fallback" else None,
        notes=binding.notes,
    )


def run_pairs(specs: list[TaskSpec], *, base: RouterBinding,
              candidate: RouterBinding, manifest_hash: str,
              variants: tuple[str, ...]) -> RunBatch:
    """Run both routers on every task instance with identical state and config."""
    _validate(specs, variants, (base, candidate), manifest_hash)
    order = {v: i for i, v in enumerate(variants)}
    ordered = sorted(specs, key=lambda s: (s.task_id, order[s.variant]))
    base_router = base.resolve()
    candidate_router = candidate.resolve()
    pairs: list[PairOutcome] = []
    for spec in ordered:
        left = _outcome(spec, base, base_router)
        right = _outcome(spec, candidate, candidate_router)
        pairs.append(PairOutcome(
            task_id=spec.task_id, instance_id=spec.instance_id,
            variant=spec.variant, spec_hash=spec.fingerprint(),
            config_hash=spec.config_fingerprint(), base=left, candidate=right,
        ))
    return RunBatch(
        schema=1, mode="paired", manifest_hash=manifest_hash,
        variants=tuple(variants), base=base.name, candidate=candidate.name,
        pairs=tuple(pairs),
    )


__all__ = [
    "RouterBinding", "RunBatch", "load_specs", "path_for_cause", "run_pairs",
]
