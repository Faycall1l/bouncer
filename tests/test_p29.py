"""P29 tests (T531-T550): CLI. No weights."""
import subprocess
import sys

sys.path.insert(0, "src")


def test_models_and_presets_commands():  # T538+T539
    r = subprocess.run([sys.executable, "-m", "gatekeeper.cli", "models"],
                       check=False, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"})
    assert r.returncode == 0 and "multilingual" in r.stdout and "pool:" in r.stdout
    r = subprocess.run([sys.executable, "-m", "gatekeeper.cli", "presets"],
                       check=False, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src"})
    assert r.returncode == 0 and "gaming" in r.stdout and "study" in r.stdout


def test_review_prune_and_filters(monkeypatch):  # T537+T540+T543
    import importlib

    import gatekeeper.review as _rv
    from gatekeeper.cli import main
    q = "/tmp/p29-review-test.jsonl"
    monkeypatch.setenv("BOUNCER_REVIEW", q)
    importlib.reload(_rv)
    _rv.clear_queue()
    _rv.add("p29 row one", {"action": "flag", "rule": "no-spam", "confidence": 0.9})
    _rv.add("p29 row two", {"action": "delete", "rule": "no-scams", "confidence": 0.95})
    assert main(["review", "--rule", "no-spam"]) == 0
    assert main(["review", "--prune", "--older-than", "-1"]) == 0  # everything aged out
    assert _rv.list_queue() == []
    _rv.clear_queue()


def test_export_action_filter(monkeypatch, tmp_path):  # T544
    import importlib

    import gatekeeper.audit as _au
    from gatekeeper.cli import main
    pa = str(tmp_path / "a.jsonl")
    monkeypatch.setenv("BOUNCER_AUDIT", pa)
    importlib.reload(_au)
    _au.log_decision("p29 allow msg", "ok", 0.9, "allow", 1.0)
    _au.log_decision("p29 bad msg", "no-spam", 0.95, "delete", 2.0)
    out = tmp_path / "only.csv"
    assert main(["export", "--out", str(out), "--action", "delete"]) == 0
    body = out.read_text().splitlines()
    assert len(body) == 2 and "delete" in body[1] and "allow" not in body[1]


def test_pack_init(tmp_path):  # T545+T878
    import json as _json

    from gatekeeper.cli import main
    f = str(tmp_path / "pack.json")
    assert main(["pack", "init", f, "--preset", "study"]) == 0
    doc = _json.loads((tmp_path / "pack.json").read_text())
    assert doc["meta"]["lang"] == "en" and len(doc["rules"]) >= 3  # T878: typed
    assert main(["pack", "init", f, "--preset", "study"]) == 4  # refuses overwrite
    assert main(["pack", "init", f, "--preset", "study", "--force"]) == 0


def test_serve_key_file(tmp_path, monkeypatch):  # T547
    import os
    import sys as _sys
    import types as _types

    from gatekeeper.cli import _cmd_serve

    class Args:
        host, port, workers, key_file = "127.0.0.1", 8000, 1, None
    fake = _types.ModuleType("uvicorn")
    fake.run = lambda *x, **k: None
    monkeypatch.setitem(_sys.modules, "uvicorn", fake)
    # setenv (not delenv) so monkeypatch records an undo even when the var
    # is absent — _cmd_serve writes os.environ directly, and without an undo
    # entry the key leaks into every later test in the session (it poisons
    # serve's import-time _KEY cache for subset runs).
    monkeypatch.setenv("BOUNCER_KEY", "")
    a = Args()
    a.key_file = str(tmp_path / "missing")
    assert _cmd_serve(a) == 4  # unreadable file, refuses to serve
    keyf = tmp_path / "key"
    keyf.write_text("  s3cret-key \n")
    a.key_file = str(keyf)
    assert _cmd_serve(a) == 0 and os.environ["BOUNCER_KEY"] == "s3cret-key"  # T609: right var
    empty = tmp_path / "empty"
    empty.write_text("")
    a.key_file = str(empty)
    assert _cmd_serve(a) == 4


def test_demo_preset_flag(capsys):  # T548
    import pytest

    from gatekeeper.cli import _demo

    class Args:
        port, share, preset = 7860, False, "nope"
    with pytest.raises(SystemExit) as ei:
        _demo(Args())
    assert ei.value.code == 4 and "unknown preset" in capsys.readouterr().err


def test_serve_cors_flag(monkeypatch):  # T549
    import os
    import sys as _sys
    import types as _types

    from gatekeeper.cli import _cmd_serve
    fake = _types.ModuleType("uvicorn")
    fake.run = lambda *x, **k: None
    monkeypatch.setitem(_sys.modules, "uvicorn", fake)
    monkeypatch.setenv("BOUNCER_CORS", "")  # undo entry even if absent (see T547 test note)

    class Args:
        host, port, workers, key_file = "127.0.0.1", 8000, 1, None
        cors = "https://a.example,https://b.example"
    assert _cmd_serve(Args()) == 0
    assert os.environ["BOUNCER_CORS"] == "https://a.example,https://b.example"


def test_cli_config_user_timeout(tmp_path, capsys):  # T531+T533+T550
    import json as _json

    import gatekeeper
    from gatekeeper.cli import main

    class S:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    gatekeeper._router = S()
    cfg = tmp_path / "cfg.json"
    cfg.write_text(_json.dumps({"allow_threshold": 0.9, "delete_threshold": 0.97,
                                "history_n": 3}))
    out = tmp_path / "pack.json"
    assert main(["pack", "init", str(out)]) == 0
    assert main(["check", "p29 sweep msg", "--rules", str(out),
                 "--config", str(cfg), "--user", "u1",
                 "--timeout", "5", "--json"]) == 0
    printed = capsys.readouterr().out
    res = _json.loads(printed[printed.index("{"):])  # --json prints one indented doc
    assert res["thresholds"] == {"allow": 0.9, "delete": 0.97}
    from gatekeeper import strikes as _st
    assert _st.standing("u1")["strikes"] >= 0
    _st.reset()


def test_watch_json_in(monkeypatch, capsys):  # T535+T542+T550
    import io

    import gatekeeper
    from gatekeeper.cli import main

    class S:
        def predict(self, state, questions):
            assert state.get("lang_hint") == "es"  # T541+T542: per-line lang
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95, "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
    gatekeeper._router = S()
    lines = '{"message": "p29 json msg", "user_id": "u2", "lang": "es"}\nnot json\n'
    monkeypatch.setattr("sys.stdin", io.StringIO(lines))
    assert main(["watch", "--preset", "es", "--json-in", "--user", "u1"]) == 0
    out = capsys.readouterr().out
    assert "p29 json msg" in out and "bad json" not in out


def test_export_json_format(monkeypatch, tmp_path):  # T536+T550
    import importlib
    import json as _json

    import gatekeeper.audit as _au
    from gatekeeper.cli import main
    monkeypatch.setenv("BOUNCER_AUDIT", str(tmp_path / "a.jsonl"))
    importlib.reload(_au)
    _au.log_decision("p29 json exp", "ok", 0.9, "allow", 1.5)
    out = tmp_path / "rows.json"
    assert main(["export", "--out", str(out), "--format", "json", "--limit", "1"]) == 0
    rows = _json.loads(out.read_text())
    import hashlib
    want = hashlib.sha256(b"p29 json exp").hexdigest()[:16]  # audit never stores raw text
    assert rows and rows[-1]["msg"] == want and rows[-1]["ms"] == 1.5
