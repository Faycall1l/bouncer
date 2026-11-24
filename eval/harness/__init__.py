"""P64 evaluation/decision harness contracts.

Every module in this package has an explicit schema: unknown keys are rejected,
missing required fields fail, and no producer silently substitutes a stub for a
model. The CLI lives in :mod:`eval.harness.cli`.
"""
from __future__ import annotations

from .manifest import DatasetManifest, SplitPin, build_manifest
from .schema import (
    ACTION_NAMES,
    VARIANTS,
    DecisionTrace,
    GoldPolicy,
    Outcome,
    PairOutcome,
    SchemaError,
    TaskSpec,
    digest,
)

__all__ = [
    "ACTION_NAMES",
    "VARIANTS",
    "DatasetManifest",
    "DecisionTrace",
    "GoldPolicy",
    "Outcome",
    "PairOutcome",
    "SchemaError",
    "SplitPin",
    "TaskSpec",
    "build_manifest",
    "digest",
]
