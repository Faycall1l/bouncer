"""P48: fine-tune pipeline boxes T911+.

train.py is a Kaggle script, not a library — these tests pin the parts that
must hold on ANY machine (import safety, config validation) without a GPU,
weights, or network.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

TRAIN = Path("kaggle/train/train.py")


def _import_train():
    """Import the script as a module — T911's contract: this must not pip
    install, assert CUDA, or read /kaggle/input."""
    spec = importlib.util.spec_from_file_location("bouncer_train", TRAIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_train_import_safe_on_cpu():  # T911
    """Importing train.py runs NO pip install, NO cuda assert, NO data read —
    the whole GPU pipeline hides behind main(). The proof is hostile: any
    subprocess (the pip install) during import fails the test."""
    import subprocess as sp

    real_run = sp.run

    def _boom(*a, **k):
        raise AssertionError("import must not shell out (pip install at import!)")

    sp.run = _boom
    try:
        mod = _import_train()
    finally:
        sp.run = real_run
    # the module is genuinely importable, with its config surface intact
    assert mod.LORA["enabled"] is False
    assert mod.DEV_FLOOR == 0.35 and mod.REGEX_FLOOR == 0.403
    assert callable(mod.main) and callable(mod.validate_config)


def test_train_dry_run_config_validates_on_cpu():  # T911 (+T919's surface)
    """--dry-run parses flags and config-validates WITHOUT torch, a GPU, the
    dataset, or weights: it exits 0 with DRY_RUN_OK on the shipped defaults —
    the cheapest possible pre-flight before spending quota."""
    r = subprocess.run([sys.executable, str(TRAIN), "--dry-run"],
                       check=False, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "DRY_RUN_OK" in r.stdout, r.stdout
    assert "lora_enabled=False" in r.stdout, "prints the knobs it validated"


def test_train_validate_config_rejects_bad_knobs():  # T911
    """validate_config() catches the human-editable mistakes BEFORE a GPU is
    rented: negative smoke truncation, an impossible LoRA block, floors
    outside (0, 1]. Disabled LoRA knobs are NOT validated (they're dead
    values — failing on them would be theatre)."""
    mod = _import_train()

    # shipped defaults are valid
    assert mod.validate_config() == []

    # a dry run over a broken config exits 2 and names every problem
    mod.LORA["enabled"] = True
    mod.LORA["r"] = 0
    mod.LORA["target_modules"] = []
    problems = mod.validate_config()
    assert len(problems) == 2, problems
    assert any("LORA.r" in p for p in problems), problems
    assert any("target_modules" in p for p in problems), problems

    # disabled LoRA: broken-looking knobs are dead values, not errors
    mod.LORA["enabled"] = False
    assert mod.validate_config() == []

    # floors outside the range are refused
    mod.REGEX_FLOOR = 1.5
    assert any("REGEX_FLOOR" in p for p in mod.validate_config())


def test_lora_target_modules_match_the_encoder():  # T912
    """The shipped LoRA target_modules must match the encoder that actually
    ships: laya's checkpoint is ModernBERT-large (a bert-style encoder whose
    projections are query/value). The llama-style q_proj/v_proj that shipped
    here before would match ZERO modules — peft wraps nothing and an adapter
    run trains no adapter — so the default block must carry the bert names,
    and the comment must name the encoder so the next editor can't guess."""
    mod = _import_train()
    assert mod.LORA["target_modules"] == ["query", "value"], mod.LORA
    assert "q_proj" not in mod.LORA["target_modules"], "llama names don't exist here"
    src = TRAIN.read_text()
    assert "ModernBERT" in src, "the comment names the real encoder, not a guess"
    # wrong-and-enabled must stay as loud as absent: an empty module list is
    # refused by the dry-run validator, never shipped silently
    mod.LORA["enabled"] = True
    mod.LORA["target_modules"] = []
    assert any("target_modules" in p for p in mod.validate_config())


def test_train_hyperparameter_flags():  # T913
    """--epochs/--lr/--seed are real knobs, not hardcoded constants: 0/absent
    reproduces the shipped 2xT4 recipe exactly (1/3 epochs, 2.5e-5 encoder
    with the head at 4x, shuffle seed 7), and the dry-run prints what it
    parsed so a quota spend is never a surprise."""
    mod = _import_train()
    # defaults: the recipe, unchanged
    assert mod.EPOCHS_FLAG == 0 and mod.LR_FLAG == 0.0 and mod.SEED == 7
    assert mod.validate_config() == [], "shipped knobs are valid"

    # negative values are refused by the validator, loudly
    mod.EPOCHS_FLAG, mod.LR_FLAG = -1, -0.1
    problems = mod.validate_config()
    assert any("--epochs" in p for p in problems), problems
    assert any("--lr" in p for p in problems), problems

    # the dry-run reports the parsed knobs
    r = subprocess.run(
        [sys.executable, str(TRAIN), "--dry-run", "--epochs", "2", "--lr", "3e-5",
         "--seed", "42"],
        check=False, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "epochs=2" in r.stdout and "lr=3e-05" in r.stdout and "seed=42" in r.stdout


def test_train_seed_reaches_the_shuffle_and_lr_ratio_kept():  # T913
    """The knobs must actually reach the pipeline, not just parse: --seed
    feeds the row shuffle (reproducible order), and --lr scales BOTH param
    groups keeping the head:encoder 4x ratio of the 2xT4 recipe."""
    src = TRAIN.read_text()
    assert "random.seed(SEED)" in src, "--seed reaches the row shuffle"
    assert "lr\": LR_FLAG or 2.5e-5" in src or "LR_FLAG or 2.5e-5" in src
    # head keeps the 4x ratio whatever --lr says
    assert "(LR_FLAG or 2.5e-5) * 4" in src, "head lr stays 4x the encoder"


def test_train_resume_continues_the_run():  # T914
    """A crashed run continues instead of burning quota twice: --resume loads
    checkpoint_latest's weights, restores the exact early-stopping state
    (epoch/best_dev/wait) from train_state.json, picks up optimizer momenta
    from optim.pt, and the loop starts at start_epoch. The bookkeeping is
    written AFTER the patience update so the restored wait is never stale.
    Refusing loudly when there's nothing to resume beats training from
    scratch under a flag that promised otherwise."""
    src = TRAIN.read_text()
    # the flag exists and is parsed at module level (import-safe, T911)
    mod = _import_train()
    assert hasattr(mod, "RESUME")
    # weights + state + optimizer all restored
    assert "checkpoint_latest" in src and "train_state.json" in src
    assert "optim.pt" in src, "optimizer/scheduler/scaler momenta resume too"
    assert "load_state_dict(blob" in src.replace("opt.load_state_dict", "load_state_dict(blob"), \
        "the saved optimizer blob is actually loaded"
    # the loop starts where the crash left off
    assert "for epoch in range(start_epoch, EPOCHS)" in src
    # nothing-to-resume is a loud refusal, not a silent fresh run
    assert "nothing to resume" in src
    # bookkeeping order: patience update BEFORE the state write, so a
    # resumed run's wait is the exact value the crashed run had
    patience = src.index('"epoch": epoch + 1, "best_dev": round(best_dev, 4), "wait": wait')
    assert src.index("wait += 1") < patience < src.index("if wait >= PATIENCE"), \
        "state written after the update, checked after the write"
    # the resume itself is logged — the trail shows where a run continued from
    assert 'kind="resume"' in src


def test_train_dry_run_tolerates_resume_flag():  # T914
    """--resume parses alongside --dry-run: a pre-flight on a to-be-resumed
    config doesn't need a GPU or an existing checkpoint."""
    r = subprocess.run([sys.executable, str(TRAIN), "--dry-run", "--resume"],
                       check=False, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "DRY_RUN_OK" in r.stdout


# --- T915: the ship gate IS gate.py, not a narrower copy ---------------------

_GOOD_REPORT = {  # the shape eval_gatekeeper writes for eval_test.json
    "n": 500, "rule_acc": 0.62, "model": "bouncer-421m",
    "ece": 0.07, "p50_ms": 18.0, "p95_ms": 35.0, "brier": 0.12,
    "abstention_rate": 0.11,
    "per_rule": {"ok": [200, 300], "spam": [70, 100], "caps": [45, 100]},
}


def test_ship_gate_runs_full_gate_py_thresholds():  # T915
    """The HF push now requires gate.py's FULL verdict (rule_acc floor, ECE
    ceiling, latency budget, abstention band, per-rule floor) — the old gate
    was just dev+test_acc and could ship a model CI would refuse. The train
    script invokes gate.py with NO threshold flags: gate.py's defaults are the
    single source, so a threshold change in CI moves the ship gate with it.
    And gate_pass=None (not run — eval failed, gate.py unreachable) refuses
    the push: a gate that never ran is never a green light."""
    src = TRAIN.read_text()
    # gate.py is invoked on the eval report, with no threshold overrides
    assert "gate.py" in src and "eval_test.json" in src
    gate_call = src.index('gt, os.path.join(OUT, "eval_test.json")')
    assert "--min-rule-acc" not in src and "--max-ece" not in src, \
        "thresholds stay single-sourced in gate.py — no drift copy here"
    # the push requires the full gate, and None (not run) refuses
    assert ("token and best_dev >= DEV_FLOOR and test_acc >= REGEX_FLOOR "
            "and gate_pass") in src
    assert "gate_pass = None" in src, "not-run starts as refuse, not pass"
    # receipts land in the trail either way
    assert 'kind="gate"' in src and 'full_gate=' in src
    # the refusal message tells the human which gates were involved
    assert "full_gate=" in src
    assert gate_call > 0


def test_gate_py_thresholds_fail_a_model_the_two_number_gate_would_ship():  # T915
    """Functional proof the new gate is strictly stronger: the good report
    passes gate.py (exit 0), and the SAME numbers the old gate looked at
    (dev floor, test_acc) are untouched when ECE blows the ceiling — exit 1.
    This is the exact subprocess train.py runs."""
    import json as _json
    import subprocess as sp
    import sys as _sys
    from pathlib import Path as _Path

    gate = _Path("eval/gate.py")

    def _run(report):
        p = _Path("eval/reports")  # gate needs a real file; tmp beside reports
        p.mkdir(exist_ok=True)
        out = p / "_t915_fixture.json"
        out.write_text(_json.dumps(report))
        try:
            r = sp.run([_sys.executable, str(gate), str(out)],
                       check=False, capture_output=True, text=True, timeout=60)
            return r.returncode, r.stdout + r.stderr
        finally:
            out.unlink(missing_ok=True)

    # good report: every threshold CI uses is met -> exit 0, push allowed
    code, out = _run(dict(_GOOD_REPORT))
    assert code == 0, out

    # ECE blown, rule_acc still 0.62 (well above every accuracy floor the old
    # gate checked) -> exit 1. The old two-number gate would have shipped it.
    bad_ece = dict(_GOOD_REPORT, ece=0.4)
    code, out = _run(bad_ece)
    assert code == 1, (code, out)

    # a rule collapsing below the per-rule floor is caught the same way
    bad_rule = dict(_GOOD_REPORT, per_rule={"ok": [200, 300], "spam": [1, 40]})
    code, out = _run(bad_rule)
    assert code == 1, (code, out)

    # zero abstention: the band requires > 0 — abstention vanishing is a fail
    no_abstain = dict(_GOOD_REPORT, abstention_rate=0.0)
    code, out = _run(no_abstain)
    assert code == 1, (code, out)


# --- T916: provenance — every log line traces to data + code + knobs --------

def test_provenance_fallbacks_are_honest():  # T916
    """Missing inputs degrade to None/absence, never to invented values: an
    unreadable file leaves no dataset hash (provenance must not crash a run),
    and the config always records itself — it's knowable on any machine."""
    mod = _import_train()
    mod.PROVENANCE.clear()
    mod.fill_provenance("/nonexistent/definitely-missing.jsonl")
    assert mod.PROVENANCE["dataset_sha256"] is None, "no file, no hash"
    assert mod.PROVENANCE["dataset_path"] == "definitely-missing.jsonl"
    assert mod.PROVENANCE["config"]["seed"] == 7, "config is always knowable"


def test_provenance_stamps_the_train_trail_source():  # T916: source wiring
    src = TRAIN.read_text()
    # filled right after the data is read — before anything logs
    assert src.index("fill_provenance(paths[0])") < src.index("for epoch in range(start_epoch")
    # every log_rec line carries it (stamped in log_rec, not per-call-site)
    assert "for k, v in PROVENANCE.items()" in src
    # provenance is recorded before the first record can possibly be written
    assert "log_rec(kind=" in src


# --- T917: the HF upload folder ships a model card ---------------------------

def test_model_card_generated_source_true(tmp_path):  # T917
    """write_model_card() produces the README the upload_folder was missing:
    run metrics from THIS run's numbers (not documentation defaults), the
    T916 provenance record, the gate verdict, and the synthetic-distribution
    caveat — the card never claims more than the run measured. And main()
    writes it BEFORE upload_folder, so the weights can't ship cardless."""
    mod = _import_train()

    data = tmp_path / "rows.jsonl"
    data.write_text('{"state": {}, "labels": {}}\n')
    mod.fill_provenance(str(data))

    # a passing run's card
    card_path = mod.write_model_card(str(tmp_path), 0.517, 0.46, True)
    card = Path(card_path).read_text()
    assert card_path.endswith("README.md")
    assert "dev rule_acc: 0.517" in card, "THIS run's number, printed as measured"
    assert "held-out test rule_acc: 0.460" in card
    assert "PASS" in card and "not pushed" not in card
    assert "ship floor 0.35" in card and "regex floor 0.403" in card
    # provenance lands in the card too (T916 record, reused not re-invented)
    assert data.name in card and mod.PROVENANCE["dataset_sha256"] in card
    assert "seed=7" in card
    # honesty stays in: the distribution caveat and the null-git explanation
    assert "same synthetic distribution" in card and "unmeasured" in card
    assert "not hand-edited" in card
    assert "Intended use" in card and "bouncer-421m" in card

    # a refused/failed run's card says so — it does not print PASS
    fail_path = mod.write_model_card(str(tmp_path), 0.30, 0.25, False)
    fail_card = Path(fail_path).read_text()
    assert "not pushed" in fail_card, "the verdict travels with the artifact"
    assert "FAIL or not run" in fail_card

    # a gate that never ran (None) reads as not-pushed, not as PASS
    none_path = mod.write_model_card(str(tmp_path), 0.5, 0.5, None)
    none_card = Path(none_path).read_text()
    assert "FAIL or not run" in none_card and "PASS" not in none_card.split("thresholds")[1]


def test_model_card_written_before_push_and_logged():  # T917: source wiring
    src = TRAIN.read_text()
    # generated after the gate verdict (so the card carries it), before upload
    assert src.index("write_model_card(OUT, best_dev, test_acc, gate_pass)") < \
        src.index("api.upload_folder(folder_path=OUT")
    assert src.index("gate_pass = g.returncode == 0") < \
        src.index("write_model_card(OUT, best_dev, test_acc, gate_pass)")
    # the card generation is in the trail (T654) with its gate verdict
    assert 'log_rec(kind="model_card"' in src
    # upload_folder ships the whole folder — README.md rides along
    assert 'api.upload_folder(folder_path=OUT' in src


# --- T918: eval_i18n measures a fine-tuned run itself (--model) --------------

def test_eval_i18n_model_flag_fails_loudly_on_bad_dir(tmp_path):  # T918
    """--model DIR makes eval_i18n score per-language decision quality against
    that checkpoint. A dir that isn't a checkpoint fails the SAME way whether
    or not laya is installed (the artifact check precedes the import — honest
    ordering): status=fail with a receipt, and exit 1 so CI can't miss it.
    The routing section still ran — it's weightless."""
    import json as _json

    r = subprocess.run(
        [sys.executable, "eval/eval_i18n.py", "--json",
         "--model", str(tmp_path / "not-a-checkpoint"), "--out",
         str(tmp_path / "i18n.json")],
        check=False, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1, (r.returncode, r.stdout[-500:], r.stderr)
    report = _json.loads((tmp_path / "i18n.json").read_text())
    q = report["quality"]
    assert q["status"] == "fail", q
    assert "rl_agent_config.json" in q["receipt"], "names exactly what was missing"
    # the weightless sections still measured — quality failing doesn't erase them
    assert report["errors"] == []
    assert report["routing"]["wrong"] == []


def test_eval_i18n_model_flag_untouched_default(tmp_path):  # T918: no flag, no change
    """Without --model the quality section is exactly the pre-T918 behavior
    (skip-with-receipt or weights-present pointer) — the flag is additive."""
    import json as _json

    r = subprocess.run(
        [sys.executable, "eval/eval_i18n.py", "--json", "--out",
         str(tmp_path / "i18n.json")],
        check=False, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    report = _json.loads((tmp_path / "i18n.json").read_text())
    q = report["quality"]
    assert q["status"] != "measured" and q["status"] != "fail", \
        "no --model means no measurement was requested"


def test_eval_i18n_score_model_honest_branches():  # T918: unit-level branches
    """score_model's three branches without a GPU: missing artifact fails
    (before any laya import), a valid-looking dir with laya absent skips with
    a receipt naming the model, and a load failure records WHY instead of
    crashing or fabricating a score."""
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, "eval")
    import eval_i18n

    # branch 1: not a checkpoint -> fail (runs before laya import: identical
    # verdict with or without laya, so this test passes in BOTH environments)
    out = eval_i18n.score_model("/nonexistent/ckpt", [], lambda r: "es")
    assert out["status"] == "fail" and "rl_agent_config.json" in out["receipt"]

    # a dir WITH the artifact but without weights under it: laya's verdict
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        _Path(d, "rl_agent_config.json").write_text("{}")
        try:
            import laya  # noqa: F401
            has_laya = True
        except ModuleNotFoundError:
            has_laya = False
        out = eval_i18n.score_model(d, [], lambda r: "es")
        if not has_laya:
            assert out["status"] == "skipped", out
            assert d in out["receipt"], "the receipt names the model given"
        else:
            # with laya present, an empty config either fails to load (fail,
            # receipt says why) or loads and scores zero rows (measured n=0)
            assert out["status"] in ("fail", "measured"), out
            if out["status"] == "measured":
                assert out["n"] == 0


def test_eval_i18n_model_flag_source_wiring():  # T918: the CLI surface
    src = Path("eval/eval_i18n.py").read_text()
    assert 'ap.add_argument("--model"' in src, "the flag exists and is documented"
    # artifact check precedes the laya import — bad dir fails identically
    # whether or not laya is installed (the CI/local determinism guarantee)
    assert src.index("rl_agent_config.json") < src.index("import laya")
    # a failed requested measurement exits nonzero — never exit 0 + receipt
    assert 'sys.exit(1)' in src and 'status"] == "fail"' in src
    # scoring runs on CPU: no GPU needed to evaluate a run's i18n quality
    assert 'device="cpu"' in src
