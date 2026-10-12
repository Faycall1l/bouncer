from gatekeeper import build_questions

def test_build_questions_dynamic_k():
    q = build_questions({"a": "rule a", "b": "rule b"})
    assert set(q["rule"]["criteria"]) == {"a", "b", "ok"}
    assert q["harm"]["type"] == "score"
    assert q["jailbreak"]["type"] == "noul"

def test_build_questions_rejects_empty():
    from gatekeeper.rules import RuleError, validate_rules
    try:
        validate_rules({})
    except RuleError:
        return
    raise AssertionError("expected RuleError")
