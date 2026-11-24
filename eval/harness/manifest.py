"""T1235: content-hashed dataset manifest with declared split provenance.

A manifest is the unit of reproducibility for a paired run. It pins the raw
file bytes, the canonical hash of every row, the gold-label policy, the gate
config, and the git commit. No field is inferred at read time: a manifest that
does not carry all of them is rejected.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import SchemaError, _dict, _keys, _str, canonical, digest


@dataclass(frozen=True)
class SplitPin:
    name: str
    n: int
    rows_sha256: str

    def __post_init__(self) -> None:
        _str(self.name, "SplitPin.name")
        if isinstance(self.n, bool) or not isinstance(self.n, int) or self.n < 1:
            raise SchemaError("SplitPin.n: expected positive int")
        if not isinstance(self.rows_sha256, str) or len(self.rows_sha256) != 64:
            raise SchemaError("SplitPin.rows_sha256: expected sha256 hex")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "n": self.n, "rows_sha256": self.rows_sha256}

    @classmethod
    def from_dict(cls, value: Any) -> SplitPin:
        obj = _dict(value, "SplitPin")
        _keys(obj, "SplitPin", ("name", "n", "rows_sha256"))
        return cls(name=obj["name"], n=obj["n"], rows_sha256=obj["rows_sha256"])


@dataclass(frozen=True)
class DatasetManifest:
    schema: int
    dataset_id: str
    split: SplitPin
    file_sha256: str
    policy_hash: str
    config_hash: str
    git_sha: str
    seed: int

    def __post_init__(self) -> None:
        if self.schema != 1:
            raise SchemaError("DatasetManifest.schema: only 1 is supported")
        _str(self.dataset_id, "DatasetManifest.dataset_id")
        if not isinstance(self.file_sha256, str) or len(self.file_sha256) != 64:
            raise SchemaError("DatasetManifest.file_sha256: expected sha256 hex")
        for name in ("policy_hash", "config_hash"):
            v = getattr(self, name)
            if not isinstance(v, str) or len(v) != 64:
                raise SchemaError(f"DatasetManifest.{name}: expected sha256 hex")
        _str(self.git_sha, "DatasetManifest.git_sha")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise SchemaError("DatasetManifest.seed: expected int")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "dataset_id": self.dataset_id,
                "split": self.split.to_dict(), "file_sha256": self.file_sha256,
                "policy_hash": self.policy_hash, "config_hash": self.config_hash,
                "git_sha": self.git_sha, "seed": self.seed}

    @classmethod
    def from_dict(cls, value: Any) -> DatasetManifest:
        obj = _dict(value, "DatasetManifest")
        _keys(obj, "DatasetManifest", ("schema", "dataset_id", "split",
                                       "file_sha256", "policy_hash", "config_hash",
                                       "git_sha", "seed"))
        return cls(
            schema=obj["schema"],
            dataset_id=_str(obj["dataset_id"], "DatasetManifest.dataset_id"),
            split=SplitPin.from_dict(obj["split"]),
            file_sha256=obj["file_sha256"], policy_hash=obj["policy_hash"],
            config_hash=obj["config_hash"], git_sha=obj["git_sha"],
            seed=obj["seed"],
        )

    def fingerprint(self) -> str:
        return digest(self.to_dict())

    def write(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical(self.to_dict()) + "\n", encoding="utf-8")


def build_manifest(path: str | Path, *, dataset_id: str, split: str,
                   policy: dict[str, Any], config: dict[str, Any],
                   git_sha: str, seed: int) -> DatasetManifest:
    """Hash a JSONL dataset and its declared evaluation context.

    `split` is required even when the file name already suggests one: a split
    label is provenance, not a guess from a path. `git_sha` and `seed` are also
    required so a manifest can never claim reproducibility it does not have.
    """
    source = Path(path)
    raw = source.read_bytes()
    rows_sha = hashlib.sha256()
    n = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise SchemaError(f"{source}:{n + 1}: invalid JSON") from exc
        obj = _dict(row, f"{source}:{n + 1}")
        _keys(obj, f"{source}:{n + 1}", ("v", "state", "labels"), ("id", "split"))
        if "split" in obj and obj["split"] != split:
            raise SchemaError(f"{source}:{n + 1}: row split does not match declared split")
        rows_sha.update(canonical(obj).encode("utf-8"))
        rows_sha.update(b"\n")
        n += 1
    if n == 0:
        raise SchemaError(f"{source}: empty dataset")
    return DatasetManifest(
        schema=1, dataset_id=dataset_id,
        split=SplitPin(name=split, n=n, rows_sha256=rows_sha.hexdigest()),
        file_sha256=hashlib.sha256(raw).hexdigest(),
        policy_hash=digest(policy), config_hash=digest(config),
        git_sha=git_sha, seed=seed,
    )
