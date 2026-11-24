"""P64 evaluation/decision harness contracts.

Every module in this package has an explicit schema: unknown keys are rejected,
missing required fields fail, and no producer silently substitutes a stub for a
model. The CLI lives in :mod:`eval.harness.cli`.
"""
from __future__ import annotations

from .gates import Check, PairedEvidence, Verdict, evidence_gate, parity_gate
from .manifest import DatasetManifest, SplitPin, build_manifest
from .metrics import MetricsConfig, MetricsReport, compute_metrics
from .runner import RouterBinding, RunBatch, load_specs, path_for_cause, run_pairs
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
    "Check",
    "DatasetManifest",
    "DecisionTrace",
    "GoldPolicy",
    "MetricsConfig",
    "MetricsReport",
    "Outcome",
    "PairOutcome",
    "PairedEvidence",
    "RouterBinding",
    "RunBatch",
    "SchemaError",
    "SplitPin",
    "TaskSpec",
    "Verdict",
    "build_manifest",
    "compute_metrics",
    "digest",
    "evidence_gate",
    "load_specs",
    "parity_gate",
    "path_for_cause",
    "run_pairs",
]
