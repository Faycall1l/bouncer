"""P59 tests (T1238-T1239): paired inference and fail-closed gates."""
import json
from dataclasses import replace

import pytest

from eval.harness.gates import (
    PairedEvidence,
    evidence_gate,
    parity_gate,
)
from eval.harness.manifest import build_manifest
from eval.harness.metrics import MetricsConfig, compute_metrics
from eval.harness.runner import RouterBinding, load_specs, run_pairs
from eval.harness.schema import GoldPolicy, SchemaError
from eval.harness.stats import (
    paired_bootstrap,
    paired_deltas,
    sign_test,
)

POLICY = GoldPolicy("delete", "allow", "delete", "escalate")
CONFIG = {"allow_threshold": 0.85, "delete_threshold": 0.85, "questions": 5}


class FixedRouter:
    def __init__(self, choice: str, confidence: float) -> None:
        self.choice = choice
        self.confidence = confidence

    def predict(self, state, questions, model=None):
        options = questions["rule"]["criteria"]
        dist = {k: (1.0 - self.confidence) / max(1, len(options) - 1)
                for k in options}
        dist[self.choice] = self.confidence
        return {"answers": {
            "rule": {"choice": self.choice, "confidence": self.confidence,
                     "probabilities": dist},
            "harm": {"score": "safe" if self.choice == "ok" else "suspicious",
                     "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0},
        }}


def _binding(name: str, choice: str, confidence: float) -> RouterBinding:
    return RouterBinding(name=name, kind="stub", source="model", attempts=1,
                         model=None, device=None,
                         router=FixedRouter(choice, confidence))


def _evidence(tmp_path):
    row = {
        "v": 1,
        "state": {"message": "SPOILER http://x.gg he dies", "history": [],
                  "rules": {"no-spoiler": "no plot spoilers"}},
        "labels": {"rule": "no-spoiler", "harm": "suspicious", "hype": "chill",
                   "jailbreak": False, "escalate": False},
    }
    data = tmp_path / "one.jsonl"
    data.write_text(json.dumps(row) + "\n")
    man = build_manifest(data, dataset_id="fixture", split="dev",
                         policy=POLICY.to_dict(), config=CONFIG,
                         git_sha="abc123", seed=7)
    variants = ("identity",)
    specs = load_specs(data, dataset="fixture", split="dev", policy=POLICY,
                       config=CONFIG, variants=variants)
    batch = run_pairs(specs, base=_binding("base", "no-spoiler", 0.93),
                      candidate=_binding("candidate", "ok", 0.95),
                      manifest_hash=man.fingerprint(), variants=variants)
    metrics = compute_metrics(batch, specs, MetricsConfig(ece_bins=4, gate_min_n=1))
    values, excluded = paired_deltas(metrics.metrics, "rule_correct")
    boot = paired_bootstrap(values, metric="rule_correct", n_boot=200,
                            ci=0.95, seed=7)
    sign = sign_test(values, metric="rule_correct")
    evidence = PairedEvidence(
        schema=1, mode="paired", manifest=man, batch=batch, metrics=metrics,
        bootstrap=boot, sign_test=sign, excluded_deltas=tuple(excluded),
    )
    return evidence, specs, variants


def test_bootstrap_and_sign_are_deterministic_and_explicit():  # T1238
    first = paired_bootstrap([-1.0, 0.0, 1.0], metric="rule_correct",
                             n_boot=500, ci=0.95, seed=42)
    second = paired_bootstrap([-1.0, 0.0, 1.0], metric="rule_correct",
                              n_boot=500, ci=0.95, seed=42)
    assert first == second
    assert first.lo <= first.mean <= first.hi
    with pytest.raises(SchemaError, match="n_boot"):
        paired_bootstrap([1.0], metric="x", n_boot=10, ci=0.95, seed=1)
    with pytest.raises(SchemaError, match="no deltas"):
        paired_bootstrap([], metric="x", n_boot=100, ci=0.95, seed=1)

    exact = sign_test([1.0, 1.0, 1.0], metric="rule_correct")
    assert (exact.wins, exact.losses, exact.ties) == (3, 0, 0)
    assert exact.p_two_sided == pytest.approx(0.25)
    with pytest.raises(SchemaError, match="no non-tied"):
        sign_test([0.0, 0.0], metric="rule_correct")


def test_paired_deltas_reports_exclusions_instead_of_dropping():  # T1238
    report = {"delta_series": {"confidence": [None, 0.2]}}
    values, excluded = paired_deltas(report, "confidence")
    assert values == [0.2] and excluded == ["0"]
    with pytest.raises(SchemaError, match="absent"):
        paired_deltas({"delta_series": {}}, "missing")


def test_parity_gate_passes_a_coherent_bundle(tmp_path):  # T1239
    evidence, specs, variants = _evidence(tmp_path)
    verdict = parity_gate(evidence, specs, variants=variants)
    assert verdict.ok, [c.name for c in verdict.checks if not c.ok]
    assert verdict.failed == 0
    assert verdict == type(verdict).from_dict(json.loads(json.dumps(verdict.to_dict())))


def test_parity_gate_fails_on_a_tampered_spec_hash(tmp_path):  # T1239
    evidence, specs, variants = _evidence(tmp_path)
    raw = evidence.batch.to_dict()
    raw["pairs"][0]["spec_hash"] = "b" * 64
    tampered = replace(evidence, batch=type(evidence.batch).from_dict(raw))
    verdict = parity_gate(tampered, specs, variants=variants)
    assert not verdict.ok
    assert "spec_hashes" in [c.name for c in verdict.checks if not c.ok]


def test_evidence_gate_is_fail_closed(tmp_path):  # T1239
    evidence, _specs, _variants = _evidence(tmp_path)
    assert evidence_gate(evidence, min_boot=100, min_ci=0.9).ok
    weak = evidence_gate(evidence, min_boot=1000, min_ci=0.9)
    assert not weak.ok
    assert "bootstrap_budget" in [c.name for c in weak.checks if not c.ok]
    broken = replace(evidence, excluded_deltas=("0",))
    assert not evidence_gate(broken, min_boot=100, min_ci=0.9).ok
