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
