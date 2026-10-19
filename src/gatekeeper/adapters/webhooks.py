"""Slack/events + generic webhook forwarder (T078-T079).
POST {"message": ..., "rules"?} -> decision; optional forward of delete/flag events.
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import json
import os
import urllib.error
import urllib.request


class WebhookError(Exception):  # T295
    code = "E_WEBHOOK"


class SlackError(Exception):  # T301
    code = "E_SLACK"


_SCHEMES = ("http://", "https://")  # T785: file://, gopher://, data: are the SSRF classics


def _check_url(url: str) -> None:
    """T785: SSRF guard for the forwarder. The URL is operator config, not
    end-user input — this keeps a copied template or a compromised config
    from turning the forwarder into an internal scanner: only http(s)
    leaves the box, and if BOUNCER_FORWARD_ALLOW is set, only those exact
    hosts (case-insensitive, no subdomain wildcards)."""
    if not url.lower().startswith(_SCHEMES):
        raise WebhookError(f"E_WEBHOOK: refusing non-http(s) scheme in {url!r}")
    allow = [h.strip() for h in
             os.environ.get("BOUNCER_FORWARD_ALLOW", "").split(",") if h.strip()]
    if allow:
        from urllib.parse import urlsplit
        host = urlsplit(url).hostname or ""
        if host not in allow:
            raise WebhookError(f"E_WEBHOOK: host {host!r} not in BOUNCER_FORWARD_ALLOW")


def verify_slack_signature(secret, ts, body, signature, *, now=None,
                           tolerance_s: float = 300.0) -> bool:  # T704
    """Slack's v0 scheme: HMAC-SHA256 over `v0:{ts}:{body}`, compared
    constant-time, inside a replay window. Missing pieces are a mismatch,
    never an exception. `body` must be the raw bytes/str Slack signed —
    a re-serialized dict would silently mismatch on key order/whitespace."""
    import time as _time
    if now is None:
        now = _time.time()
    try:
        if abs(now - float(ts)) > tolerance_s:
            return False  # replay window: stale or clock-skewed beyond reason
    except (TypeError, ValueError):
        return False
    from gatekeeper.adapters.common import verify_signature
    return verify_signature(secret, signature, f"v0:{ts}:{body}", prefix="v0=")


def receive_slack_event(body, rules, *, secret=None, raw=None, ts=None,  # T704
                        signature=None) -> dict:  # T078
    """Pass `secret` (+ the raw body, timestamp and X-Slack-Signature header)
    to enforce T704 verification — fail-closed: a missing piece raises
    E_SLACK instead of letting an unsigned event through."""
    if secret is not None and (
        raw is None or not verify_slack_signature(secret, ts, raw, signature)
    ):
        raise SlackError("E_SLACK: bad signature (T704)")
    from gatekeeper import moderate
    from gatekeeper.adapters.common import as_user_id
    if not isinstance(body, dict):  # T301
        raise SlackError(f"E_SLACK: event body is {type(body).__name__}, expected dict")
    text = body.get("text", "")
    if not isinstance(text, str):
        raise SlackError("E_SLACK: event text must be a string")
    if body.get("subtype") == "bot_message" or body.get("bot_id"):  # T302: no bot loops
        return {"action": "allow", "rule": "ok", "confidence": 1.0, "ignored": True,
                "reason": "slack: bot message ignored"}
    return moderate(text, rules,  # T856: strikes accrue per platform user
                    user_id=as_user_id(body.get("user")))


def forward(url: str, event: dict) -> None:  # T079
    from gatekeeper import __version__
    from gatekeeper.adapters.common import dry_run

    _check_url(url)  # T785: scheme + opt-in allowlist before any socket opens
    if dry_run():  # T697: never post — not even the forwarder
        from gatekeeper.adapters.common import redact
        print(f"[dry-run] would forward {event.get('action')} to {redact(url)}")
        return
    req = urllib.request.Request(url, data=json.dumps(event).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": f"bouncer/{__version__}",  # T293
                                          "X-Bouncer-Event": event.get("action", "?")})
    try:  # T295: network failure becomes a coded error, not a bare URLError
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.URLError as e:
        raise WebhookError(f"E_WEBHOOK: POST {url} failed ({e})") from e


def forward_if_interesting(res: dict, message: str) -> bool:
    """T294+T707: delete/flag/escalate go to BOUNCER_FORWARD_URL with the
    reason; True if sent. Breaker-open results fire too (explicitly keyed on
    `cause`, not just today's escalate action shape) and carry `cause` in the
    payload — a receiver must be able to tell "the model said escalate" from
    "the model is down, escalating by default"."""
    url = os.environ.get("BOUNCER_FORWARD_URL", "")
    interesting = (res["action"] in ("delete", "flag", "escalate")
                   or res.get("cause") == "breaker-open")  # T707
    if url and interesting:
        forward(url, {"action": res["action"], "rule": res.get("rule", "ok"),
                      "confidence": res.get("confidence", 0.0),
                      "reason": res.get("reason", ""),
                      "cause": res.get("cause", ""),  # T707: breaker-open shows here
                      "message": message[:500]})
        return True
    return False
