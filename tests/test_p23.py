"""P23 tests (T411-T430): release gates. No weights."""
import sys

sys.path.insert(0, "src")

import pytest

from gatekeeper.cli import main


def test_all_subcommand_helps():  # T414
    for cmd in (["check", "--help"], ["serve", "--help"], ["demo", "--help"],
                ["watch", "--help"], ["review", "--help"], ["stats", "--help"],
                ["export", "--help"], ["pack", "--help"]):
        with pytest.raises(SystemExit) as ei:
            main(cmd)
        assert ei.value.code == 0, cmd


def test_all_get_routes():  # T415
    from fastapi.testclient import TestClient

    import gatekeeper
    from gatekeeper import serve

    class S:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    gatekeeper._router = S()
    serve._BUCKETS.clear()
    client = TestClient(serve.app)
    for path in ("/health", "/version", "/models", "/stats", "/presets", "/metrics"):
        r = client.get(path)
        assert r.status_code == 200, path


def test_demo_import_without_gradio():  # T416
    import sys as _sys
    assert "gradio" not in _sys.modules, "import gradio only inside launch()"
    import gatekeeper.demo_app as _da
    assert callable(_da.launch) and callable(_da.parse_rules)
    import inspect
    assert "port" in inspect.signature(_da.launch).parameters


def test_eval_ece_golden():  # T417: import-safe (no router built) + golden value
    sys.path.insert(0, "eval")
    from eval_gatekeeper import ece
    assert ece([0.9, 0.9, 0.1, 0.1], [True, False, False, False]) == pytest.approx(0.25)


def test_audit_rotation(tmp_path):  # T418
    import os as _os

    import gatekeeper.audit as _au
    p = str(tmp_path / "audit.jsonl")
    old_path, old_max = _au._PATH, _au._MAX_BYTES
    _au._PATH, _au._MAX_BYTES = p, 50
    try:
        _au.log_decision("one", "ok", 0.9, "allow", 1.0)
        _au.log_decision("two", "ok", 0.9, "allow", 1.0)
        assert _os.path.exists(p + ".1")
    finally:
        _au._PATH, _au._MAX_BYTES = old_path, old_max
