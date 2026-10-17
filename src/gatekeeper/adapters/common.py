"""Shared adapter plumbing (T691/T696): the adapter error type, env-token
guard, and the one poll loop every sync adapter runs."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import os
import sys
import time


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


def run_loop(fetch, handle, *, name: str, backoff_s: float = 5.0,
             sleep=time.sleep):
    """T696: one poll loop for every sync adapter (telegram/matrix/zulip).

    `fetch()` returns the next page of events (or None); `handle()` consumes
    one event. Fetch failures log, back off, and keep the loop alive; a bad
    event costs one log line, never the process. KeyboardInterrupt always
    passes through — Ctrl-C must stop a bot. The Mattermost websocket adapter
    is async and keeps its own loop; its per-event guard matches this one.
    """
    while True:
        try:
            page = fetch()
        except Exception as e:  # noqa: BLE001 — network blips must not kill the bot
            print(f"{name} error:", e, file=sys.stderr, flush=True)
            sleep(backoff_s)
            continue
        for ev in page or []:
            try:
                handle(ev)
            except Exception as e:  # noqa: BLE001
                print(f"{name} event error:", e, file=sys.stderr, flush=True)
