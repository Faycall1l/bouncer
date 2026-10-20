"""P35 tests (T651-T670): fine-tune plumbing. Weightless — the GPU run is manual;
these tests review the scripts statically and exercise everything runnable."""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, "src")


def _run_py(*args):
    env = {**os.environ, "PATH": "/usr/bin:/bin"}  # strip kaggle CLI for determinism
    return subprocess.run([sys.executable, *args], check=False, capture_output=True,
                          text=True, env=env, timeout=30)


def _src(path):
    with open(path) as f:
        return f.read()


def test_train_script_asserts_before_training():  # T651: every stage gated
    src = _src("kaggle/train/train.py")
    assert src.count("assert ") >= 8  # one assert per stage boundary
    loop = src.index("for epoch in range(EPOCHS)")
    # indented since T911's main() wrap — the guarantee is positional, not column-0
    for m in re.finditer(r"^\s*assert ", src, re.MULTILINE):
        assert m.start() < loop, "an assert sits after training started"
    for kw in ("no /kaggle/input", "row schema", "zero items",
               "empty train or calibration split", "micro-batch", "no encoder params"):
        assert kw in src


def test_finetune_pastein_asserts():  # T651: converter refuses bad rows
    src = _src("notebooks/finetune_kaggle.py")
    assert src.count("assert ") >= 3
    for kw in ("wrong file", "label out of range", "no records built"):
        assert kw in src


def test_laya_records_shape():  # T651: converter output matches engine schema
    import sys

    sys.path.insert(0, "notebooks")
    import finetune_kaggle
    recs = finetune_kaggle.to_laya_records("data/examples.jsonl")
    assert recs, "converter returned nothing"
    r = recs[0]
    assert set(r) == {"state", "questions", "expected"}
    assert set(r["questions"]) == {"rule", "harm", "hype", "jailbreak", "escalate"}
    assert r["questions"]["rule"]["type"] == "choice"
    assert r["questions"]["harm"]["type"] == "score"
    assert r["questions"]["jailbreak"]["type"] == "noul"
    # score heads are int indices, choice is the label string (T387 contract)
    for rec in recs:
        assert isinstance(rec["expected"]["harm"], int)
        assert isinstance(rec["expected"]["hype"], int)
        assert isinstance(rec["expected"]["rule"], str)
        assert isinstance(rec["expected"]["jailbreak"], bool)


def test_class_weights_hint_reaches_notebook_docs():  # T648/T651: pointers stay
    src = _src("notebooks/finetune_kaggle.py")
    assert "class_weights" in src and "build_dataset" in src


def test_lora_single_block_at_top():  # T652: knobs live in one editable block
    src = _src("kaggle/train/train.py")
    block = src.index("LORA = {")
    build = src.index("build_model(")
    assert block < build < src.index("for epoch in range(EPOCHS)")
    for key in ('"enabled": False', '"r":', '"alpha":', '"dropout":', '"target_modules":'):
        assert key in src
    # optimizer only touches trainable params (full FT no-op, LoRA-correct)
    assert src.count("p.requires_grad") == 2


def test_early_stopping_wiring():  # T653: dev carve + patience + best restore
    src = _src("kaggle/train/train.py")
    assert "PATIENCE = 1" in src
    assert "train_rows[:-200], train_rows[-200:]" in src  # dev carved, test held out
    assert "dev_rule_acc(" in src and "EARLY_STOP" in src
    loop, calib = src.index("for epoch in range(EPOCHS)"), src.index("model.eval()")
    dev_call = src.index("dev_rule_acc(os.path.join")
    assert loop < dev_call < calib  # dev eval inside the loop
    restore = src.index("ship the best epoch")
    assert restore < calib  # best weights restored before calibration/save


def test_loss_jsonl_logging():  # T654: JSONL trail independent of wandb
    src = _src("kaggle/train/train.py")
    assert 'kind="step"' in src and 'kind="epoch"' in src
    assert 'kind="early_stop"' in src and 'kind="test"' in src
    assert 'json.dumps(kw)' in src and "train_log.jsonl" in src


def test_push_gated_on_dev_floor():  # T655: no shipping sub-floor checkpoints
    src = _src("kaggle/train/train.py")
    assert "DEV_FLOOR = 0.35" in src
    gate = src.index("best_dev >= DEV_FLOOR and test_acc >= REGEX_FLOOR")
    push = src.index("upload_folder")
    assert gate < push  # the gate sits before the upload
    assert "gate failed:" in src  # refusal is loud, both metrics printed


def test_regression_gate_beats_regex():  # T661: new model must beat the regex bar
    src = _src("kaggle/train/train.py")
    assert "REGEX_FLOOR = 0.403" in src  # the real post-T637 number, not the stale 0.480
    assert '"--model", OUT' in src  # gate consumes eval_gatekeeper's own numbers
    assert 'kind="no_push"' in src and "regex_floor=REGEX_FLOOR" in src  # refusals logged


def test_calibration_writes_temp_json():  # T662: temperature artifact lands in OUT
    src = _src("kaggle/train/train.py")
    assert '"temp.json"' in src
    assert '"temperature": cfg.get("temperature"' in src
    assert 'kind="calibration"' in src
    save = src.index("save_checkpoint(model, tok, cfg, OUT)")
    temp = src.index('"temp.json"')
    assert save < temp  # temp.json reflects the checkpoint that was actually saved


def test_bouncer_model_dir_overrides_lang(monkeypatch):  # T663: finetuned dir wins
    import gatekeeper
    seen = {}

    class R:
        def predict(self, state, questions, model=None):
            seen["model"] = model
            return {"answers": {
                "rule": {"choice": "ok"},
                "harm": {"score": "safe", "probabilities": []},
                "hype": {"score": "chill", "probabilities": []},
                "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}

    monkeypatch.setenv("BOUNCER_MODEL_DIR", "/models/bouncer-421m")
    gatekeeper.moderate("hello one", {"r": "t"}, router=R())
    assert seen["model"] == "/models/bouncer-421m"  # env dir beats lang routing
    gatekeeper.moderate("hello two", {"r": "t"}, router=R(), model="english")
    assert seen["model"] == "english"  # explicit pin still beats the env dir
    monkeypatch.delenv("BOUNCER_MODEL_DIR")
    gatekeeper.moderate("hello three", {"r": "t"}, router=R())
    assert seen["model"] is None  # no dir, en default -> plain base router


def test_pool_builds_from_model_dir(monkeypatch):  # T664: pool honors the dir
    from gatekeeper import pool as P
    built = []

    def factory(**kw):
        built.append(kw)
        return "router"

    monkeypatch.setattr(P, "POOL", P.RouterPool(max_n=2, factory=factory))
    monkeypatch.setenv("BOUNCER_MODEL_DIR", "/models/bouncer-421m")
    assert P.get_pooled_router() == "router"
    assert built[-1]["model"] == "/models/bouncer-421m"
    P.get_pooled_router()  # same effective kwargs -> pooled hit, no rebuild
    assert len(built) == 1
    P.get_pooled_router(model="english")  # explicit pin bypasses the dir
    assert built[-1]["model"] == "english"
    monkeypatch.delenv("BOUNCER_MODEL_DIR")
    P.get_pooled_router()  # dir gone -> plain build, a distinct pool slot
    assert built[-1] == {}


def test_check_kaggle_env_preflight():  # T656: pre-flight plan is honest JSON
    r = _run_py("scripts/check_kaggle_env.py", "--json")
    rep = json.loads(r.stdout)
    names = {c["name"] for c in rep["checks"]}
    assert names == {"kaggle_cli", "kaggle_credentials", "dataset_artifact", "hf_token"}
    assert r.returncode == (0 if rep["ok"] else 1)  # exit code matches the plan
    for c in rep["checks"]:
        assert set(c) == {"name", "ok", "required", "detail"}
    # an unbuilt dataset fails loud, a shipped artifact passes
    r = _run_py("scripts/check_kaggle_env.py", "--dataset", "/nonexistent/x.jsonl", "--json")
    assert r.returncode == 1
    assert "dataset_artifact" in json.loads(r.stdout)["failed_required"]
    r = _run_py("scripts/check_kaggle_env.py", "--dataset", "data/examples.jsonl", "--json")
    assert "dataset_artifact" not in json.loads(r.stdout)["failed_required"]


def test_upload_dataset_kaggle_dry_run():  # T657: publish plan, dry-run default
    r = _run_py("scripts/upload_dataset_kaggle.py")
    rep = json.loads(r.stdout)
    assert rep["slug"] == "gatekeeper-chatmix-12k"
    assert set(rep) == {"slug", "files", "missing", "total_rows", "kaggle_cli", "credentials"}
    assert r.returncode == 1  # unbuilt 12k dataset fails loud
    assert "data/gatekeeper-12k.jsonl" in rep["missing"]
    # shipped artifact dry-runs clean (exit 0, no kaggle call without --yes)
    r = _run_py("scripts/upload_dataset_kaggle.py", "--dataset", "data/examples.jsonl")
    rep = json.loads(r.stdout)
    assert r.returncode == 0 and rep["missing"] == [] and rep["total_rows"] == 300
    # --yes without the CLI on PATH fails loud before staging anything
    r = _run_py("scripts/upload_dataset_kaggle.py", "--dataset", "data/examples.jsonl", "--yes")
    assert r.returncode == 1 and "kaggle CLI" in r.stderr


def test_max_samples_smoke_flag():  # T658: smoke truncation without breaking splits
    src = _src("kaggle/train/train.py")
    assert '"--max-samples"' in src and "parse_known_args" in src
    assert "T658: smoke path" in src  # truncation happens AFTER completeness asserts
    assert "T658: smoke split" in src and "split left an empty part" in src
    flag = src.index('"--max-samples"')
    assert flag < src.index("rows_raw = rows_raw[:MAX_SAMPLES]") < src.index("train_items, calib_items")


def test_smoke_run_path_documented():  # T659+T913: 50 rows, 1 epoch default
    src = _src("kaggle/train/train.py")
    # T913: --epochs can override, but the smoke default stays 1 epoch
    assert "EPOCHS = EPOCHS_FLAG or (1 if MAX_SAMPLES else 3)" in src
    assert "--max-samples 50" in src  # train.py docstring documents the path
    readme = _src("notebooks/README.md")
    assert "--max-samples 50" in readme and "TRAIN_OK" in readme


def test_failure_modes_documented():  # T667: OOM, token cap, label noise, refusals
    readme = _src("notebooks/README.md")
    for kw in ("## Failure modes", "CUDA OOM", "head_max_len=256",
               "quarantine", "no_push", "temp.json"):
        assert kw in readme


def test_compare_models_deltas(tmp_path):  # T668: weightless base-vs-ft diff
    base = {"model": "base-router", "n": 500, "rule_acc": 0.305, "ece": 0.21,
            "brier": 0.18, "p50_ms": 1004.0, "abstention_rate": 0.0,
            "overconfident_errors": 0, "gate": {"prec": 0.0, "n": 0}}
    ft = {"model": "bouncer-421m", "n": 500, "rule_acc": 0.512, "ece": 0.12,
          "brier": 0.11, "p50_ms": 40.0, "abstention_rate": 0.05,
          "overconfident_errors": 2, "gate": {"prec": 0.81, "n": 42}}
    b, f_ = tmp_path / "base.json", tmp_path / "ft.json"
    b.write_text(json.dumps(base))
    f_.write_text(json.dumps(ft))
    r = _run_py("eval/compare_models.py", str(b), str(f_), "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["ft_wins"] == 7 and rep["base_wins"] == 1  # overconf is the loss
    assert rep["ft_better"] is True
    assert rep["metrics"]["rule_acc"]["delta"] == 0.207
    assert rep["metrics"]["rule_acc"]["verdict"] == "ft"
    assert rep["metrics"]["ece"]["delta"] == -0.09  # lower is better
    assert rep["metrics"]["overconfident_errors"]["verdict"] == "base"
    # unreadable report -> exit 2, loud
    r = _run_py("eval/compare_models.py", str(tmp_path / "nope.json"), str(f_))
    assert r.returncode == 2 and "cannot read" in r.stderr


def test_release_checklist_accuracy_item():  # T669: numbers refreshed before tags
    doc = _src("docs/RELEASE-CHECKLIST.md")
    assert "accuracy numbers refreshed" in doc
    assert "eval_gatekeeper.py" in doc and "never vibes" in doc
    assert "docs/RELEASE-CHECKLIST.md" in _src("CONTRIBUTING.md")


def test_p35_numbers_consistent_everywhere():  # T670 sweep: one set of numbers
    bench = _src("BENCHMARKS.md")
    assert "0.403" in bench and "2×T4" in bench  # T666 costs block present
    assert "finetune-run-impact.md" in bench  # T665 draft is linked
    impact = _src("docs/drafts/finetune-run-impact.md")
    assert "0.305" in impact and "0.403" in impact  # before-column is measured
    assert "**Status: draft.**" in impact  # nothing in it pretends to be measured
    train = _src("kaggle/train/train.py")
    assert "REGEX_FLOOR = 0.403" in train and "DEV_FLOOR = 0.35" in train


def test_compare_models_render_table(tmp_path):  # T670 sweep: human output path
    b, f_ = tmp_path / "base.json", tmp_path / "ft.json"
    b.write_text(json.dumps({"model": "base-router", "n": 10, "rule_acc": 0.3}))
    f_.write_text(json.dumps({"model": "bouncer-421m", "n": 10, "rule_acc": 0.5}))
    r = _run_py("eval/compare_models.py", str(b), str(f_))
    assert r.returncode == 0, r.stderr
    assert "rule_acc" in r.stdout and "better" in r.stdout
    assert "ft wins 1 / base wins 0" in r.stdout  # table + verdict line render


def test_eval_after_train_cell():  # T660: CI metrics on the held-out split
    src = _src("kaggle/train/train.py")
    assert "test_split.jsonl" in src  # split always written OUT
    assert "eval_gatekeeper.py" in src and '"--model", OUT' in src
    cell = src.index("(T660): CI's own metrics")
    push = src.index("token and best_dev >= DEV_FLOOR")
    assert cell < push  # eval cell runs before the push gate (T661 hooks here)
    assert "not reachable — run locally" in src  # honest fallback command
