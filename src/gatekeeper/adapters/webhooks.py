"""Slack/events + generic webhook forwarder (T078-T079).
POST {"message": ..., "rules"?} -> decision; optional forward of delete/flag events.
"""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import json
import os
import urllib.request


def receive_slack_event(body: dict, rules: dict) -> dict:  # T078
    from gatekeeper import moderate
    text = body.get("text", "")
    return moderate(text, rules)


def forward(url: str, event: dict) -> None:  # T079
    from gatekeeper import __version__
    req = urllib.request.Request(url, data=json.dumps(event).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": f"bouncer/{__version__}",  # T293
                                          "X-Bouncer-Event": event.get("action", "?")})
    urllib.request.urlopen(req, timeout=10).read()


def forward_if_interesting(res: dict, message: str) -> bool:
    """T294: delete/flag/escalate go to BOUNCER_FORWARD_URL with the reason; True if sent."""
    url = os.environ.get("BOUNCER_FORWARD_URL", "")
    if url and res["action"] in ("delete", "flag", "escalate"):
        forward(url, {"action": res["action"], "rule": res["rule"],
                      "confidence": res["confidence"], "reason": res.get("reason", ""),
                      "message": message[:500]})
        return True
    return False
