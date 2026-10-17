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


def receive_slack_event(body: dict, rules: dict) -> dict:  # T078
    from gatekeeper import moderate
    if not isinstance(body, dict):  # T301
        raise SlackError(f"E_SLACK: event body is {type(body).__name__}, expected dict")
    text = body.get("text", "")
    if not isinstance(text, str):
        raise SlackError("E_SLACK: event text must be a string")
    if body.get("subtype") == "bot_message" or body.get("bot_id"):  # T302: no bot loops
        return {"action": "allow", "rule": "ok", "confidence": 1.0, "ignored": True,
                "reason": "slack: bot message ignored"}
    return moderate(text, rules)


def forward(url: str, event: dict) -> None:  # T079
    from gatekeeper import __version__
    from gatekeeper.adapters.common import dry_run
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
    """T294: delete/flag/escalate go to BOUNCER_FORWARD_URL with the reason; True if sent."""
    url = os.environ.get("BOUNCER_FORWARD_URL", "")
    if url and res["action"] in ("delete", "flag", "escalate"):
        forward(url, {"action": res["action"], "rule": res["rule"],
                      "confidence": res["confidence"], "reason": res.get("reason", ""),
                      "message": message[:500]})
        return True
    return False
