"""P48: fine-tune pipeline boxes T911+.

train.py is a Kaggle script, not a library — these tests pin the parts that
must hold on ANY machine (import safety, config validation) without a GPU,
weights, or network.
"""
import importlib.util
import json
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


# --- T919: parse + dry-run config-validate on CPU, end to end ----------------

def test_train_parses_and_dry_run_config_validates_end_to_end():  # T919
    """The whole T919 contract through the CLI, no torch/weights/GPU touched:
    the module PARSES on CPU (import runs argparse + constants only), a good
    config exits 0 with DRY_RUN_OK printing the knobs it read, and a broken
    config exits 2 with DRY_RUN_FAIL naming the flag — config-validation
    refuses bad values BEFORE quota is spent, not after."""
    # 1. parses: import is pure argparse + constants (hostile proof — any
    # subprocess during import would be the pip install, already forbidden)
    mod = _import_train()
    assert mod.MAX_SAMPLES == 0 and mod.EPOCHS_FLAG == 0
    assert mod.DRY_RUN is False

    # 2. good config: exit 0, knobs echoed back
    good = subprocess.run([sys.executable, str(TRAIN), "--dry-run", "--seed", "42"],
                          check=False, capture_output=True, text=True, timeout=60)
    assert good.returncode == 0, good.stderr
    assert "DRY_RUN_OK" in good.stdout and "seed=42" in good.stdout

    # 3. broken config: exit 2, DRY_RUN_FAIL names the offending flag —
    # end-to-end through the CLI, not just the in-process validator
    bad = subprocess.run([sys.executable, str(TRAIN), "--dry-run", "--epochs", "-1"],
                         check=False, capture_output=True, text=True, timeout=60)
    assert bad.returncode == 2, (bad.returncode, bad.stdout, bad.stderr)
    assert "DRY_RUN_FAIL" in bad.stderr and "--epochs" in bad.stderr, \
        "the refusal names the flag a human can fix"
    assert "DRY_RUN_OK" not in bad.stdout, "a failed validation never prints OK"

    # 4. and it never imported the heavy deps: no torch needed for any of it
    probe = subprocess.run(
        [sys.executable, "-c",
         ("import importlib.util as u; "
          f"spec = u.spec_from_file_location('t', {str(TRAIN)!r}); "
          "m = u.module_from_spec(spec); spec.loader.exec_module(m); "
          "import sys; print('TORCH' if 'torch' in sys.modules else 'CLEAN')")],
        check=False, capture_output=True, text=True, timeout=60)
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "CLEAN", "import pulls no torch on a CPU box"


# --- T920: ship-gate thresholds == gate.py defaults, one source --------------

def test_ship_gate_thresholds_single_sourced_from_gate_py():  # T920
    """No drift copy: train.py's REGEX_FLOOR must be gate.py's --min-rule-acc
    default (the same 0.403 both call the regex baseline), and the ship gate
    passes NO threshold flags to gate.py — so a threshold moved in gate.py
    moves the ship gate too, and a threshold moved in ONLY one place fails
    this test instead of a future push."""
    import re as _re

    mod = _import_train()
    gate_src = Path("eval/gate.py").read_text()
    train_src = TRAIN.read_text()

    def _default(flag):
        m = _re.search(
            rf'add_argument\("{flag}",\s*type=float,\s*default=([0-9.]+)', gate_src)
        assert m, f"gate.py no longer declares {flag} with a plain default"
        return float(m.group(1))

    # the accuracy floor is one number in two names — pinned equal
    assert mod.REGEX_FLOOR == _default("--min-rule-acc"), \
        "train.py's regex floor drifted from gate.py's rule_acc threshold"

    # the ship gate invokes gate.py with no threshold overrides: defaults ARE
    # the thresholds (T915's design, re-asserted here as the no-drift clause)
    assert "--min-rule-acc" not in train_src and "--max-ece" not in train_src
    assert "--min-abstention" not in train_src and "--min-per-rule-acc" not in train_src
    gate_call = _re.search(
        r'subprocess\.run\(\[sys\.executable, gt, [^\]]*\]', train_src)
    assert gate_call, "the ship gate's gate.py call exists"
    assert "--" not in gate_call.group(0).split("gt,")[1], \
        "no flags ride along — gate.py defaults are the single source"


def test_gate_py_threshold_defaults_unchanged_shape():  # T920: the flags exist
    """T920's regexes pin real flags: if gate.py renames a threshold or moves
    its default off a plain literal (say, a computed baseline), this test
    fails first — so the single-source assertion above can never silently
    stop matching."""
    gate_src = Path("eval/gate.py").read_text()
    for flag in ("--min-rule-acc", "--max-ece", "--min-abstention",
                 "--max-abstention", "--min-per-rule-acc"):
        assert f'add_argument("{flag}"' in gate_src, flag
    # the docs-drift gate (T684) also knows these numbers — same source chain
    assert "regex_floor" in gate_src and "max_ece" in gate_src


# --- T921: provenance fields present in log_rec OUTPUT -----------------------

def test_provenance_fields_present_in_log_rec_output(tmp_path):  # T921
    """log_rec stamps dataset_sha256 + git_sha + config into every record, so
    any number in train_log.jsonl can be traced back to the exact file hashed,
    the commit that ran, and the knobs used. Fill it against a real file, call
    log_rec, read the line back — the fields are IN the output, not just in a
    source comment."""
    import json as _json

    mod = _import_train()
    data = tmp_path / "rows.jsonl"
    data.write_text('{"state": {}, "labels": {}}\n')

    mod.fill_provenance(str(data))
    assert set(mod.PROVENANCE) >= {"dataset_path", "dataset_sha256", "git_sha", "config"}

    # dataset hash: sha256 of the bytes actually read, not a placeholder
    import hashlib as _hashlib
    assert mod.PROVENANCE["dataset_sha256"] == _hashlib.sha256(
        data.read_bytes()).hexdigest()
    assert mod.PROVENANCE["dataset_path"] == "rows.jsonl"

    # config carries the knobs verbatim (T913/T914/T912 surface)
    cfg = mod.PROVENANCE["config"]
    assert cfg["seed"] == 7 and cfg["max_samples"] == 0 and cfg["resume"] is False
    assert cfg["lora"]["target_modules"] == ["query", "value"]
    assert cfg["dev_floor"] == 0.35 and cfg["regex_floor"] == 0.403

    # git sha: real sha in a checkout, None (not a fake) when git is absent
    if mod.PROVENANCE["git_sha"] is not None:
        assert len(mod.PROVENANCE["git_sha"]) >= 7

    # the fields land in the WRITTEN line — this is T921's assertion
    mod.t0 = 0.0  # log_rec computes t from the clock; any value works
    real_log = tmp_path / "train_log.jsonl"
    mod.LOG = str(real_log)
    mod.log_rec(kind="step", epoch=1, step=1, loss=1.0)
    line = _json.loads(real_log.read_text().splitlines()[-1])
    assert line["kind"] == "step"
    assert line["dataset_sha256"] == mod.PROVENANCE["dataset_sha256"]
    assert line["git_sha"] == mod.PROVENANCE["git_sha"]
    assert line["config"]["seed"] == 7
    assert "t" in line, "the T654 timestamp survives"

    # a second record keeps provenance AND stays append-only (T654 contract)
    mod.log_rec(kind="epoch", epoch=1, avg_loss=0.5)
    lines = real_log.read_text().splitlines()
    assert len(lines) == 2
    second = _json.loads(lines[-1])
    assert second["dataset_sha256"] == line["dataset_sha256"], "every line carries it"
    assert second["kind"] == "epoch"


# --- T922: kaggle/README documents flags, resume, and the gate order --------

def test_kaggle_readme_documents_flags_resume_gate_order():  # T922
    """kaggle/README.md must document every flag the script actually parses,
    the resume semantics, and the gate order an upload must survive —
    cross-checked against BOTH sources (train.py's argparse and gate.py's
    invocation), so a flag added without docs, or a documented flag that
    doesn't exist, fails here."""
    readme = Path("kaggle/README.md").read_text()
    src = TRAIN.read_text()

    # every flag train.py parses is in the README table
    import re as _re
    script_flags = set(_re.findall(r'add_argument\("(--[a-z-]+)"', src))
    assert script_flags, "train.py has flags"
    for flag in script_flags:
        assert flag in readme, f"{flag} not documented in kaggle/README.md"

    # and no documented flag is fictional
    for flag in set(_re.findall(r"`(--[a-z-]+)`", readme)):
        assert flag in script_flags, f"README documents {flag} which train.py lacks"

    # resume semantics: the three artifacts and the honest limitation
    for word in ("checkpoint_latest", "train_state.json", "optim.pt"):
        assert word in readme, word
    assert "not the best" in readme, "the resume limitation stays honest"

    # gate order: eval -> gate.py -> model card -> push, in that order
    order = ["3. **eval_gatekeeper", "4. **gate.py", "5. **model card",
             "6. **push**"]
    positions = [readme.index(s) for s in order]
    assert positions == sorted(positions), "the gate order reads in real order"
    assert "single source" in readme and "T920" in readme
    assert "gate_pass=None" in readme, "a gate that never ran refuses (T915)"

    # no-push row names the new full-gate reason, not just the old two floors
    assert "full_gate" in readme and "ECE" in readme

    # honest status — nothing here pretends the run happened
    assert "NOT RUN" in readme


def test_kaggle_readme_matches_reality_surfaces():  # T922: receipts cross-file
    """The README's claims point at things that exist: the smoke path, the
    dry-run, the i18n eval of a run, the tests that pin it, and the T-numbers
    it cites are all real boxes."""
    import re as _re

    readme = Path("kaggle/README.md").read_text()
    assert Path("kaggle/train/train.py").exists()
    assert Path("scripts/check_kaggle_env.py").exists()
    assert "tests/test_p48.py" in readme
    assert "eval/eval_i18n.py --model" in readme.replace("`", "")
    assert "test_train_parses_and_dry_run_config_validates_end_to_end" in readme

    # citation integrity: every box the README cites exists in TODO.md
    todo = Path("TODO.md").read_text()
    for t in set(_re.findall(r"\bT\d{3,4}\b", readme)):
        assert t in todo, f"kaggle/README cites unknown box {t}"


# --- T923: notebook paste-in signature drift vs train.py is a failure --------

def test_finetune_pastein_matches_train_signature(tmp_path):  # T923
    """finetune_kaggle.to_laya_records (the 3 cells you paste into a notebook)
    and train.py's to_row must produce the SAME record for the same row —
    identical question types, instructions, criteria, and expected mapping.
    Drift used to be a comment saying 'keep the notebook's call'; now it's a
    test failure: a paste-in that half-matches the pipeline would reject
    records late, on quota time."""
    import sys as _sys

    mod = _import_train()
    _sys.path.insert(0, "notebooks")
    import finetune_kaggle

    row = {
        "state": {"message": "BUY NOW!!!", "history": ["hi"],
                  "rules": {"caps": "no caps", "spam": "no spam"}},
        "labels": {"rule": "spam", "harm": "suspicious", "hype": "hyped",
                   "jailbreak": False, "escalate": True},
    }
    src_file = tmp_path / "rows.jsonl"
    src_file.write_text(json.dumps(row) + "\n")

    paste_in = finetune_kaggle.to_laya_records(str(src_file))[0]
    in_script = mod.to_row(row)
    assert paste_in == in_script, (
        "notebook paste-in and train.py disagree on the record shape — "
        f"paste-in keys {sorted(paste_in)} vs {sorted(in_script)}")

    # the deep claim: question specs and expected mapping are identical
    assert paste_in["questions"] == in_script["questions"]
    assert paste_in["expected"] == in_script["expected"]
    # shared vocab stays shared (the label enums must not fork)
    assert finetune_kaggle.HARM == mod.HARM
    assert finetune_kaggle.HYPE == mod.HYPE


def test_finetune_pastein_fallback_removed():  # T923: the warning is now a failure
    """The 'if the function name drifted, keep its call' escape hatch is gone
    — the comment must point at the enforcing test instead, so nobody follows
    stale advice into a half-compatible paste-in."""
    src = Path("notebooks/finetune_kaggle.py").read_text()
    assert "keep the notebook's call" not in src and "only swap `recs`" not in src, \
        "the fallback advice was removed, not reworded"
    assert "test_finetune_pastein_matches_train_signature" in src, \
        "the comment names the test that enforces it"
    assert "FAILURE" in src and "T923" in src


# --- T924: data gate runs BEFORE training start — hash mismatch refuses -------

def _good_row(rule="spam"):
    return {"state": {"message": "BUY NOW!!!", "history": ["hi"],
                      "rules": {"caps": "no caps", "spam": "no spam"}},
            "labels": {"rule": rule, "harm": "suspicious", "hype": "hyped",
                       "jailbreak": False, "escalate": True}}


def test_data_gate_clean_dataset_passes(tmp_path):  # T924
    """validate_data reports zero problems on a well-formed file and the
    receipt distinguishes 'no pin to check' from 'pin matched' — an absent
    sidecar must never read as a pass."""
    mod = _import_train()
    data = tmp_path / "rows.jsonl"
    data.write_text(json.dumps(_good_row()) + "\n")

    out = mod.data_gate(str(data))
    assert out["problems"] == [], out
    assert out["pin"] == "absent", "no sidecar: recorded as absent, not as match"

    # with the publisher's pin present and matching, the pin reads as a match
    import hashlib

    digest = hashlib.sha256(data.read_bytes()).hexdigest()
    (tmp_path / "rows.jsonl.sha256").write_text(f"{digest}  rows.jsonl\n")
    out = mod.data_gate(str(data))
    assert out["problems"] == [] and out["pin"] == "match", out


def test_data_gate_hash_mismatch_refuses(tmp_path):  # T924
    """A sidecar that doesn't hash to the bytes on disk means this is not the
    dataset that was published — the gate refuses with BOTH digests named, and
    refusing here means refusing BEFORE training, not before push."""
    mod = _import_train()
    data = tmp_path / "rows.jsonl"
    data.write_text(json.dumps(_good_row()) + "\n")
    (tmp_path / "rows.jsonl.sha256").write_text(
        f"{'0' * 64}  rows.jsonl\n")  # some other dataset's digest

    out = mod.data_gate(str(data))
    assert out["pin"] == "mismatch"
    assert out["problems"], "a hash mismatch must refuse"
    msg = out["problems"][0]
    assert "hash mismatch" in msg and "0" * 12 in msg, msg
    assert "upload_dataset_kaggle" in msg, "the refusal names the fix"


def test_data_gate_bad_rows_refuse(tmp_path):  # T924
    """Schema problems from eval/validate_data.py refuse too — including bad
    JSON, which raw json.loads would only reveal as a traceback mid-read."""
    mod = _import_train()
    data = tmp_path / "rows.jsonl"
    data.write_text(json.dumps(_good_row()) + "\n"
                    + '{"state": "not-an-object"}\n'
                    + "{not json at all\n")

    out = mod.data_gate(str(data))
    assert len(out["problems"]) >= 2, out
    assert any("schema" in p for p in out["problems"]), out
    assert any("bad JSON" in p for p in out["problems"]), out


def test_data_gate_unreachable_checker_refuses(monkeypatch, tmp_path):  # T924
    """A checker that can't be found is a problem, never a green light — the
    same rule the ship gate applies (T915)."""
    mod = _import_train()
    monkeypatch.setattr(mod, "find_validate_data", lambda: None)
    data = tmp_path / "rows.jsonl"
    data.write_text(json.dumps(_good_row()) + "\n")

    out = mod.data_gate(str(data))
    assert out["problems"], "no checker -> refuse, not pass"
    assert "validate_data.py not reachable" in out["problems"][0]
    assert "kernel input" in out["problems"][0]
    assert out["pin"] == "not checked"


def test_data_gate_wired_before_training_source():  # T924: source wiring
    """The gate sits in main() before rows are read and before the epoch loop,
    it logs a receipt, and refusal is a training refusal (return 1), not just
    a push refusal. Provenance is filled first so the receipt carries the hash."""
    src = TRAIN.read_text()
    gate = src.index("gate = data_gate(paths[0])")
    rows = src.index("rows_raw = [json.loads")
    loop = src.index("for epoch in range(start_epoch, EPOCHS)")
    assert src.index("fill_provenance(paths[0])") < gate, \
        "provenance first: the data_gate receipt must carry dataset_sha256"
    assert gate < rows < loop, "the gate runs before the data is even parsed"
    assert 'log_rec(kind="data_gate"' in src, "the refusal/pass is in the trail"
    assert "return 1" in src[src.index("gate = data_gate"):loop], \
        "a refused dataset must stop the run, not just the push"
    # pin side: the uploader stages a .sha256 per file (the gate's counterpart)
    up = Path("scripts/upload_dataset_kaggle.py").read_text()
    assert ".sha256" in up and "sha256_file" in up
    assert "stage(" in up, "staging writes the pins alongside the dataset"


def test_upload_dataset_stage_writes_matching_pins(tmp_path):  # T924: producer side
    """The pins upload writes are exactly what train.py's gate checks — a
    round-trip: stage the files, hand the staged copy to data_gate, match.
    Tamper with one byte and the same call refuses."""
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location(
        "upload_dataset_kaggle", Path("scripts/upload_dataset_kaggle.py"))
    up = _ilu.module_from_spec(spec)
    spec.loader.exec_module(up)

    src = tmp_path / "gatekeeper-12k.jsonl"
    src.write_text(json.dumps(_good_row()) + "\n")
    stage_dir = tmp_path / "stage"
    staged = up.stage([str(src)], str(stage_dir))

    pin = stage_dir / "gatekeeper-12k.jsonl.sha256"
    assert pin.exists(), f"staging must write pins: staged={staged}"
    assert Path(staged[-1]).name == pin.name

    mod = _import_train()
    out = mod.data_gate(str(stage_dir / "gatekeeper-12k.jsonl"))
    assert out["problems"] == [] and out["pin"] == "match", out

    # one flipped byte on the way to the kernel -> mismatch, refuse
    staged_file = stage_dir / "gatekeeper-12k.jsonl"
    staged_file.write_text(staged_file.read_text().replace("spam", "spzm"))
    out = mod.data_gate(str(staged_file))
    assert out["pin"] == "mismatch" and out["problems"], out


def test_log_rec_safe_before_clock_and_creates_log_dir(tmp_path):  # T924 plumbing
    """Records written before the training clock starts (the data-gate receipt,
    the --resume record) carry t=null instead of crashing on None, and the log
    directory is created — the trail can open before any checkpoint exists."""
    mod = _import_train()
    mod.t0 = None
    mod.LOG = str(tmp_path / "not_yet" / "train_log.jsonl")
    mod.log_rec(kind="data_gate", pin="absent", refused=False)
    line = json.loads(Path(mod.LOG).read_text())
    assert line["kind"] == "data_gate" and line["t"] is None
    # once the clock runs, t is a number again
    mod.t0 = 0.0
    mod.log_rec(kind="step", epoch=1, step=1, loss=1.0)
    line = json.loads(Path(mod.LOG).read_text().splitlines()[-1])
    assert isinstance(line["t"], float)


# --- T925: eval report naming/shape matches gate.py's kind dispatch ---------

_STUB_LAYA = '''
class Router:
    def __init__(self, **kw):
        pass

    def predict(self, state, questions, model=None, **kw):
        return {"answers": {
            "rule": {"choice": "ok", "confidence": 0.9, "probabilities": {"ok": 0.9}},
            "harm": {"score": "safe", "probabilities": []},
            "hype": {"score": "chill", "probabilities": []},
            "jailbreak": {"noul": 0.0}, "escalate": {"noul": 0.0}}}
'''


def test_eval_report_shape_dispatches_to_full_eval_collector(tmp_path):  # T925
    """gate.py picks a collector by report SHAPE (detect_kind), and the
    fine-tune pipeline writes eval_gatekeeper's output (eval_test.json) into
    the full "eval" collector — the one carrying every ship threshold. The
    proof runs the real producer (stub laya, like T583) and the real gate on
    its file: dispatch == eval, and the verdict's check names are the whole
    threshold set. The hazard is one borrowed key: a single per_lang/routing/
    tripped/speedup/bench in that report reroutes the verdict to a narrower
    collector while gate.py still exits 0 — so the sentinel keys are pinned
    absent from what the producer actually writes."""
    import os as _os

    (tmp_path / "laya.py").write_text(_STUB_LAYA)
    data = tmp_path / "rows.jsonl"
    row = {"state": {"message": "hello there", "history": [],
                     "rules": {"be-kind": "be nice"}},
           "labels": {"rule": "ok", "harm": "safe", "hype": "chill",
                      "jailbreak": False, "escalate": False}}
    data.write_text(json.dumps(row) + "\n")
    env = {**_os.environ, "PATH": "/usr/bin:/bin",
           "PYTHONPATH": f"src:{tmp_path}"}
    out = tmp_path / "eval_test.json"  # the exact name train.py writes
    r = subprocess.run([sys.executable, "eval/eval_gatekeeper.py", str(data),
                        "--limit", "1", "--out", str(out)],
                       check=False, capture_output=True, text=True, env=env,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())

    sys.path.insert(0, "eval")
    import gate

    # the producer's shape routes to the FULL eval collector
    assert gate.detect_kind(rep) == "eval"
    sentinels = {"per_lang", "routing", "tripped", "closed",
                 "speedup", "thrash", "bench"}
    assert not (set(rep) & sentinels), "a sentinel key would reroute the gate"
    # the hazard is real: ONE borrowed key changes the family
    assert gate.detect_kind(dict(rep, per_lang={})) == "i18n"
    assert gate.detect_kind(dict(rep, speedup=1.0)) == "pool"

    # the exact subprocess train.py runs: gate.py -- <report>, defaults only
    r2 = subprocess.run([sys.executable, "eval/gate.py", "--json", str(out)],
                        check=False, capture_output=True, text=True, timeout=60)
    verdict = json.loads(r2.stdout)
    names = {c["name"] for c in verdict["checks"]}
    assert {"report_n", "report_rule_acc", "rule_acc", "ece", "p95_ms",
            "abstention_rate", "per_rule_worst"} <= names, names


def test_eval_out_name_is_the_gated_report_name():  # T925: naming wiring
    """One name on both sides of the ship gate: eval_gatekeeper's --out and
    gate.py's report argument are the same os.path.join(OUT, "eval_test.json"),
    eval runs before the gate, and gate_pass starts as None — so the gate can
    only ever judge the file the eval just wrote, never a stale leftover from
    an earlier run."""
    src = TRAIN.read_text()
    ev_out = src.index('"--out", os.path.join(OUT, "eval_test.json")')
    gate_arg = src.index("gt, os.path.join(OUT, \"eval_test.json\")")
    assert ev_out < gate_arg, "eval writes the name gate.py later reads"
    # exactly two uses: the producer's --out and the gate's argument
    assert src.count('os.path.join(OUT, "eval_test.json")') == 2
    assert "gate_pass = None" in src, "not-run starts as refuse, not pass"


# --- T926: bouncer-ft smoke — the fine-tune pre-flight, scripted on CPU ------

FT_SMOKE = Path("scripts/ft_smoke.py")


def test_ft_smoke_passes_on_cpu_without_cuda():  # T926
    """`bouncer-ft smoke` is the whole pre-flight in one command: train.py's
    dry run (config parse + validate_config) chained with the dataset schema
    check — no weights, no GPU, no torch. It passes on THIS interpreter,
    which has no training stack installed: the proof of "without CUDA" is a
    green run where CUDA cannot exist."""
    import os as _os

    env = {**_os.environ, "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(FT_SMOKE), "--json"],
                       check=False, capture_output=True, text=True, env=env,
                       timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["ok"] is True, rep
    by_step = {s["step"]: s for s in rep["steps"]}
    assert set(by_step) == {"dataset", "dry_run", "validate_data"}
    assert all(s["ok"] for s in rep["steps"]), rep
    # the dry run is the REAL one: the contract token proves config validation
    # happened, not just a zero exit
    assert "DRY_RUN_OK" in by_step["dry_run"]["detail"]
    # and the script stays weightless: no torch anywhere in its source
    assert "torch" not in FT_SMOKE.read_text()


def test_ft_smoke_names_the_failing_step():  # T926: refusals are pointed
    """A bad dataset fails the smoke WITHOUT failing the other steps: the
    receipt shows dataset+dry_run green and validate_data red, stderr names
    the failing step in FT_SMOKE_FAIL, and a missing dataset is reported as
    such — never a traceback pretending the file was fine."""
    import os as _os

    bad = Path.cwd() / "ft_smoke_bad.jsonl"
    bad.write_text(json.dumps({"nope": 1}) + "\n")
    env = {**_os.environ, "PATH": "/usr/bin:/bin"}
    try:
        r = subprocess.run([sys.executable, str(FT_SMOKE), "--json",
                            "--dataset", str(bad)],
                           check=False, capture_output=True, text=True, env=env,
                           timeout=300)
    finally:
        bad.unlink(missing_ok=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    by_step = {s["step"]: s for s in rep["steps"]}
    assert by_step["dataset"]["ok"] is True  # the file exists — it's the rows
    assert by_step["dry_run"]["ok"] is True  # config is fine; data is not
    assert by_step["validate_data"]["ok"] is False
    assert "FT_SMOKE_FAIL: validate_data" in r.stderr

    # missing dataset: named, not crashed
    r = subprocess.run([sys.executable, str(FT_SMOKE), "--json",
                        "--dataset", "/nonexistent/ft.jsonl"],
                       check=False, capture_output=True, text=True, env=env,
                       timeout=300)
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    by_step = {s["step"]: s for s in rep["steps"]}
    assert by_step["dataset"]["ok"] is False
    assert "not found" in by_step["dataset"]["detail"]
    assert "FT_SMOKE_FAIL:" in r.stderr


def test_ft_smoke_drives_the_pinned_pre_flight_surfaces():  # T926: wiring
    """The smoke chains the SAME two pre-flights the rest of the repo pins:
    train.py --dry-run (T911/T919) and eval/validate_data.py (T381, the
    checker behind the T924 data gate). If either surface moves and the
    smoke doesn't follow, it would go red on CI before anything trains —
    so the exact invocations are pinned here."""
    src = FT_SMOKE.read_text()
    assert '"--dry-run"' in src, "the config-parse step invokes the dry run"
    assert "validate_data.py" in src, "the data step invokes the schema checker"
    # the smoke is a runner, not a copy: no schema rules or config rules live
    # here — those stay single-sourced in their own scripts
    assert "def check_row" not in src and "def validate_config" not in src
    # the default dataset is the one shipped in the repo, so a fresh clone
    # can run the smoke before building the 12k set
    assert "data/examples.jsonl" in src


# --- T927: nightly runs the fine-tune CPU smoke ------------------------------

def test_nightly_runs_the_ft_cpu_smoke():  # T927
    """The nightly workflow gained an ft-smoke job: the same one-command
    pre-flight a human runs locally (T926), on the night's dependency
    resolution — config parse + data validate, no weights, no CUDA. The job
    invokes the SCRIPT (single source, not a copy of its steps), installs
    the same open-floor dev extras as the suite, and the workflow keeps
    its no-push-trigger contract (ci.yml owns pushes, T748)."""
    import re as _re

    text = Path(".github/workflows/nightly.yml").read_text()
    header, _, body = text.partition("jobs:")
    assert "push" not in header, "nightly must not double ci.yml"
    m = _re.search(r"^  ft-smoke:(.*?)(?=^  \w|\Z)", body,
                   _re.MULTILINE | _re.DOTALL)
    assert m, "no ft-smoke job in nightly.yml"
    job = m.group(1)
    assert "python scripts/ft_smoke.py" in job, "the job runs the T926 script"
    assert ".[dev]" in job, "same open-floor install as the suite job"
    # no GPU runner: this job must stay CPU-only
    assert "runs-on: ubuntu-latest" in job, "CPU runner only"
    assert "gpu" not in job.lower() and "nvidia" not in job.lower()
    # and the smoke's own contract still holds — the job is only useful
    # because the script refuses (exit 1) on a failed step
    assert FT_SMOKE.exists(), "the nightly job's script was removed"


# --- T928: ROADMAP fine-tune section — pipeline receipts, status NOT RUN -----

def test_roadmap_finetune_section_lists_pipeline_receipts_honestly():  # T928
    """ROADMAP's fine-tune section now names what P48 actually built (dry
    run, resume, provenance, model card, data gate, full ship gate, the
    CPU smoke and its nightly job) — while the status line stays NOT RUN
    and the closing bullet says plainly that receipts on the PATH are not
    a trained checkpoint. Every box it cites must exist in TODO.md (the
    same citation-integrity rule docs tests already enforce), so the page
    can't thank a box that was never written."""
    import re as _re

    rm = Path("docs/ROADMAP.md").read_text()
    assert "Fine-tune results (status: NOT RUN)" in rm
    # the pipeline receipts are listed, and so is their limit
    for needle in ("tests/test_p48.py", "scripts/ft_smoke.py",
                   "T911/T919", "T915/T920", "T924", "T926", "T927"):
        assert needle in rm, needle
    assert "not that a checkpoint was trained" in rm, \
        "receipts on the path must not read as a run"
    # status honesty survives the addition: no run, no after-column
    assert "has **not run**" in rm and 'mode:"real"' in rm
    # citation integrity: every T-number on the page is a real box
    todo = Path("TODO.md").read_text()
    for t in set(_re.findall(r"\bT\d{3,4}\b", rm)):
        assert t in todo, f"ROADMAP cites unknown box {t}"


# --- T930: P48 closer — every box ticked, receipts outside TODO.md ----------

def test_p48_finetune_pipeline_sweep():  # T930: every box T911-T930 ticked,
    # every box has a receipt outside TODO.md, no invented citations
    import re as _re

    todo = Path("TODO.md").read_text()
    p48 = [b for b in _re.findall(r"- \[[ x]\] (T\d{3,4})\b", todo)
           if 911 <= int(b[1:]) <= 930]
    assert sorted(p48) == [f"T{n}" for n in range(911, 931)], p48
    for b in p48:
        assert f"- [x] {b}" in todo, f"{b} unticked"
    assert "## P48 Fine-tune pipeline (T911–T930)" in todo

    # receipts live OUTSIDE TODO.md — across this batch's own surfaces:
    # the train script, its README, the smoke + publisher scripts, the
    # nightly workflow, ROADMAP, and the tests themselves
    corpus = (Path("README.md").read_text()
              + Path("CONTRIBUTING.md").read_text()
              + Path("verify.sh").read_text())
    for root in ("docs", "tests", "src", ".github", "eval", "kaggle",
                 "scripts", "notebooks"):
        for p in Path(root).rglob("*"):
            if (p.is_file()
                    and p.suffix in (".md", ".py", ".yml", ".yaml", ".sh")):
                corpus += p.read_text()
    for b in p48:
        assert b in corpus, f"{b} has no receipt outside TODO.md"

    # citation integrity: every T-number on the surfaces this batch touched
    # is a box TODO.md actually knows — invented receipts fail here
    for f in (Path("kaggle/README.md"), Path("kaggle/train/train.py"),
              Path("scripts/ft_smoke.py"),
              Path("scripts/upload_dataset_kaggle.py"),
              Path(".github/workflows/nightly.yml"),
              Path("docs/ROADMAP.md")):
        for t in set(_re.findall(r"T\d{3,4}", f.read_text())):
            assert t in todo, (str(f), f"cites unknown box {t}")

    # the pipeline's gates are all on their surfaces, not just in TODO:
    # data gate before training, full ship gate, named refusals
    train = TRAIN.read_text()
    assert "DATA_GATE" in train and "gate_pass = None" in train
    readme = Path("kaggle/README.md").read_text()
    assert "NOT RUN" in readme, "the run status stays honest"
    assert Path("scripts/ft_smoke.py").exists(), "the CPU smoke exists (T926)"
    assert "ft-smoke" in Path(".github/workflows/nightly.yml").read_text()
    # the smoke passes on THIS machine (T929's finding, re-checked here):
    # the pre-flight the nightly runs is green, not aspirational
    import subprocess as _sp
    r = _sp.run([sys.executable, "scripts/ft_smoke.py", "--json"],
                check=False, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["ok"] is True
