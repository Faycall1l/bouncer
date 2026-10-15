"""P16 tests (T271-T290): performance. No weights."""
import sys

sys.path.insert(0, "src")


def test_forced_ok_skips_dists():  # T276
    from gatekeeper.explain import explain
    res = {"action": "delete", "rule": "ok", "confidence": 0.95, "forced": "jailbreak 0.95",
           "rule_dist": None}
    s = explain(res, {})
    assert s.startswith("delete: override") and "runner-up" not in s
