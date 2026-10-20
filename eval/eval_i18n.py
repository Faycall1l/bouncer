"""T498: i18n wiring check (no weights). Validates fixtures, presets, lang-hint
plumbing, script detection, and auto model routing. Writes a JSON report.

T898: also MEASURES routing — for every fixture row, does the pipeline's own
decision (detect_lang -> model_for_lang -> model_for_script, the exact
moderate() chain) land on the checkpoint the row's language deserves? That
measurement is weightless and deterministic, so it always runs. Decision
QUALITY per language needs real weights; when laya isn't importable the
report says so with a skip receipt instead of pretending to have measured."""
import argparse
import json
import os
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "eval")
from validate_data import check_file

from gatekeeper import build_questions, get_preset
from gatekeeper.normalize import detect_script
from gatekeeper.pool import model_for_lang, model_for_script

LANG_OF = {"sin-spam": "es", "pas-de-spam": "fr", "bla-spam": "ar"}


def _route(msg, lang):
    """T898: the checkpoint moderate() would pick for this message+hint —
    lang hint first (T457), then the message's own script (T891)."""
    from gatekeeper.adapters.common import detect_lang
    return model_for_lang(lang) or model_for_script(detect_lang(msg))


def main(path="data/examples_i18n.jsonl", limit=0):
    errs = check_file(path, limit)
    with open(path) as f:
        rows = [json.loads(line) for line in f]
    if limit:
        rows = rows[:limit]
    per_lang: dict = {}
    routing = {"n": 0, "ok": 0, "wrong": []}  # T898: measured, not asserted
    for row in rows:
        rules = row["state"]["rules"]
        lang = next(LANG_OF[k] for k in rules if k in LANG_OF)
        preset_rules = get_preset({"es": "es", "fr": "fr", "ar": "ar"}[lang])
        assert set(preset_rules) <= set(rules) or set(rules) <= set(preset_rules)
        q = build_questions(rules, lang)  # T503: hint line present
        assert lang in q["rule"]["instructions"]
        script = detect_script(row["state"]["message"])
        if lang == "ar":
            assert script == "arabic"
        else:
            assert script == "latin"
        d = per_lang.setdefault(lang, {"n": 0, "multilingual": 0})
        d["n"] += 1
        d["multilingual"] += model_for_lang(lang) == "multilingual"
        # T898: routing measurement — ar rows must land multilingual,
        # latin-script rows (es/fr) must land auto-route (None)
        want = "multilingual" if lang == "ar" else None
        got = _route(row["state"]["message"], lang)
        routing["n"] += 1
        if got == want:
            routing["ok"] += 1
        else:
            routing["wrong"].append({"message": row["state"]["message"][:60],
                                     "lang": lang, "want": want, "got": got})
    # T898: quality needs weights — skip with a receipt, never fake a score
    try:
        import laya  # noqa: F401  — presence is the whole question
        quality = {"status": "weights present — run eval_gatekeeper.py "
                             "for per-language decision quality"}
    except ModuleNotFoundError:
        quality = {"status": "skipped",
                   "receipt": "laya (model weights) not importable here; "
                              "routing above is script-based and weightless, "
                              "so it was measured — decision quality was not"}
    return {"n": len(rows), "errors": errs, "per_lang": per_lang,
            "routing": routing, "quality": quality}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="eval_i18n")
    ap.add_argument("path", nargs="?", default="data/examples_i18n.jsonl")
    ap.add_argument("--limit", type=int, default=0)  # T509
    ap.add_argument("--out", default="eval/reports/i18n.json")  # T509
    ap.add_argument("--json", action="store_true")  # T509
    a = ap.parse_args()
    report = main(a.path, a.limit)
    os.makedirs("eval/reports", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=None if a.json else 2))
