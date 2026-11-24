"""P64 evaluation/decision harness contracts.

Every module in this package has an explicit schema: unknown keys are rejected,
missing required fields fail, and no producer silently substitutes a stub for a
model. The CLI lives in :mod:`eval.harness.cli`.
"""
from __future__ import annotations

from .decision import (
    Decision,
    DecisionConfig,
    DecisionPolicy,
    PolicyComparisonReport,
    RunDecisions,
    Scenario,
    compare_runs,
    moderate_decision,
    run_scenarios,
)
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
from .stability import StabilityReport, run_twice, stability_gate

__all__ = [
    "ACTION_NAMES",
    "VARIANTS",
    "Check",
    "DatasetManifest",
    "Decision",
    "DecisionConfig",
    "DecisionPolicy",
    "DecisionTrace",
    "GoldPolicy",
    "MetricsConfig",
    "MetricsReport",
    "Outcome",
    "PairOutcome",
    "PairedEvidence",
    "PolicyComparisonReport",
    "RouterBinding",
    "RunBatch",
    "RunDecisions",
    "Scenario",
    "SchemaError",
    "SplitPin",
    "StabilityReport",
    "TaskSpec",
    "Verdict",
    "build_manifest",
    "compare_runs",
    "compute_metrics",
    "digest",
    "evidence_gate",
    "load_specs",
    "moderate_decision",
    "parity_gate",
    "path_for_cause",
    "run_pairs",
    "run_scenarios",
    "run_twice",
    "stability_gate",
]
