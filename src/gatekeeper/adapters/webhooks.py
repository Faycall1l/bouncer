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
    req = urllib.request.Request(url, data=json.dumps(event).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def forward_if_interesting(res: dict, message: str) -> None:
    url = os.environ.get("BOUNCER_FORWARD_URL", "")
    if url and res["action"] in ("delete", "flag"):
        forward(url, {"action": res["action"], "rule": res["rule"],
                      "confidence": res["confidence"], "message": message[:500]})
