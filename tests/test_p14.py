"""P14 tests (T231-T250): observability + stats. No weights."""
import sys

sys.path.insert(0, "src")

from gatekeeper.stats import get_stats, record, reset_stats


def test_reset_clears_all():  # T239
    reset_stats()
    record("delete", "no-spam", 12.5, cause="violation")
    record("allow", "ok", 0.0, cheap=True, cause="fastpath")
    s = get_stats()
    assert s["actions_by_rule"] == {"no-spam": {"delete": 1}, "ok": {"allow": 1}}
    assert s["latency"]["n"] == 2 and s["cheap_paths"] == 1
    assert s["causes"] == {"violation": 1, "fastpath": 1}
    reset_stats()
    s = get_stats()
    assert s["total"] == 0 and s["latency"]["n"] == 0
    assert s["cheap_paths"] == 0 and s["causes"] == {} and s["actions_by_rule"] == {}
    reset_stats()  # leave clean state for later tests
