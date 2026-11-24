"""P64 harness CLI: manifest, paired run, gates, and self-stability.

Every decision-affecting value is a required flag. In particular the CLI only
runs declared real routers; injected stubs are a Python-API capability for
tests and trace generation, never a silent substitute here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Direct execution (`python eval/harness/cli.py`) must resolve the same package
# as `python -m eval.harness.cli`. No import path is guessed at call sites.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "eval.harness"

from .gates import PairedEvidence, evidence_gate, parity_gate
from .manifest import DatasetManifest, build_manifest
from .runner import RouterBinding, load_specs, run_pairs
from .schema import GoldPolicy, SchemaError, canonical
from .stability import run_twice, stability_gate


def _json(path: str, label: str) -> dict[str, Any]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise SchemaError(f"{label}: expected JSON object")
    return obj


def _policy(path: str) -> GoldPolicy:
    return GoldPolicy.from_dict(_json(path, "policy"))


def _config(path: str) -> dict[str, Any]:
    return _json(path, "config")


def _variants(raw: str) -> tuple[str, ...]:
    parts = tuple(part for part in raw.split(",") if part)
    if not parts:
        raise SchemaError("--variants: expected a non-empty comma-separated list")
    return parts


def _manifest(path: str) -> DatasetManifest:
    return DatasetManifest.from_dict(_json(path, "manifest"))


def _real_binding(prefix: str, args: argparse.Namespace) -> RouterBinding:
    kind = getattr(args, f"{prefix}_kind")
    if kind != "real":
        raise SchemaError(f"--{prefix}-kind: CLI requires 'real'; "
                          "injected stubs use the Python API")
    return RouterBinding(
        name=getattr(args, f"{prefix}_name"), kind="real", source="model",
        attempts=getattr(args, f"{prefix}_attempts"),
        model=getattr(args, f"{prefix}_model"),
        device=getattr(args, f"{prefix}_device"), router=None,
    )


def _specs(args: argparse.Namespace, policy: GoldPolicy) -> list:
    return load_specs(
        args.data, dataset=args.dataset, split=args.split, policy=policy,
        config=_config(args.config), variants=_variants(args.variants))


def cmd_manifest(args: argparse.Namespace) -> int:
    man = build_manifest(
        args.data, dataset_id=args.dataset, split=args.split,
        policy=_json(args.policy, "policy"), config=_config(args.config),
        git_sha=args.git_sha, seed=args.seed,
    )
    man.write(args.out)
    print(json.dumps({"manifest": args.out, "sha256": man.fingerprint()}))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    base = _real_binding("base", args)
    candidate = _real_binding("candidate", args)
    man = _manifest(args.manifest)
    specs = _specs(args, _policy(args.policy))
    batch = run_pairs(
        specs, base=base, candidate=candidate,
        manifest_hash=man.fingerprint(), variants=_variants(args.variants),
    )
    batch.write(args.out)
    print(json.dumps({"run": args.out, "pairs": len(batch.pairs),
                      "decision_sha256": batch.decision_digest()}))
    return 0


def _evidence_from_args(args: argparse.Namespace) -> PairedEvidence:
    evidence = PairedEvidence.from_dict(_json(args.evidence, "evidence"))
    return evidence


def cmd_gate(args: argparse.Namespace) -> int:
    evidence = _evidence_from_args(args)
    specs = _specs(args, _policy(args.policy))
    variants = _variants(args.variants)
    parity = parity_gate(evidence, specs, variants=variants)
    support = evidence_gate(evidence, min_boot=args.min_boot, min_ci=args.min_ci)
    verdict = {"gate": "paired", "ok": parity.ok and support.ok,
               "parity": parity.to_dict(), "evidence": support.to_dict()}
    Path(args.out).write_text(canonical(verdict) + "\n", encoding="utf-8")
    print(json.dumps({"ok": verdict["ok"], "out": args.out,
                      "parity_passed": parity.passed,
                      "evidence_passed": support.passed}))
    return 0 if verdict["ok"] else 1


def cmd_stability(args: argparse.Namespace) -> int:
    base = _real_binding("base", args)
    candidate = _real_binding("candidate", args)
    man = _manifest(args.manifest)
    specs = _specs(args, _policy(args.policy))
    left, right = run_twice(
        specs, base=base, candidate=candidate,
        manifest_hash=man.fingerprint(), variants=_variants(args.variants),
    )
    report = stability_gate(left, right, manifest_hash=man.fingerprint())
    report.write(args.out)
    print(json.dumps({"ok": report.verdict.ok, "out": args.out,
                      "drift": len(report.drifted_instances)}))
    return 0 if report.verdict.ok else 1


def _add_data_spec(p: argparse.ArgumentParser) -> None:
    for name in ("data", "dataset", "split", "policy", "config"):
        p.add_argument(f"--{name}", required=True)


def _add_variants(p: argparse.ArgumentParser) -> None:
    p.add_argument("--variants", required=True)


def _add_bindings(p: argparse.ArgumentParser) -> None:
    for prefix in ("base", "candidate"):
        p.add_argument(f"--{prefix}-kind", choices=("real", "stub"), required=True)
        p.add_argument(f"--{prefix}-name", required=True)
        p.add_argument(f"--{prefix}-model", required=True)
        p.add_argument(f"--{prefix}-device", choices=("cpu", "cuda", "mps"),
                       required=True)
        p.add_argument(f"--{prefix}-attempts", type=int, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python eval/harness/cli.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("manifest")
    _add_data_spec(p)
    p.add_argument("--git-sha", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("run")
    _add_data_spec(p)
    _add_variants(p)
    _add_bindings(p)
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("gate")
    _add_data_spec(p)
    _add_variants(p)
    p.add_argument("--evidence", required=True)
    p.add_argument("--min-boot", type=int, required=True)
    p.add_argument("--min-ci", type=float, required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("stability")
    _add_data_spec(p)
    _add_variants(p)
    _add_bindings(p)
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_stability)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
