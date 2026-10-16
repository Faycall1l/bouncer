"""P24 tests (T431-T450): persistence. No weights."""
import sys

sys.path.insert(0, "src")


def test_snapshot_save_load(tmp_path):  # T437+T438
    from gatekeeper import strikes as _strikes
    from gatekeeper.cli import main
    from gatekeeper.stats import get_stats, record, reset_stats
    reset_stats()
    _strikes.reset()
    record("delete", "no-spam", 5.0, cause="violation")
    _strikes.add_strike("u9", 2)
    f = str(tmp_path / "snap.json")
    assert main(["snapshot", "save", f]) == 0
    reset_stats()
    _strikes.reset()
    assert main(["snapshot", "load", f]) == 0
    assert get_stats()["actions"]["delete"] == 1
    assert _strikes.standing("u9")["strikes"] == 2
    reset_stats()
    _strikes.reset()


def test_corrupt_snapshot(tmp_path):  # T446
    import pytest

    from gatekeeper.persist import SnapshotError, read_json
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(SnapshotError, match="E_SNAPSHOT"):
        read_json(str(bad))
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2]")
    with pytest.raises(SnapshotError, match="want object"):
        read_json(str(arr))


def test_strikes_save_load(tmp_path):  # T432+T433
    from gatekeeper import strikes as _st
    _st.reset()
    _st.add_strike("a", 2)
    p = str(tmp_path / "st.json")
    _st.save(p)
    _st.reset()
    assert _st.load(p) == 1 and _st.standing("a")["strikes"] == 2
    _st.add_strike("a", 5)
    _st.load(p)  # max-wins: file has 2, memory has 7
    assert _st.standing("a")["strikes"] == 7
    _st.reset()


def test_stats_save_load(tmp_path):  # T435
    from gatekeeper.stats import get_stats, load, record, reset_stats, save
    reset_stats()
    record("flag", "r", 4.0, cause="suspected")
    p = str(tmp_path / "stats.json")
    save(p)
    reset_stats()
    load(p)
    s = get_stats()
    assert s["actions"]["flag"] == 1 and s["causes"] == {"suspected": 1}
    reset_stats()


def test_cache_save_load(tmp_path):  # T436
    from gatekeeper.cache import TTLCache
    c, d = TTLCache(), TTLCache()
    c.set("k", {"a": 1})
    p = str(tmp_path / "cache.json")
    c.save(p)
    assert d.load(p) == 1 and d.get("k") == {"a": 1}
    e = TTLCache(ttl=0.01)
    import time as _t
    e.set("old", {"a": 1})
    _t.sleep(0.02)
    e.save(p)
    assert TTLCache().load(p) == 0  # expired pruned


def test_audit_tail_and_review_prune(tmp_path, monkeypatch):  # T440+T441+T442
    import importlib

    import gatekeeper.audit as _au
    import gatekeeper.review as _rv
    pa = tmp_path / "a.jsonl"
    pr = tmp_path / "r.jsonl"
    monkeypatch.setenv("BOUNCER_AUDIT", str(pa))
    monkeypatch.setenv("BOUNCER_REVIEW", str(pr))
    importlib.reload(_au)
    importlib.reload(_rv)
    for i in range(5):
        _au.log_decision(f"m{i}", "ok", 0.9, "allow", 1.0)
    assert len(_au.tail(2)) == 2
    _rv.add("old", {"action": "flag", "rule": "r", "confidence": 0.5})
    assert _rv.list_queue()[0]["t"] > 0 and "cause" in _rv.list_queue()[0]
    assert _rv.prune(3600) == 0
    assert _rv.prune(-1) == 1 and _rv.list_queue() == []  # everything older than future


def test_export_stats_and_limit(tmp_path, monkeypatch):  # T445+T449
    import importlib
    import json as _json

    import gatekeeper.audit as _au
    from gatekeeper.cli import main
    pa = tmp_path / "a2.jsonl"
    monkeypatch.setenv("BOUNCER_AUDIT", str(pa))
    importlib.reload(_au)
    for i in range(4):
        _au.log_decision(f"x{i}", "ok", 0.9, "allow", 2.0)
    out = tmp_path / "lim.csv"
    assert main(["export", "--out", str(out), "--limit", "2"]) == 0
    assert len(out.read_text().splitlines()) == 3  # header + 2
    st = tmp_path / "st.json"
    assert main(["export", "--stats", str(st)]) == 0
    assert "stats" in _json.loads(st.read_text())


def test_restore_rejects_unknown(tmp_path):  # T447
    import pytest

    from gatekeeper.persist import SnapshotError
    from gatekeeper.stats import reset_stats, restore, snapshot
    reset_stats()
    snap = snapshot()
    snap["counts"] = {"allow": 1, "ban": 2}
    with pytest.raises(SnapshotError, match="unknown actions"):
        restore(snap)
    reset_stats()
