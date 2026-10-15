"""Cheap pre-model signals: normalization + flood/link detectors (no weights needed)."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import re
import unicodedata

URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+\.(?:gg|com|net|io|xyz)\b\S*", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")  # T275: compiled once, not per message


def clean_text(msg: str, max_chars: int = 2000) -> str:
    """T013: unicode-fold, collapse whitespace, truncate with marker."""
    t = unicodedata.normalize("NFKC", msg or "") if isinstance(msg, str) else ""  # T263
    t = _WS_RE.sub(" ", t).strip()
    if len(t) > max_chars:
        t = t[:max_chars] + " …[truncated]"
    return t


def caps_flood(msg: str, ratio: float = 0.7, min_len: int = 12) -> bool:
    """T014: True when mostly-caps shouting on a long-enough message."""
    if not isinstance(msg, str):  # T265
        return False
    letters = [c for c in msg if c.isalpha()]
    if len(letters) < min_len:
        return False
    return sum(c.isupper() for c in letters) / len(letters) >= ratio


def emoji_flood(msg: str, max_run: int = 5, max_total: int = 10) -> bool:
    """T015: True on emoji walls (long run or high total of non-text symbols)."""
    if not isinstance(msg, str):  # T265
        return False
    syms = [c for c in msg if not (c.isalnum() or c.isspace() or c in ".,!?;:'\"-()")]
    if len(syms) >= max_total:
        return True
    run = best = 0
    for c in msg:
        run = run + 1 if not (c.isalnum() or c.isspace()) else 0
        best = max(best, run)
    return best >= max_run


def extract_links(msg: str) -> list:
    """T016: urls for rules/no-spam to cite and for the audit trail."""
    if not isinstance(msg, str):  # T264
        return []
    return URL_RE.findall(msg)
