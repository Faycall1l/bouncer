"""P18 tests (T311-T330): CLI flags + behaviors. No weights."""
import sys

sys.path.insert(0, "src")

import pytest

import gatekeeper
from gatekeeper.cli import main


class Stub:
    def __init__(self, choice="ok", conf=0.95):
        self.a = {"rule": {"choice": choice, "confidence": conf,
                           "probabilities": {choice: conf}},
                  "harm": {"score": "safe"}, "hype": {"score": "chill"},
                  "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}

    def predict(self, state, questions):
        self.seen = getattr(self, "seen", None) or []
        self.seen.append(state)
        return {"answers": self.a}


@pytest.fixture(autouse=True)
def _stub():
    gatekeeper._router = Stub()
    from gatekeeper.cache import CACHE
    CACHE.clear()
    yield


def test_check_flags(capsys):  # T311+T312+T313+T320+T329
    rc = main(["check", "p18 msg one", "--preset", "gaming", "--lang", "en",
               "--context", "u: hi", "--history", "2", "--quiet"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == "allow"


def test_check_bad_severity():  # T313
    with pytest.raises(SystemExit) as ei:
        main(["check", "hi", "--preset", "gaming", "--severity", "nope"])
    assert ei.value.code == 4


def test_fail_fast_rules(tmp_path, capsys):  # T314
    p = tmp_path / "rules.json"
    p.write_text('{"BAD ID!": "x"}')
    with pytest.raises(SystemExit) as ei:
        main(["check", "hi", "--rules", str(p)])
    assert ei.value.code == 4
    assert "bouncer:" in capsys.readouterr().err


def test_stats_modes(capsys):  # T315
    assert main(["stats"]) == 0
    assert "allow=" in capsys.readouterr().out
    assert main(["stats", "--json"]) == 0
    assert '"decisions"' in capsys.readouterr().out


def test_review_clear_needs_yes(capsys):  # T318
    assert main(["review", "--clear"]) == 4
    assert "bouncer:" in capsys.readouterr().err


def test_pack_modes(capsys):  # T319+T325
    assert main(["pack", "show", "--preset", "gaming", "--format", "lines"]) == 0
    assert ":" in capsys.readouterr().out.splitlines()[0]


def test_watch_totals(monkeypatch, capsys):  # T286+T328
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("hello one\nhello two\n"))
    assert main(["watch", "--preset", "gaming"]) == 0
    assert "totals:" in capsys.readouterr().err


def test_export_since(tmp_path):  # T316+T327
    import json as _json

    import gatekeeper.audit as _au
    p = tmp_path / "audit.jsonl"
    with open(p, "w") as f:
        f.write(_json.dumps({"t": 100, "msg": "a", "rule": "ok", "conf": 1.0,
                             "action": "allow", "ms": 1}) + "\n")
        f.write(_json.dumps({"t": 200, "msg": "b", "rule": "ok", "conf": 1.0,
                             "action": "allow", "ms": 3}) + "\n")
    old = _au._PATH
    _au._PATH = str(p)
    out = tmp_path / "out.csv"
    try:
        assert main(["export", "--out", str(out), "--since", "150"]) == 0
        rows = out.read_text().splitlines()
        assert len(rows) == 2  # header + 1 filtered row
    finally:
        _au._PATH = old
