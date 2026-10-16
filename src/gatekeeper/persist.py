"""Atomic JSON persistence for stats/strikes/cache snapshots. No deps."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import json
import os


class SnapshotError(Exception):
    """T431: corrupt or incompatible snapshot file. Machine-readable code."""

    code = "E_SNAPSHOT"


def atomic_write(path: str, text: str) -> None:
    """T431: write via tmp + rename so crashes never leave half a snapshot."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def read_json(path: str) -> dict:
    """T431+T446: load a snapshot; corrupt files raise SnapshotError."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SnapshotError(f"E_SNAPSHOT: cannot read {path} ({e})") from e
    if not isinstance(data, dict):
        raise SnapshotError(f"E_SNAPSHOT: {path} holds {type(data).__name__}, want object")
    return data
