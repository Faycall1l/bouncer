"""P60 tests (T1240): self-stability gate and explicit harness CLI."""
import json
import subprocess
import sys
from pathlib import Path

from eval.harness.gates import PairedEvidence
from eval.harness.manifest import build_manifest
from eval.harness.metrics import MetricsConfig, compute_metrics
from eval.harness.runner import RouterBinding, load_specs, run_pairs
from eval.harness.schema import GoldPolicy, SchemaError, canonical
from eval.harness.stability import run_twice, stability_gate
from eval.harness.stats import paired_bootstrap, paired_deltas, sign_test

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
                         model=None, device=None, router=FixedRouter(choice, confidence))


def _fixture(tmp_path):
    row = {"v": 1,
           "state": {"message": "SPOILER http://x.gg he dies", "history": [],
                     "rules": {"no-spoiler": "no plot spoilers"}},
           "labels": {"rule": "no-spoiler", "harm": "suspicious", "hype": "chill",
                      "jailbreak": False, "escalate": False}}
    data = tmp_path / "one.jsonl"
    data.write_text(json.dumps(row) + "\n")
    variants = ("identity",)
    specs = load_specs(data, dataset="fixture", split="dev", policy=POLICY,
                       config=CONFIG, variants=variants)
    man = build_manifest(data, dataset_id="fixture", split="dev",
                         policy=POLICY.to_dict(), config=CONFIG,
                         git_sha="abc123", seed=7)
    return data, specs, man, variants


def _evidence(specs, man, variants) -> PairedEvidence:
    batch = run_pairs(specs, base=_binding("base", "no-spoiler", 0.93),
                      candidate=_binding("candidate", "ok", 0.95),
                      manifest_hash=man.fingerprint(), variants=variants)
    metrics = compute_metrics(batch, specs, MetricsConfig(ece_bins=4, gate_min_n=1))
    values, excluded = paired_deltas(metrics.metrics, "rule_correct")
    return PairedEvidence(
        schema=1, mode="paired", manifest=man, batch=batch, metrics=metrics,
        bootstrap=paired_bootstrap(values, metric="rule_correct", n_boot=200,
                                   ci=0.95, seed=7),
        sign_test=sign_test(values, metric="rule_correct"),
        excluded_deltas=tuple(excluded),
    )


def test_stability_gate_passes_identical_runs(tmp_path):  # T1240
    _data, specs, man, variants = _fixture(tmp_path)
    left, right = run_twice(specs, base=_binding("base", "no-spoiler", 0.93),
                            candidate=_binding("candidate", "ok", 0.95),
                            manifest_hash=man.fingerprint(), variants=variants)
    report = stability_gate(left, right, manifest_hash=man.fingerprint())
    assert report.verdict.ok, [c.name for c in report.verdict.checks if not c.ok]
    assert report.run_a_hash == report.run_b_hash
    assert report == type(report).from_dict(json.loads(json.dumps(report.to_dict())))


def test_stability_gate_detects_a_drifted_decision(tmp_path):  # T1240
    _data, specs, man, variants = _fixture(tmp_path)
    left, right = run_twice(specs, base=_binding("base", "no-spoiler", 0.93),
                            candidate=_binding("candidate", "ok", 0.95),
                            manifest_hash=man.fingerprint(), variants=variants)
    raw = right.to_dict()
    raw["pairs"][0]["candidate"]["action"] = "flag"
    drifted = type(right).from_dict(raw)
    report = stability_gate(left, drifted, manifest_hash=man.fingerprint())
    assert not report.verdict.ok
    assert report.drifted_instances == (left.pairs[0].instance_id,)
    assert "drift_count" in [c.name for c in report.verdict.checks if not c.ok]


def test_cli_manifest_and_gate_are_explicit(tmp_path):  # T1240
    data, specs, man, variants = _fixture(tmp_path)
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps(POLICY.to_dict()))
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(CONFIG))
    manifest_out = tmp_path / "manifest.json"
    cli = Path("eval/harness/cli.py")

    run = subprocess.run(
        [sys.executable, str(cli), "manifest", "--data", str(data),
         "--dataset", "fixture", "--split", "dev", "--policy", str(policy_file),
         "--config", str(config_file), "--git-sha", "abc123", "--seed", "7",
         "--out", str(manifest_out)],
        capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    assert json.loads(manifest_out.read_text()) == man.to_dict()

    evidence = _evidence(specs, man, variants)
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(canonical(evidence.to_dict()) + "\n")
    verdict_out = tmp_path / "verdict.json"
    run = subprocess.run(
        [sys.executable, str(cli), "gate", "--data", str(data),
         "--dataset", "fixture", "--split", "dev", "--policy", str(policy_file),
         "--config", str(config_file), "--variants", "identity",
         "--evidence", str(evidence_file), "--min-boot", "100", "--min-ci", "0.9",
         "--out", str(verdict_out)],
        capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    assert json.loads(verdict_out.read_text())["ok"] is True

    missing = subprocess.run(
        [sys.executable, str(cli), "manifest", "--data", str(data),
         "--dataset", "fixture", "--split", "dev", "--policy", str(policy_file),
         "--config", str(config_file), "--git-sha", "abc123"],
        capture_output=True, text=True, check=False)
    assert missing.returncode == 2  # argparse refuses missing --seed/--out


def test_cli_rejects_stub_substitutes(tmp_path):  # T1240
    data, _specs, _man, _variants = _fixture(tmp_path)
    from eval.harness.cli import build_parser

    args = build_parser().parse_args([
        "run", "--data", str(data), "--dataset", "fixture", "--split", "dev",
        "--policy", "p.json", "--config", "c.json", "--variants", "identity",
        "--base-kind", "stub", "--base-name", "base", "--base-model", "x",
        "--base-device", "cpu", "--base-attempts", "1",
        "--candidate-kind", "real", "--candidate-name", "candidate",
        "--candidate-model", "y", "--candidate-device", "cpu",
        "--candidate-attempts", "1", "--manifest", "m.json", "--out", "o.json",
    ])
    try:
        args.func(args)
    except SchemaError as exc:
        assert "CLI requires 'real'" in str(exc)
    else:
        raise AssertionError("stub substitute was accepted by the CLI")


def test_stability_report_rejects_unknown_fields(tmp_path):  # T1240
    _data, specs, man, variants = _fixture(tmp_path)
    left, right = run_twice(specs, base=_binding("base", "no-spoiler", 0.93),
                            candidate=_binding("candidate", "ok", 0.95),
                            manifest_hash=man.fingerprint(), variants=variants)
    report = stability_gate(left, right, manifest_hash=man.fingerprint())
    from eval.harness.stability import StabilityReport

    raw = report.to_dict()
    raw["extra"] = 1
    try:
        StabilityReport.from_dict(raw)
    except SchemaError as exc:
        assert "unknown keys" in str(exc)
    else:
        raise AssertionError("unknown field accepted")
