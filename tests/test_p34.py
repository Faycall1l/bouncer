"""P34 tests (T631-T650): dataset build pipeline. No weights, no network."""
import json
import os
import subprocess
import sys
import types

sys.path.insert(0, "src")

ENV = {**os.environ, "PATH": "/usr/bin:/bin", "PYTHONPATH": "src"}


def _run(*args, env=None):
    return subprocess.run([sys.executable, *args], check=False, capture_output=True,
                          text=True, env=env or ENV, timeout=60)


def _server(row):
    return tuple(sorted(row["state"]["rules"]))


def test_split_is_server_disjoint(tmp_path):  # T632: no rule-set leaks between splits
    out = str(tmp_path / "ds.jsonl")
    r = _run("data/build_dataset.py", "--n", "150", "--template-only",
             "--seed", "11", "--out", out)
    assert r.returncode == 0, r.stderr
    parts = {}
    for name in ("train", "dev", "test"):
        with open(f"{out[:-6]}.{name}.jsonl") as f:
            parts[name] = [json.loads(l) for l in f]
    keys = {n: {_server(x) for x in rows} for n, rows in parts.items()}
    assert not keys["train"] & keys["dev"]
    assert not keys["train"] & keys["test"]
    assert not keys["dev"] & keys["test"]
    # every row lands in exactly one split (no drops, no dupes)
    # 150 template rows + 15 default hard negatives (T636: hard-n = n//10)
    total = sum(len(v) for v in parts.values())
    assert total == 165
    msgs = [x["state"]["message"] for rows in parts.values() for x in rows]
    assert len(set(msgs)) >= 3  # the 3 template messages all survive the split


def test_split_ratios_converge_with_many_servers():  # T632: greedy honors targets
    sys.path.insert(0, "data")
    from build_dataset import split_rows
    rows = []
    for s in range(40):  # 40 distinct rule-sets, 25 rows each
        rules = {f"rule-{s}-a": "t", f"rule-{s}-b": "t", f"rule-{s}-c": "t"}
        rows += [{"state": {"message": f"m{s}.{i}", "history": [], "rules": rules},
                  "labels": {"rule": "ok"}} for i in range(25)]
    splits = split_rows(rows, ratios=(0.8, 0.1, 0.1), seed=0)
    n = len(rows)
    assert sum(len(v) for v in splits.values()) == n
    frac = {k: len(v) / n for k, v in splits.items()}
    assert 0.6 <= frac["train"] <= 0.9  # near target despite whole-server granularity
    assert frac["dev"] > 0 and frac["test"] > 0
    k = {name: {_server(x) for x in part} for name, part in splits.items()}
    assert not k["train"] & k["dev"] and not k["train"] & k["test"]
    assert not k["dev"] & k["test"]
    assert len(k["train"] | k["dev"] | k["test"]) == 40  # all servers placed


def test_split_three_servers_one_each():  # T632: tiny sets still yield dev+test
    sys.path.insert(0, "data")
    from build_dataset import split_rows
    rows = []
    for s in range(3):
        rules = {f"srv{s}-x": "t", f"srv{s}-y": "t"}
        rows += [{"state": {"message": f"m{s}.{i}", "history": [], "rules": rules},
                  "labels": {"rule": "ok"}} for i in range(10)]
    splits = split_rows(rows, ratios=(0.8, 0.1, 0.1), seed=0)
    assert all(len(v) == 10 for v in splits.values())  # 1 server per split


def test_bad_ratios_rejected():  # T632: garbage config fails loud
    sys.path.insert(0, "data")
    from build_dataset import split_rows
    rows = [{"state": {"message": "m", "history": [], "rules": {"r": "t"}},
             "labels": {"rule": "ok"}}]
    for bad in ((1.0, 0.0), (-0.1, 0.6, 0.5), (0.0, 0.0, 0.0)):
        try:
            split_rows(rows, ratios=bad)
        except ValueError:
            continue
        raise AssertionError(f"ratios {bad} accepted")
    # weights need not sum to 1: 2:1:0 = two parts train, one test, no dev
    splits = split_rows([  # two servers, 30 rows each
        {"state": {"message": f"m{s}.{i}", "history": [], "rules": {f"s{s}": "t"}},
         "labels": {"rule": "ok"}} for s in range(2) for i in range(30)
    ], ratios=(2.0, 0.0, 1.0), seed=0)
    assert len(splits["train"]) == 30 and len(splits["test"]) == 30
    assert splits["dev"] == []


def test_dedupe_normalized_hash():  # T634: case/punct/whitespace collapse
    sys.path.insert(0, "data")
    from build_dataset import dedupe_rows, normalized_hash
    assert normalized_hash("GG all!!") == normalized_hash("gg  all")
    assert normalized_hash("GG all") != normalized_hash("GG all tomorrow")
    rows = [{"state": {"message": m, "history": [], "rules": {"r": "t"}},
             "labels": {"rule": "ok"}}
            for m in ("GG all", "gg  ALL!", "gg all.", "different text")]
    kept, dropped = dedupe_rows(rows)
    assert dropped == 2 and len(kept) == 2
    assert kept[0]["state"]["message"] == "GG all"  # first wins


def test_report_balance_thresholds(tmp_path):  # T633: --report flags thin labels
    # an unreachable threshold flags every label -> balanced False
    r = _run("data/build_dataset.py", "--n", "120", "--template-only",
             "--seed", "11", "--report", "--min-share", "1.1")
    assert r.returncode == 0, r.stderr  # advisory without --strict
    rep = json.loads(r.stdout)
    assert rep["n"] == 132 and rep["servers"] == 3  # 120 + 12 default hard negatives
    assert rep["seed"] == 11  # T646: seed logged for full reproducibility
    cw = rep["class_weights"]  # T648: inverse-frequency hints for the finetune
    assert set(cw) == {"rule", "harm", "jailbreak", "escalate"}
    for field in ("rule", "harm"):
        ws = list(cw[field].values())
        assert all(w > 0 for w in ws)
        assert ws == sorted(ws)  # most_common order == ascending weights
    assert set(cw["jailbreak"]) == {"false", "true"}
    for name in ("train", "dev", "test"):
        s = rep["splits"][name]
        assert s["n"] > 0 and sum(s["rule"].values()) == s["n"]
    assert rep["balanced"] is False and rep["below_threshold"]
    # --strict turns the same imbalance into exit 1 (CI gate shape)
    r = _run("data/build_dataset.py", "--n", "120", "--template-only",
             "--seed", "11", "--report", "--min-share", "1.1", "--strict")
    assert r.returncode == 1
    # a zero threshold can never trip: single-label splits are share 1.0
    r = _run("data/build_dataset.py", "--n", "120", "--template-only",
             "--seed", "11", "--report", "--min-share", "0.0", "--strict")
    assert r.returncode == 0 and json.loads(r.stdout)["balanced"] is True


def test_examples_row_count_and_size():  # T641: shipped fixtures stay pinned
    import pathlib

    p = pathlib.Path("data/examples.jsonl")
    with open(p) as f:
        rows = [json.loads(l) for l in f]
    assert len(rows) == 300  # T637 regeneration pinned this count
    assert all(r.get("v") == 1 for r in rows)  # T640 stamps present
    assert p.stat().st_size < 1_000_000  # example file stays small
    q = pathlib.Path("data/examples_i18n.jsonl")
    with open(q) as f:
        irows = [json.loads(l) for l in f]
    assert len(irows) == 12 and all(r.get("v") == 1 for r in irows)
    assert q.stat().st_size < 50_000


def test_stratify_keeps_label_mix():  # T643: label-preserving split beats plain
    from collections import Counter

    sys.path.insert(0, "data")
    from build_dataset import split_rows
    rows = []
    for s in range(30):  # 30 servers: all-ok / all-be-kind / all-no-spam thirds
        lab = ("ok", "be-kind", "no-spam")[s // 10]
        rules = {f"srv{s}-a": "t", f"srv{s}-b": "t"}
        rows += [{"state": {"message": f"m{s}.{i}", "history": [], "rules": dict(rules)},
                  "labels": {"rule": lab}} for i in range(20)]

    def dev_distance(splits):  # squared distance of dev's label mix from global
        c = Counter(r["labels"]["rule"] for r in splits["dev"])
        n = len(splits["dev"]) or 1
        return sum((c[l] / n - 1 / 3) ** 2 for l in ("ok", "be-kind", "no-spam"))

    plain = split_rows(rows, seed=0)
    strat = split_rows(rows, seed=0, stratify=True)
    assert dev_distance(strat) < dev_distance(plain)  # dev is not a single label
    # server disjointness still holds under stratification
    k = {n: {tuple(sorted(x["state"]["rules"])) for x in part}
         for n, part in strat.items()}
    assert not k["train"] & k["dev"] and not k["train"] & k["test"]
    assert sum(len(v) for v in strat.values()) == len(rows)


def test_validate_warns_on_empty_history(tmp_path):  # T644: advisory, exit 0
    # shipped examples carry history (T635) -> zero warnings
    r = _run("eval/validate_data.py", "data/examples.jsonl", "--json")
    assert r.returncode == 0
    assert json.loads(r.stdout)["warnings"] == 0
    # a pre-T635 row (history: []) warns but never fails the run
    old = tmp_path / "old.jsonl"
    old.write_text(json.dumps(
        {"state": {"message": "x", "history": [], "rules": {"r": "t"}},
         "labels": {"rule": "ok"}}) + "\n")
    r = _run("eval/validate_data.py", str(old), "--json")
    assert r.returncode == 0
    rep = json.loads(r.stdout)
    assert rep["errors"] == 0 and rep["warnings"] == 1
    assert "empty history" in r.stderr


def test_quarantine_rows_keeps_reason():  # T645: bad rows carry their errors
    sys.path.insert(0, "data")
    from build_dataset import quarantine_rows
    good_row = {"v": 1, "state": {"message": "hi", "history": [], "rules": {"r": "t"}},
                "labels": {"rule": "ok"}}
    bad_row = {"v": 1, "state": {"message": "x", "history": [], "rules": {}},
               "labels": {}}  # empty rules + missing labels.rule
    good, bad = quarantine_rows([good_row, bad_row])
    assert good == [good_row]
    assert len(bad) == 1 and bad[0]["row"] is bad_row
    assert "rules" in bad[0]["error"] and "labels.rule" in bad[0]["error"]


def test_llm_rows_quarantine_collects(monkeypatch):  # T645: no silent skip
    def create(**kw):
        msg = types.SimpleNamespace(content="{{ not json")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    fake = types.SimpleNamespace(
        OpenAI=lambda **kw: types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))))
    monkeypatch.setitem(sys.modules, "openai", fake)
    sys.path.insert(0, "data")
    import synth_rules
    q = []
    rows = synth_rules.llm_rows(3, quarantine=q)
    assert rows == []  # every teacher row was corrupt -> nothing shipped silently
    assert {e["i"] for e in q} == {0, 1, 2}
    assert all(e["raw"] == "{{ not json" and e["error"] for e in q)


def test_synth_quarantine_file_written(tmp_path):  # T645: CLI end-to-end
    (tmp_path / "openai.py").write_text(
        "from types import SimpleNamespace\n"
        "class OpenAI:\n"
        "    def __init__(self, **kw):\n"
        "        msg = SimpleNamespace(content=\"not valid json {\")\n"
        "        self.chat = SimpleNamespace(completions=SimpleNamespace(\n"
        "            create=lambda **kw: SimpleNamespace(\n"
        "                choices=[SimpleNamespace(message=msg)])))\n")
    env = {**ENV, "PYTHONPATH": f"{tmp_path}:src",
           "OPENAI_API_KEY": "x", "OPENAI_BASE_URL": "http://127.0.0.1:0"}
    out = str(tmp_path / "q.jsonl")
    r = _run("data/synth_rules.py", "--n", "3", "--out", out, env=env)
    assert r.returncode == 0, r.stderr
    assert "quarantined" in r.stderr
    with open(tmp_path / "q.quarantine.jsonl") as f:
        q = [json.loads(l) for l in f]
    assert len(q) == 2  # n=3 -> 1 template row + 2 corrupt teacher rows
    assert all("raw" in e and "error" in e for e in q)
    with open(out) as f:
        rows = [json.loads(l) for l in f]
    assert len(rows) == 1  # the valid template row still ships


def test_12k_template_build_end_to_end(tmp_path):  # T647: full-size pipeline run
    out = str(tmp_path / "gatekeeper-12k.jsonl")
    r = _run("data/build_dataset.py", "--n", "12000", "--template-only",
             "--seed", "42", "--out", out)
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["n"] == 13200  # 12000 template + 1200 default hard negatives
    assert rep["errors"] == 0 and rep["disjoint"] is True and rep["seed"] == 42
    # splits exist, reconcile with the full file, and are server-disjoint
    keys, total = {}, 0
    for name in ("train", "dev", "test"):
        with open(f"{out.removesuffix('.jsonl')}.{name}.jsonl") as f:
            part = [json.loads(l) for l in f]
        total += len(part)
        keys[name] = {tuple(sorted(x["state"]["rules"])) for x in part}
    assert total == rep["n"]
    assert not keys["train"] & keys["dev"] and not keys["train"] & keys["test"]
    assert not keys["dev"] & keys["test"]
    # every row stamped (T640) and carries history (T635)
    with open(out) as f:
        all_rows = [json.loads(l) for l in f]
    assert all(x["v"] == 1 and 2 <= len(x["state"]["history"]) <= 4 for x in all_rows)


def test_i18n_rows_flow_through_pipeline(tmp_path):  # T649: not hand-kept
    out = str(tmp_path / "i18n.jsonl")
    r = _run("data/build_dataset.py", "--i18n", "--seed", "42", "--out", out)
    assert r.returncode == 0, r.stderr
    with open(out) as f:
        gen = [json.loads(l) for l in f]
    with open("data/examples_i18n.jsonl") as f:
        shipped = [json.loads(l) for l in f]
    assert len(gen) == len(shipped) == 12

    def key(r_):
        return (r_["state"]["message"], r_["labels"]["rule"])

    assert sorted(map(key, gen)) == sorted(map(key, shipped))  # same fixtures
    assert len({tuple(sorted(x["state"]["rules"])) for x in gen}) == 3  # 3 langs
    for x in gen + shipped:  # pipeline shape everywhere: stamped + historyed
        assert x["v"] == 1 and x["state"]["history"]
