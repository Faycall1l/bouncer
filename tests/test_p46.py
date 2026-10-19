"""P46 tests (T871-T890): CLI, rules, storage. All network is stubbed."""
import json
import sys

sys.path.insert(0, "src")

from gatekeeper.cli import main


def test_config_validate_lints_toml_and_gate_json(tmp_path, monkeypatch,
                                                  capsys):  # T871
    """`bouncer config validate` lints both config kinds standalone: the
    default bouncer.toml (absent is fine), a named file (must exist), broken
    TOML as E_ADAPTER, and gate JSON through GateConfig.from_dict + validate
    — unknown keys, bad ranges, wrong shape and malformed JSON all fail the
    line. 0 all valid, 1 any failure, 2 a bare `config`."""
    monkeypatch.delenv("BOUNCER_CONFIG", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    # no file at all: the default target is absent, defaults are fine
    assert main(["config", "validate"]) == 0
    assert "ok: bouncer.toml absent (defaults)" in capsys.readouterr().out

    # a valid adapter TOML passes the default lint by name
    (work / "bouncer.toml").write_text('[adapters.telegram]\ntoken = "x"\n')
    assert main(["config", "validate"]) == 0
    assert "ok: bouncer.toml\n" in capsys.readouterr().out

    # broken TOML fails the line with E_ADAPTER, the file named
    bad = work / "bad.toml"
    bad.write_text("nope = [unclosed\n")
    assert main(["config", "validate", "--toml", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "fail:" in out and "E_ADAPTER" in out, out

    # a named file that doesn't exist is a failure, not the absent-default
    assert main(["config", "validate", "--toml", str(work / "nope.toml")]) == 1
    assert "no such file" in capsys.readouterr().out

    # gate JSON: the valid shape passes from_dict + validate
    good = work / "good.json"
    good.write_text(json.dumps({"allow_threshold": 0.9, "timeout_s": 5.0}))
    assert main(["config", "validate", "--json", str(good)]) == 0
    assert f"ok: {good}\n" in capsys.readouterr().out

    # each failure class fails its own line
    (work / "extra.json").write_text(json.dumps({"warp": 9}))
    assert main(["config", "validate", "--json", str(work / "extra.json")]) == 1
    assert "E_CONFIG" in capsys.readouterr().out, "unknown keys (T289)"
    (work / "range.json").write_text(json.dumps({"allow_threshold": 3.0}))
    assert main(["config", "validate", "--json", str(work / "range.json")]) == 1
    assert "must be in [0, 1]" in capsys.readouterr().out, "range (T253)"
    (work / "shape.json").write_text("[1, 2]")
    assert main(["config", "validate", "--json", str(work / "shape.json")]) == 1
    assert "E_CONFIG" in capsys.readouterr().out, "not an object"
    (work / "broken.json").write_text("{not json")
    assert main(["config", "validate", "--json", str(work / "broken.json")]) == 1
    assert "not valid JSON" in capsys.readouterr().out
    assert main(["config", "validate", "--json", str(work / "absent.json")]) == 1
    assert "no such file" in capsys.readouterr().out

    # both targets in one run: one line each, any failure fails the run
    assert main(["config", "validate", "--toml", str(bad),
                 "--json", str(good)]) == 1
    out = capsys.readouterr().out
    assert "fail:" in out and f"ok: {good}" in out

    # a bare `config` is a usage error, not a crash
    assert main(["config"]) == 2
    assert "validate" in capsys.readouterr().err
