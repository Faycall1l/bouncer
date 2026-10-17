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


def dry_run() -> bool:
    """T697: BOUNCER_DRY_RUN=1 — adapters print actions, never post."""
    return os.environ.get("BOUNCER_DRY_RUN") == "1"


# T700: every secret an adapter might echo into a log line or an out= print.
_ENV_TOKEN_VARS = ("DISCORD_TOKEN", "TWITCH_TOKEN", "TWITCH_NICK",
                   "TELEGRAM_TOKEN", "MATRIX_TOKEN", "MATRIX_HOMESERVER",
                   "MATTERMOST_TOKEN", "MATTERMOST_SERVER", "ZULIP_API_KEY",
                   "ZULIP_EMAIL", "ZULIP_SITE", "BOUNCER_FORWARD_URL")


def redact(s: str) -> str:
    """T700: one redaction pass for every adapter log line.

    Masks exact env token/site values (worst case: an exception embeds one),
    `Bearer`/`oauth:`/`Basic` credentials, emails, and URL query-string
    secrets — in that order, so a token containing an email-like substring
    is still masked as the token.
    """
    import re
    s = str(s)
    for var in _ENV_TOKEN_VARS:
        v = os.environ.get(var)
        if v:
            s = s.replace(v, f"***{var}***")
    s = re.sub(r"(?i)\b(bearer|basic)\s+\S+", r"\1 ***", s)
    s = re.sub(r"(?i)\boauth:\S+", "oauth:***", s)
    s = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "***@***", s)  # emails
    s = re.sub(r"(?i)([?&](?:token|key|api_key|access_token|secret)=)[^&\s]+",
               r"\1***", s)  # URL query secrets
    return s


def load_rules(adapter: str, default: str = "gaming") -> dict:
    """T698: where an adapter's rules come from, per adapter.

    `BOUNCER_RULES_<ADAPTER>` (e.g. BOUNCER_RULES_MATRIX) overrides the shared
    `BOUNCER_RULES`; either names a preset or points at a JSON file of rules.
    """
    spec = os.environ.get(f"BOUNCER_RULES_{adapter.upper()}",
                          os.environ.get("BOUNCER_RULES", default))
    if os.path.isfile(spec):
        import json
        try:
            with open(spec) as f:
                rules = json.load(f)
        except (OSError, ValueError) as e:
            raise AdapterError(
                f"E_ADAPTER: rules file {spec} is unreadable JSON: {e}") from e
        if not isinstance(rules, dict) or not rules:
            raise AdapterError(
                f"E_ADAPTER: rules file {spec} must be a non-empty JSON object")
        return rules
    from gatekeeper import get_preset, presets
    try:
        return get_preset(spec)
    except KeyError as e:
        raise AdapterError(
            f"E_ADAPTER: unknown rules {spec!r} — a preset "
            f"{sorted(presets.PRESETS)} or a JSON file path") from e


def run_loop(fetch, handle, *, name: str, backoff_s: float = 5.0,
             sleep=time.sleep, health=None):
    """T696: one poll loop for every sync adapter (telegram/matrix/zulip).

    `fetch()` returns the next page of events (or None); `handle()` consumes
    one event. Fetch failures log, back off, and keep the loop alive; a bad
    event costs one log line, never the process. KeyboardInterrupt always
    passes through — Ctrl-C must stop a bot. The Mattermost websocket adapter
    is async and keeps its own loop; its per-event guard matches this one.
    T699: `health` (if given) counts real decisions, records errors, and
    emits its health line when due.
    """
    while True:
        try:
            page = fetch()
        except Exception as e:  # noqa: BLE001 — network blips must not kill the bot
            print(f"{name} error: {redact(e)}", file=sys.stderr, flush=True)
            if health is not None:
                health.error(redact(e))  # T700: no secrets in the health line
            sleep(backoff_s)
            continue
        for ev in page or []:
            try:
                res = handle(ev) or {}
                if health is not None and res.get("action") not in (
                        "ignored", "command"):
                    health.decision()  # T699: ignored traffic isn't a decision
            except Exception as e:  # noqa: BLE001
                print(f"{name} event error: {redact(e)}",
                      file=sys.stderr, flush=True)
                if health is not None:
                    health.error(e)
        if health is not None:
            health.maybe_log()


class Health:
    """T699: per-adapter health line — decisions/min + last error, on a timer.

    Clock and log are injectable so tests never wait a real minute.
    """

    def __init__(self, name: str, *, clock=time.monotonic, log=print,
                 window_s: float = 60.0, every_s: float = 300.0):
        self.name = name
        self.clock = clock
        self.log = log
        self.window_s = window_s
        self.every_s = every_s
        self._stamps = []
        self._last_error = None  # (clock ts, message)
        self._last_line = clock()

    def decision(self):
        self._stamps.append(self.clock())

    def error(self, msg):
        self._last_error = (self.clock(), str(msg))

    def line(self) -> str:
        cutoff = self.clock() - self.window_s
        self._stamps = [t for t in self._stamps if t > cutoff]
        if self._last_error is None:
            err = "none"
        else:
            ago = (self.clock() - self._last_error[0]) / 60.0
            err = f"{ago:.0f}m ago — {self._last_error[1]}"
        return (f"{self.name} health: {len(self._stamps)} decisions/min, "
                f"last error: {err}")

    def maybe_log(self):
        now = self.clock()
        if now - self._last_line >= self.every_s:
            self.log(self.line())
            self._last_line = now
