"""Cheap pre-model signals: normalization + flood/link detectors (no weights needed)."""
from __future__ import annotations

import re
import unicodedata

URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+\.(?:gg|com|net|io|xyz)\b\S*", re.IGNORECASE)


def clean_text(msg: str, max_chars: int = 2000) -> str:
    """T013: unicode-fold, collapse whitespace, truncate with marker."""
    t = unicodedata.normalize("NFKC", msg or "")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_chars:
        t = t[:max_chars] + " …[truncated]"
    return t
