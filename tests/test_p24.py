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
