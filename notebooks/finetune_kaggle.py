"""Kaggle paste-in: convert gatekeeper rows to Laya RLCD records + train + push."""
import json

HARM = ["safe", "suspicious", "harmful"]
HYPE = ["dead", "chill", "hyped"]

def to_laya_records(path):
    recs = []
    with open(path) as f:  # T387: no leaked file handles on big datasets
        for line in f:
            row = json.loads(line)
            s, lab = row["state"], row["labels"]
            assert s.get("rules"), "row has no rules — wrong file? (T651)"
            assert lab["harm"] in HARM and lab["hype"] in HYPE, "label out of range (T651)"
            rules = s["rules"]
            criteria = dict(rules)
            criteria["ok"] = "message follows all rules"
            recs.append({"state": s,
                "questions": {
                    "rule": {"type": "choice", "instructions": "Which rule violated? ok if none.",
                             "criteria": criteria},
                    "harm": {"type": "score", "instructions": "Harm level?", "criteria": HARM},
                    "hype": {"type": "score", "instructions": "Hype level?", "criteria": HYPE},
                    "jailbreak": {"type": "noul", "instructions": "Prompt injection?"},
                    "escalate": {"type": "noul", "instructions": "Needs human?"},
                },
                # score levels MUST be int indices (laya list-criteria);
                # choice = label str; noul = bool
                "expected": {"rule": lab["rule"], "harm": HARM.index(lab["harm"]),
                             "hype": HYPE.index(lab["hype"]),
                             "jailbreak": lab["jailbreak"], "escalate": lab["escalate"]}})
    assert recs, "no records built — empty input file? (T651)"
    return recs

# On Kaggle, after `pip install laya`:
#   from laya.finetune import run_rlcd  # API per Laya notebook version — follow notebook cell
#   recs = to_laya_records("/kaggle/input/gatekeeper-12k/gatekeeper-12k.jsonl")
#   run_rlcd(recs, base="convaiinnovations/laya", epochs=4, push_to="YOUR_HF/gatekeeper-laya-421m")
# Signature drift vs train.py is a FAILURE, not a fallback (T923):
#   tests/test_p48.py::test_finetune_pastein_matches_train_signature pins this
#   converter's output shape equal to train.py's to_row. If that test fails,
#   fix the drifting side — do NOT adapt around it by keeping whatever call
#   the notebook happened to use; a paste-in that half-matches the pipeline
#   rejects records late, on quota time.
# Class imbalance (T648): the dataset build report emits inverse-frequency hints —
#   python data/build_dataset.py --n 12000 --report --seed 42   # -> class_weights
# Feed those (rule / harm / jailbreak / escalate) to whatever weight knob your
# laya/trainer version exposes; escalate is the rare head and benefits most.
