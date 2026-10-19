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


def require_env(name: str, cfg_value=None) -> str:
    """T691: adapter tokens come from env; a missing one is a startup error
    naming the variable — not a raw KeyError from deep inside the run loop.
    T709: a value from bouncer.toml fills in when the env var is missing or
    blank; a non-empty env var always wins."""
    v = os.environ.get(name)
    if not v:  # unset and exported-but-blank are both misconfigurations
        if isinstance(cfg_value, str) and cfg_value.strip():
            return cfg_value.strip()
        raise AdapterError(f"E_ADAPTER: {name} is not set — export it or set "
                           f"it in bouncer.toml before starting the adapter")
    return v


def load_config(path: str | None = None) -> dict:
    """T709: optional per-adapter config from bouncer.toml (stdlib tomllib).

    A missing file is {} — config is additive, never required. Broken TOML
    is E_ADAPTER naming the file, never a raw traceback. BOUNCER_CONFIG
    overrides the default path. Env vars always beat file values: the file
    supplies defaults, the environment is the deployment.
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11: the tomli backport (T814)
        import tomli as tomllib
    p = path or os.environ.get("BOUNCER_CONFIG", "").strip() or "bouncer.toml"
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise AdapterError(f"E_ADAPTER: config {p} is unreadable: {e}") from e
    if not isinstance(data, dict):
        raise AdapterError(f"E_ADAPTER: config {p} must be a TOML table")
    return data


def cfg_get(cfg, *keys, default=None):
    """T709: dotted lookup into a loaded config; anything missing = default."""
    cur = cfg
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def opt_in(env_name: str, cfg, adapter: str, name: str) -> bool:
    """T709: BOUNCER_*_DELETE/REDACT env beats bouncer.toml [adapter.x] flags.
    An env var that is set decides, whatever its value; unset falls to the
    file's boolean."""
    v = os.environ.get(env_name)
    if v is not None:
        return v == "1"
    return bool(cfg_get(cfg, "adapter", adapter, name))


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


def verify_signature(secret: str, header: str, body, *, prefix: str = "",
                     digestmod: str = "sha256") -> bool:
    """T704: constant-time HMAC signature check for webhook receivers.

    Malformed input (None/empty secret, header, body) is a mismatch, never
    an exception — a verifier that crashes on `None` hands out 500-response
    oracles. `prefix` covers schemes like GitHub's `sha256=`. Comparison is
    `hmac.compare_digest` throughout; no `==` on secrets, ever.
    """
    import hashlib
    import hmac
    if not secret or not header or body is None:
        return False
    if not isinstance(header, str) or not isinstance(secret, str):
        return False
    raw = body if isinstance(body, bytes) else str(body).encode()
    expected = prefix + hmac.new(secret.encode(), raw,
                                 getattr(hashlib, digestmod)).hexdigest()
    return hmac.compare_digest(header, expected)


def load_rules(adapter: str, default: str = "gaming", cfg=None) -> dict:
    """T698+T709: where an adapter's rules come from, per adapter.

    `BOUNCER_RULES_<ADAPTER>` (e.g. BOUNCER_RULES_MATRIX) overrides the shared
    `BOUNCER_RULES`; either names a preset or points at a JSON file of rules.
    With no env, bouncer.toml `[adapter.<name>] rules` is consulted (T709).
    """
    spec = os.environ.get(f"BOUNCER_RULES_{adapter.upper()}") \
        or os.environ.get("BOUNCER_RULES") \
        or (cfg_get(cfg, "adapter", adapter, "rules") or "") \
        or default  # T709: env beats file, file beats default
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


def install_shutdown(name: str, log=print, hard: bool = False):
    """T702: SIGTERM -> clean stop; returns `stopping()` for the loops.

    Default (soft): the flag flips, loops finish their current page and exit
    at the next page boundary. A second SIGTERM force-exits (128+sig), like
    uvicorn. `hard=True` exits immediately instead — right for adapters whose
    runner (discord.py) owns its own loop and cleanup.
    """
    import signal
    state = {"stop": False}

    def _handler(signum, frame):  # frame unused — signal API shape
        if hard or state["stop"]:
            raise SystemExit(128 + signum)
        state["stop"] = True
        log(f"{name}: SIGTERM — finishing current page, then exiting")

    def stopping() -> bool:
        return state["stop"]

    try:
        signal.signal(signal.SIGTERM, _handler)
    except ValueError:  # not on the main thread (tests, embedding)
        pass
    return stopping


def http_json(req, *, timeout: float = 30.0, opener=None, attempts: int = 3,
              backoff_s: float = 0.5, backoff_cap_s: float = 8.0,
              retry_after_cap_s: float = 60.0,
              sleep=time.sleep, rand=None):  # T851
    """The one place adapters speak HTTP with retries (replaces four
    single-shot copies: telegram/mattermost/matrix/zulip `api()`).

    429 and 5xx are transient *because the server said so*: retried up to
    `attempts`, honoring a numeric `Retry-After` (capped — a broken server
    demanding an 8-hour wait gets `retry_after_cap_s`, not our process).
    Without the header it's capped exponential backoff with jitter in
    [half, full] of each span, so retries from different bots don't
    synchronize. Every other failure — 4xx that isn't 429, DNS, TLS,
    timeouts — raises immediately: a 401 or 404 doesn't improve by
    trying again, and run_loop already backs off network errors (T696).
    Returns parsed JSON, like the copies it replaced.
    """
    import json
    import random
    import urllib.error
    import urllib.request

    open_ = opener or urllib.request.urlopen
    rnd = rand if rand is not None else random.random
    wait = 0.0
    for attempt in range(attempts):
        if wait:
            sleep(wait)
            wait = 0.0
        try:
            with open_(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            ra = None
            try:  # seconds form; HTTP-date falls back to backoff (rare)
                ra = max(0.0, float((e.headers.get("Retry-After")
                                     if e.headers else "") or ""))
            except (TypeError, ValueError):
                ra = None
            e.close()  # the error body is of no use; free the socket
            if e.code != 429 and not 500 <= e.code < 600:
                raise  # permanent — retrying a 401/404 just wastes calls
            if attempt == attempts - 1:
                raise  # budget spent — surface the real status to the caller
            if ra is not None:
                wait = min(ra, retry_after_cap_s)
            else:
                span = min(backoff_s * (2 ** attempt), backoff_cap_s)
                wait = span * (0.5 + 0.5 * rnd())  # jitter: never 0, never early


def run_loop(fetch, handle, *, name: str, backoff_s: float = 5.0,
             sleep=time.sleep, health=None, stopping=None):
    """T696: one poll loop for every sync adapter (telegram/matrix/zulip).

    `fetch()` returns the next page of events (or None); `handle()` consumes
    one event. Fetch failures log, back off, and keep the loop alive; a bad
    event costs one log line, never the process. KeyboardInterrupt always
    passes through — Ctrl-C must stop a bot. The Mattermost websocket adapter
    is async and keeps its own loop; its per-event guard matches this one.
    T699: `health` (if given) counts real decisions, records errors, and
    emits its health line when due. T702: `stopping` (if given) is polled at
    page boundaries — SIGTERM (via install_shutdown) finishes the current
    page, then exits cleanly.
    """
    while True:
        if stopping is not None and stopping():  # T702: page boundary exit
            print(f"{name}: shutdown requested — exiting cleanly",
                  file=sys.stderr, flush=True)
            return
        try:
            page = fetch()
        except Exception as e:  # noqa: BLE001 — network blips must not kill the bot
            print(f"{name} error: {redact(e)}", file=sys.stderr, flush=True)
            if health is not None:
                health.error(redact(e))  # T700: no secrets in the health line
            if stopping is not None and stopping():
                print(f"{name}: shutdown requested — exiting cleanly",
                      file=sys.stderr, flush=True)
                return  # T702: the long-poll died because we're shutting down
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


class RateCap:
    """T701: per-user sliding-window cap — one flood can't monopolize the
    model. `allow(key)` True = this call may reach the model."""

    def __init__(self, max_calls: int = 10, window_s: float = 60.0,
                 clock=time.monotonic):
        self.max_calls = max_calls
        self.window_s = window_s
        self.clock = clock
        self._hits = {}
        self._last_sweep = clock()

    def _sweep(self, now):
        cutoff = now - self.window_s
        for key in [k for k, ts in self._hits.items()
                    if not ts or ts[-1] <= cutoff]:
            del self._hits[key]  # idle users cost nothing

    def allow(self, key) -> bool:
        now = self.clock()
        if now - self._last_sweep > self.window_s:
            self._sweep(now)
            self._last_sweep = now
        hits = [t for t in self._hits.get(key, []) if t > now - self.window_s]
        if len(hits) >= self.max_calls:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


def rate_cap_from_env(cfg=None) -> RateCap | None:
    """T701: BOUNCER_RATE_CAP = max model calls per user per minute;
    0 disables the cap. A typo'd value must not crash a running bot.
    T709: with no env, bouncer.toml `[tuning] rate_cap` is consulted."""
    raw = os.environ.get("BOUNCER_RATE_CAP")
    if raw is None or not raw.strip():
        raw = cfg_get(cfg, "tuning", "rate_cap")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 10
    return RateCap(max_calls=n) if n > 0 else None
