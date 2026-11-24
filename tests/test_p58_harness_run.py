"""P58 tests (T1236-T1237): paired execution and derived metrics."""
import json

import pytest

from eval.harness.metrics import MetricsConfig, compute_metrics
from eval.harness.runner import (
    RouterBinding,
    load_specs,
    path_for_cause,
    run_pairs,
)
from eval.harness.schema import GoldPolicy, SchemaError

POLICY = GoldPolicy("delete", "allow", "delete", "escalate")
CONFIG = {"allow_threshold": 0.85, "delete_threshold": 0.85, "questions": 5}
MANIFEST = "a" * 64
VARIANTS = ("identity", "reversed_rules")


class FixedRouter:
    """Declares its answer; it does not guess from the message text."""

    def __init__(self, choice: str, confidence: float) -> None:
        self.choice = choice
        self.confidence = confidence

    def predict(self, state, questions, model=None):
        options = questions["rule"]["criteria"]
        dist = {name: (1.0 - self.confidence) / max(1, len(options) - 1)
                for name in options}
        dist[self.choice] = self.confidence
        return {"answers": {
            "rule": {"choice": self.choice, "confidence": self.confidence,
                     "probabilities": dist},
            "harm": {"score": "safe" if self.choice == "ok" else "suspicious",
                     "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0},
        }}


def _row() -> dict:
    return {
        "v": 1,
        "state": {
            "message": "ENDGAME SPOILER http://x.gg he dies lol",
            "history": ["a: hi"],
            "rules": {"no-spam": "no ads, links", "no-spoiler": "no plot spoilers"},
        },
        "labels": {"rule": "no-spoiler", "harm": "suspicious", "hype": "chill",
                   "jailbreak": False, "escalate": False},
    }


def _binding(name: str, choice: str, confidence: float) -> RouterBinding:
    return RouterBinding(
        name=name, kind="stub", source="model", attempts=1,
        model=None, device=None, router=FixedRouter(choice, confidence),
        notes=("declared stub",),
    )


def _specs(tmp_path):
    data = tmp_path / "rows.jsonl"
    data.write_text(json.dumps(_row()) + "\n")
    return load_specs(data, dataset="fixture", split="dev", policy=POLICY,
                      config=CONFIG, variants=VARIANTS)


def test_load_specs_expands_declared_variants(tmp_path):  # T1236
    specs = _specs(tmp_path)
    assert [s.variant for s in specs] == list(VARIANTS)
    assert specs[0].task_id == specs[1].task_id
    assert list(specs[1].rules) == ["no-spoiler", "no-spam"]
    with pytest.raises(SchemaError, match="variants"):
        load_specs(tmp_path / "rows.jsonl", dataset="fixture", split="dev",
                   policy=POLICY, config=CONFIG, variants=("identity", "identity"))


def test_paired_run_keeps_routers_and_variants_distinct(tmp_path):  # T1236
    specs = _specs(tmp_path)
    batch = run_pairs(
        specs, base=_binding("base", "no-spoiler", 0.93),
        candidate=_binding("candidate", "ok", 0.95),
        manifest_hash=MANIFEST, variants=VARIANTS,
    )
    assert len(batch.pairs) == 2
    assert {p.variant for p in batch.pairs} == set(VARIANTS)
    assert all(p.base.action == "delete" for p in batch.pairs)
    assert all(p.candidate.action == "allow" for p in batch.pairs)
    assert batch.decision_digest() == type(batch).from_dict(
        batch.to_dict()).decision_digest()
    assert len({p.instance_id for p in batch.pairs}) == 2


def test_cache_key_separates_model_identity():  # T1236
    from gatekeeper import CACHE

    args = ("msg", {"r": "t"}, 0.85, 0.9)
    assert CACHE.key(*args, model="base") != CACHE.key(*args, model="candidate")
    assert CACHE.key(*args, model=None) == CACHE.key(*args, model=None)


def test_real_binding_is_explicit_and_cause_paths_are_closed():  # T1236
    with pytest.raises(SchemaError, match="explicit model"):
        RouterBinding(name="r", kind="real", source="model", attempts=1,
                      model=None, device="cpu", router=None)
    with pytest.raises(SchemaError, match="device"):
        RouterBinding(name="r", kind="real", source="model", attempts=1,
                      model="/models/x", device="guess", router=None)
    assert path_for_cause("breaker-open: model down") == "FALLBACK"
    assert path_for_cause("violation delete: no-spam") == "VIOLATION_DELETE"
    with pytest.raises(SchemaError, match="undeclared cause"):
        path_for_cause("vibes")


def test_runner_refuses_an_engine_result_without_a_cause(tmp_path):  # T1236
    spec = _specs(tmp_path)[0]
    # Rules mention links and the message has none: the engine's fastpath
    # currently omits `cause`. The harness must surface that, not guess.
    fast = spec.__class__.from_dict({**spec.to_dict(),
                                     "message": "plain chat",
                                     "rules": {"no-spam": "no link"},
                                     "gold_rule": "ok", "gold_action": "allow",
                                     "variant": "identity"})
    with pytest.raises(SchemaError, match="no cause"):
        run_pairs([fast], base=_binding("base", "ok", 0.9),
                  candidate=_binding("candidate", "ok", 0.9),
                  manifest_hash=MANIFEST, variants=("identity",))


def test_metrics_are_derived_and_support_is_explicit(tmp_path):  # T1237
    specs = _specs(tmp_path)
    batch = run_pairs(
        specs, base=_binding("base", "no-spoiler", 0.93),
        candidate=_binding("candidate", "ok", 0.95),
        manifest_hash=MANIFEST, variants=VARIANTS,
    )
    report = compute_metrics(batch, specs, MetricsConfig(ece_bins=5, gate_min_n=1))
    assert report.n == 2
    assert report.metrics["base"]["rule_acc"] == 1.0
    assert report.metrics["candidate"]["rule_acc"] == 0.0
    assert report.metrics["delta"]["rule_acc"] == -1.0
    assert report.metrics["candidate"]["gate_precision"] is None
    assert report.metrics["candidate"]["gate_precision_status"] == "no_gated_decisions"
    assert report.manifest_hash == MANIFEST
    assert report.fingerprint() == type(report).from_dict(report.to_dict()).fingerprint()
