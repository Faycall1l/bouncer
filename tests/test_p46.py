"""P46 tests (T871-T890): CLI, rules, storage. All network is stubbed."""
import json
import sys
from pathlib import Path

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


def test_pack_diff_reports_added_removed_changed(tmp_path, capsys):  # T872
    """pack diff compares two packs: added (+), removed (-) and changed (~)
    rules each on their own line, an exact match says so and exits 0, any
    drift exits 2 — while missing/unreadable/non-object files keep the
    hardened T786 exits and messages."""
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"spam": "no spam", "hate": "no hate",
                             "old": "legacy rule"}))
    b.write_text(json.dumps({"spam": "no spam at all", "hate": "no hate",
                             "new": "fresh rule"}))

    assert main(["pack", "diff", str(a), str(b)]) == 2, "drift exits 2"
    out = capsys.readouterr().out
    assert "+ new: fresh rule" in out, out
    assert "- old: legacy rule" in out, out
    assert "~ spam: 'no spam' -> 'no spam at all'" in out, out
    assert "+1 -1 ~1" in out, out
    assert "hate" not in out, "unchanged rules stay quiet"

    assert main(["pack", "diff", str(a), str(a)]) == 0
    assert "packs identical: 3 rules" in capsys.readouterr().out

    # one file is not a diff
    assert main(["pack", "diff", str(a)]) == 4
    assert "two files" in capsys.readouterr().err
    # missing and unreadable files keep the hardened read (T786)
    assert main(["pack", "diff", str(tmp_path / "nope.json"), str(b)]) == 4
    assert "no pack file" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    assert main(["pack", "diff", str(bad), str(b)]) == 4
    assert "cannot read pack" in capsys.readouterr().err
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2]")
    assert main(["pack", "diff", str(arr), str(b)]) == 4
    assert "is not a rules object" in capsys.readouterr().err
    # the same hardened read drives pack lint's --rules path
    assert main(["pack", "lint", "--rules", str(arr)]) == 4
    assert "is not a rules object" in capsys.readouterr().err


def test_pack_sign_and_verify_roundtrip(tmp_path, capsys):  # T873
    """sign writes a sha256 manifest over sorted ids+text — key order never
    changes the digest — verify recomputes and matches; a missing or
    unreadable manifest fails coded (E_PACK_SIG, exit 4). Content tamper
    itself is T888's byte-flip test."""
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({"spam": "no spam", "hate": "no hate"}))

    assert main(["pack", "sign", str(p)]) == 0
    out = capsys.readouterr().out
    assert f"{p}.sig" in out and "sha256" in out, out
    sig = json.loads(Path(f"{p}.sig").read_text())
    assert sig["v"] == 1 and sig["algo"] == "sha256"
    assert sig["rules"] == 2 and len(sig["digest"]) == 64

    assert main(["pack", "verify", str(p)]) == 0
    assert f"verified {p}: 2 rules" in capsys.readouterr().out

    # canonical: re-serializing in another key order still verifies
    p.write_text(json.dumps({"hate": "no hate", "spam": "no spam"}))
    assert main(["pack", "verify", str(p)]) == 0
    capsys.readouterr()

    # no manifest: E_PACK_SIG, the fix suggested, exit 4 (file class)
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps({"spam": "no spam"}))
    assert main(["pack", "verify", str(bare)]) == 4
    err = capsys.readouterr().err
    assert "E_PACK_SIG" in err and "pack sign" in err, err
    # corrupt manifest: same code, same class
    Path(f"{p}.sig").write_text("{broken")
    assert main(["pack", "verify", str(p)]) == 4
    assert "E_PACK_SIG" in capsys.readouterr().err
    # sign keeps the hardened read, and both verbs need a file
    assert main(["pack", "sign", str(tmp_path / "nope.json")]) == 4
    assert "no pack file" in capsys.readouterr().err
    assert main(["pack", "sign"]) == 4
    assert "sign needs a file" in capsys.readouterr().err
    assert main(["pack", "verify"]) == 4
    assert "verify needs a file" in capsys.readouterr().err


def test_check_file_batch_scoring_jsonl(tmp_path, monkeypatch, capsys):  # T874
    """check --file scores one message per line as JSONL: each object
    carries its 1-based input line number and the CLI's own reason, blank
    lines are skipped, the batch exits with the worst action — and
    MESSAGE/--file is an XOR while neither alone is a usage error."""
    import gatekeeper

    class LineStub:
        def predict(self, state, questions):
            choice = "no-cheat" if "aimbot" in state["message"] else "ok"
            conf = 0.95
            return {"answers": {
                "rule": {"choice": choice, "confidence": conf,
                         "probabilities": {choice: conf}},
                "harm": {"score": "safe"}, "hype": {"score": "chill"},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    monkeypatch.setattr(gatekeeper, "_router", LineStub())
    f = tmp_path / "batch.txt"
    f.write_text("good game\n\naimbot for sale\nanother clean line\n")

    assert main(["check", "--file", str(f), "--preset", "gaming"]) == 2, \
        "the batch exits with its worst action"
    rows = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert len(rows) == 3, "the blank line is not a message"
    assert [r["line"] for r in rows] == [1, 3, 4], "1-based input mapping"
    assert rows[0]["action"] == "allow" and rows[2]["action"] == "allow"
    assert rows[1]["action"] in ("delete", "flag"), rows[1]
    assert all(r["reason"] for r in rows), "the CLI reason rides every row"

    # a clean batch is exit 0 like a single allow
    clean = tmp_path / "clean.txt"
    clean.write_text("good game\n")
    assert main(["check", "--file", str(clean), "--preset", "gaming"]) == 0

    # MESSAGE and --file are mutually exclusive; neither alone is usage
    assert main(["check", "hi", "--file", str(clean)]) == 4
    assert "exactly one" in capsys.readouterr().err
    assert main(["check"]) == 4
    assert "needs MESSAGE or --file" in capsys.readouterr().err
    # a missing file keeps the file-class exit and names it
    assert main(["check", "--file", str(tmp_path / "nope.txt")]) == 4
    assert "no message file" in capsys.readouterr().err
