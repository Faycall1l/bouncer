"""P35 tests (T651-T670): fine-tune plumbing. Weightless — the GPU run is manual;
these tests review the scripts statically and exercise everything runnable."""
import re


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
