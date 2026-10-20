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


def test_completion_generated_from_parser(capsys):  # T875
    """completion bash|zsh is built from build_parser() itself: every
    subcommand lands in the script (new commands complete without touching
    the generator), options come from each subparser's own actions, and the
    emitted scripts parse under bash -n / zsh -n."""
    import argparse
    import shutil
    import subprocess

    from gatekeeper.cli import build_parser

    p = build_parser()
    subs = next(a for a in p._actions
                if isinstance(a, argparse._SubParsersAction)).choices

    assert main(["completion", "bash"]) == 0
    bash = capsys.readouterr().out
    assert "complete -F _bouncer_complete bouncer" in bash
    assert "compgen -W" in bash
    for name in subs:  # the whole parser surface, generated
        assert f"        {name})" in bash, name
    assert '"--preset' in bash or ' --preset ' in bash, "options per parser"
    assert "--file" in bash, "check's new flag completes too"
    if shutil.which("bash"):  # the script must actually parse
        r = subprocess.run(["bash", "-n"], check=False, input=bash, text=True,
                           capture_output=True)
        assert r.returncode == 0, r.stderr

    assert main(["completion", "zsh"]) == 0
    zsh = capsys.readouterr().out
    assert zsh.startswith("#compdef bouncer")
    assert "compdef _bouncer bouncer" in zsh
    assert "_describe 'command' cmds" in zsh
    for name in subs:
        assert f"{name}) compadd" in zsh, name
    if shutil.which("zsh"):
        r = subprocess.run(["zsh", "-n"], check=False, input=zsh, text=True,
                           capture_output=True)
        assert r.returncode == 0, r.stderr

    # an unknown shell is argparse's refusal, not ours
    try:
        main(["completion", "fish"])
        raise AssertionError("choices must refuse fish")
    except SystemExit as e:
        assert e.code == 2


def test_snapshot_v2_migrates_v1_and_rejects_unknown(tmp_path, capsys):  # T876
    """The snapshot schema is v2 at both levels (doc + stats): save writes
    it, load takes v2 natively and v1 through an in-memory migration noted
    on stdout (stats without adapters ride it, raw user keys are preserved
    and the table then gains namespaced strikes alongside), while
    non-object strikes and unknown versions refuse E_SNAPSHOT before
    anything is applied."""
    from gatekeeper import strikes as _st
    from gatekeeper.stats import get_stats, record, reset_stats

    reset_stats()
    _st.reset()
    record("flag", "r", 1.0)
    _st.add_strike("telegram:77", 2)
    f = tmp_path / "v2.json"
    assert main(["snapshot", "save", str(f)]) == 0
    doc = json.loads(f.read_text())
    assert doc["v"] == 2 and doc["stats"]["v"] == 2, "current schema, both levels"
    assert "adapters" in doc["stats"], "v2 declares the T867 section"

    # export --stats stamps the same schema — a loadable snapshot doc
    ex = tmp_path / "ex.json"
    assert main(["export", "--stats", str(ex)]) == 0
    exdoc = json.loads(ex.read_text())
    assert exdoc["v"] == 2 and exdoc.get("bouncer"), "export is a real doc"

    # a v1 doc from an older bouncer: stats without adapters, raw keys
    reset_stats()
    _st.reset()
    old = tmp_path / "v1.json"
    old.write_text(json.dumps({
        "v": 1, "t": 1700000000, "bouncer": "0.4.0",
        "stats": {"v": 1, "t": 1700000000,
                  "counts": {"allow": 3, "flag": 0, "delete": 0, "escalate": 0},
                  "by_rule": {"ok": 3}, "joint": [["allow", "ok", 3]],
                  "causes": {}, "cheap": 3},
        "strikes": {"legacyuser": 1}}))
    assert main(["snapshot", "load", str(old)]) == 0
    out = capsys.readouterr().out
    assert "migrated v1 -> v2" in out, out
    assert get_stats()["actions"]["allow"] == 3, "v1 counters restored"
    assert _st.standing("legacyuser")["strikes"] == 1, "raw keys preserved"
    # ...and the restored table gains namespaced strikes alongside (T858)
    _st.add_strike("telegram:77", 1)
    assert _st.standing("telegram:77")["strikes"] == 1
    assert _st.standing("legacyuser")["strikes"] == 1, "both live together"

    # v2 loads natively — no migration note, max-wins merge keeps 2
    reset_stats()
    assert main(["snapshot", "load", str(f)]) == 0
    assert "migrated" not in capsys.readouterr().out
    assert _st.standing("telegram:77")["strikes"] == 2

    # unknown version: coded refusal, nothing applied
    (tmp_path / "v3.json").write_text(
        json.dumps({"v": 3, "stats": {}, "strikes": {}}))
    assert main(["snapshot", "load", str(tmp_path / "v3.json")]) == 4
    err = capsys.readouterr().err
    assert "E_SNAPSHOT" in err and "version 3" in err, err
    # non-object strikes: refused before the merge (v2 contract)
    (tmp_path / "bad.json").write_text(
        json.dumps({"v": 2, "stats": {"v": 2}, "strikes": [1, 2]}))
    assert main(["snapshot", "load", str(tmp_path / "bad.json")]) == 4
    assert "strikes table must be an object" in capsys.readouterr().err
    assert _st.standing("legacyuser")["strikes"] == 1, "nothing half-applied"
    _st.reset()
    reset_stats()


def test_snapshot_carries_the_decision_cache(tmp_path, capsys):  # T877
    """snapshot save/load carries the decision cache: live entries ride in
    the doc and are counted on both lines, restore merges them back and
    prunes expired ones, a section-less (v1) snapshot restores none and
    says nothing, and a malformed section refuses before anything applies."""
    import time

    from gatekeeper.cache import CACHE
    from gatekeeper.stats import get_stats, record, reset_stats

    reset_stats()
    CACHE.clear()
    key = CACHE.key("warm message", {"r": "t"}, 0.85, 0.9)
    CACHE.set(key, {"action": "allow", "rule": "ok"})

    f = tmp_path / "c.json"
    assert main(["snapshot", "save", str(f)]) == 0
    doc = json.loads(f.read_text())
    assert "cache" in doc and doc["cache"]["v"] == 1, "v1-shaped section"
    assert key in doc["cache"]["entries"], "the live entry rides along"
    assert "cache=1" in capsys.readouterr().out, "counted on the save line"

    # round-trip: empty cache in, the entry back
    CACHE.clear()
    assert main(["snapshot", "load", str(f)]) == 0
    out = capsys.readouterr().out
    assert "cache=1" in out, out
    hit = CACHE.get(key)
    assert hit is not None and hit["action"] == "allow", "merged back"

    # expired entries are pruned at restore, never resurrected
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps(dict(
        doc, cache={"v": 1, "entries":
                    {"stale": [time.time() - 5, {"action": "allow"}]}})))
    CACHE.clear()
    assert main(["snapshot", "load", str(stale)]) == 0
    assert "cache=0" in capsys.readouterr().out

    # a pre-T877 v1 doc has no section: migration note, no cache note
    bare = {k: doc[k] for k in ("v", "t", "bouncer", "stats", "strikes")}
    bare["v"] = 1
    bpath = tmp_path / "bare.json"
    bpath.write_text(json.dumps(bare))
    CACHE.clear()
    assert main(["snapshot", "load", str(bpath)]) == 0
    out = capsys.readouterr().out
    assert "migrated v1 -> v2" in out and "cache=" not in out, out
    assert CACHE.get(key) is None, "no section, no entries"

    # malformed sections refuse before anything applies
    reset_stats()
    record("allow", "ok", 1.0)
    p1 = tmp_path / "badsec.json"
    p1.write_text(json.dumps(dict(doc, cache={"v": 1, "entries": "nope"})))
    assert main(["snapshot", "load", str(p1)]) == 4
    assert "bad cache snapshot" in capsys.readouterr().err
    assert get_stats()["actions"]["allow"] == 1, "nothing half-applied"
    p2 = tmp_path / "badentry.json"
    p2.write_text(json.dumps(dict(
        doc, cache={"v": 1, "entries": {"k": 5}})))
    assert main(["snapshot", "load", str(p2)]) == 4
    assert "bad cache entry" in capsys.readouterr().err
    assert get_stats()["actions"]["allow"] == 1, "still nothing applied"
    reset_stats()
    CACHE.clear()


def test_pack_init_writes_typed_metadata(tmp_path, monkeypatch, capsys):  # T878
    """pack init writes a typed pack — meta (schema version, bouncer,
    created, preset, lang, count) over the rules section — and every
    reader (lint, check --rules, diff, sign) unwraps it, while a bare
    {id: text} pack from before T878 keeps working everywhere."""
    import gatekeeper

    class PackStub:
        def predict(self, state, questions):
            return {"answers": {
                "rule": {"choice": "ok", "confidence": 0.95,
                         "probabilities": {"ok": 0.95}},
                "harm": {"score": "safe"}, "hype": {"score": "chill"},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    monkeypatch.setattr(gatekeeper, "_router", PackStub())
    f = tmp_path / "typed.json"
    assert main(["pack", "init", str(f), "--preset", "study"]) == 0
    doc = json.loads(f.read_text())
    meta = doc["meta"]
    assert meta["v"] == 1 and meta["preset"] == "study", "typed, not bare"
    assert meta["lang"] == "en" and meta["rules"] == len(doc["rules"])
    assert isinstance(meta["created"], int) and meta["bouncer"], "provenance"
    capsys.readouterr()

    # lint + check unwrap the typed pack
    assert main(["pack", "lint", "--rules", str(f)]) == 0
    assert main(["check", "good game", "--rules", str(f)]) == 0
    capsys.readouterr()

    # a bare {id: text} pack (pre-T878) still works everywhere
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(doc["rules"]))
    assert main(["pack", "lint", "--rules", str(bare)]) == 0
    assert main(["check", "good game", "--rules", str(bare)]) == 0
    capsys.readouterr()

    # diff sees through the wrapping: same rules = identical
    assert main(["pack", "diff", str(f), str(bare)]) == 0
    assert "identical" in capsys.readouterr().out

    # sign/verify digest the rules section, wrapping aside
    assert main(["pack", "sign", str(f)]) == 0
    assert main(["pack", "verify", str(f)]) == 0
    assert "verified" in capsys.readouterr().out


def test_pack_lint_catches_duplicate_ids_and_invisible_text(tmp_path, capsys):  # T879
    """Two rules with the same id are a parse-time problem, not a lint one:
    the JSON scanner silently keeps the last duplicate, so _read_pack
    rejects the pack outright, naming the id (exit 4). Text made only of
    zero-width/control characters slips past strip() but renders as nothing,
    so validate_rule_text rejects it as invisible-only — while a good pack
    still lints clean."""
    dup = tmp_path / "dup.json"
    dup.write_text('{"spam": "no spam", "hate": "no hate", "spam": "other"}')
    assert main(["pack", "lint", "--rules", str(dup)]) == 4
    err = capsys.readouterr().err
    assert "duplicate key 'spam'" in err, err

    zwsp = tmp_path / "zwsp.json"
    zwsp.write_text(json.dumps({"ghost": "\u200b"}))
    assert main(["pack", "lint", "--rules", str(zwsp)]) == 4
    err = capsys.readouterr().err
    assert "E_RULES_TEXT" in err and "invisible-only" in err, err

    # NBSP-only is whitespace-only: caught by the T113 empty check still
    nbsp = tmp_path / "nbsp.json"
    nbsp.write_text(json.dumps({"ghost": "\u00a0"}))
    assert main(["pack", "lint", "--rules", str(nbsp)]) == 4
    assert "has empty text" in capsys.readouterr().err

    # positive control: a pack of plain printable text lints clean
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"spam": "no spam here",
                                "hate": "no hate here"}))
    assert main(["pack", "lint", "--rules", str(good)]) == 0
    assert "pack ok: 2 rules" in capsys.readouterr().out


def test_pack_lint_warns_on_verbatim_preset_text(tmp_path, capsys):  # T880
    """Rule text copied word-for-word out of a built-in preset is a template
    someone forgot to tune: pack lint warns, naming the preset and rule it
    came from. Linting a preset by name never warns about its own rules;
    warnings alone don't change the exit code."""
    # a pack whose rule is gaming's no-spam text verbatim (new id)
    copy = tmp_path / "copy.json"
    copy.write_text(json.dumps({
        "my-spam": "no ads, links, self-promo, or crypto giveaways",
        "custom": "stick to raid planning and logistics"}))
    assert main(["pack", "lint", "--rules", str(copy)]) == 0
    out = capsys.readouterr().out
    assert "warn:" in out and "verbatim preset gaming rule no-spam" in out, out
    assert "custom" not in out, "unrelated rules stay quiet"
    assert "pack ok: 2 rules" in out

    # linting gaming by name excludes gaming: no self-warnings, exit 0
    assert main(["pack", "lint", "--preset", "gaming"]) == 0
    assert "verbatim" not in capsys.readouterr().out

    # a fully custom pack stays silent
    solo = tmp_path / "solo.json"
    solo.write_text(json.dumps({"one": "stick to raid planning and logistics"}))
    assert main(["pack", "lint", "--rules", str(solo)]) == 0
    assert "verbatim" not in capsys.readouterr().out
