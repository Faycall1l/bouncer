"""Shared adapter plumbing (T691): the adapter error type and env-token guard.

T696 grows this into the full shared SDK (one `run_loop()` for all pollers).
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import os


class AdapterError(Exception):
    """Startup/config errors an operator can fix (T691)."""
    code = "E_ADAPTER"


def require_env(name: str) -> str:
    """T691: adapter tokens come from env; a missing one is a startup error
    naming the variable — not a raw KeyError from deep inside the run loop."""
    v = os.environ.get(name)
    if not v:  # unset and exported-but-blank are both misconfigurations
        raise AdapterError(f"E_ADAPTER: {name} is not set — export it before "
                           f"starting the adapter")
    return v
