"""P35 tests (T651-T670): fine-tune plumbing. Weightless — the GPU run is manual;
these tests review the scripts statically and exercise everything runnable."""
import json
import os
import re
import subprocess
import sys


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
    for m in re.finditer(r"^assert ", src, re.MULTILINE):
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


def test_smoke_run_path_documented():  # T659: 50 rows, 1 epoch, documented shape
    src = _src("kaggle/train/train.py")
    assert 'EPOCHS = 1 if MAX_SAMPLES else 3' in src
    assert "--max-samples 50" in src  # train.py docstring documents the path
    readme = _src("notebooks/README.md")
    assert "--max-samples 50" in readme and "TRAIN_OK" in readme


def test_eval_after_train_cell():  # T660: CI metrics on the held-out split
    src = _src("kaggle/train/train.py")
    assert "test_split.jsonl" in src  # split always written OUT
    assert "eval_gatekeeper.py" in src and '"--model", OUT' in src
    cell = src.index("(T660): CI's own metrics")
    push = src.index("token and best_dev >= DEV_FLOOR")
    assert cell < push  # eval cell runs before the push gate (T661 hooks here)
    assert "not reachable — run locally" in src  # honest fallback command
