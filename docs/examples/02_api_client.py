"""Call a running bouncer server over HTTP, stdlib only (T806).

    bouncer serve                       # terminal 1: pip install -e ".[server]"
    BOUNCER_KEY=... python docs/examples/02_api_client.py

Shows the wire contract: X-API-Key auth (omit the env var if the server
runs without a key), structured {"detail": {"code", "message"}} errors
with a plain-string fallback for legacy 40x details, and the exit-code
mapping scripts can rely on: 0 allow, 2 delete/flag, 3 escalate, 4 here
means "the API could not be used at all".
"""
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("BOUNCER_URL", "http://localhost:8000/predict")
EXIT = {"allow": 0, "flag": 2, "delete": 2, "escalate": 3}


def decide(message: str) -> dict:
    body = json.dumps({"message": message, "preset": "gaming"}).encode()
    headers = {"content-type": "application/json"}
    if os.environ.get("BOUNCER_KEY"):
        headers["x-api-key"] = os.environ["BOUNCER_KEY"]
    req = urllib.request.Request(URL, data=body, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main() -> int:
    try:
        res = decide("gg that clutch, wp team")
    except urllib.error.HTTPError as exc:
        # E_PRESET / E_RULES_* / E_CONTEXT details are {"code","message"}
        # dicts; some 40x details are plain strings — handle both
        payload = json.load(exc)
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        if isinstance(detail, dict):
            code, msg = detail.get("code", "?"), detail.get("message", "")
        else:
            code, msg = "?", str(detail)
        print(f"HTTP {exc.code} {code}: {msg}", file=sys.stderr)
        return 4
    except urllib.error.URLError as exc:
        print(f"bouncer: unreachable ({exc.reason}) — is bouncer serve up?",
              file=sys.stderr)
        return 4
    print(f"{res['action']}: {res['reason']}")
    return EXIT[res["action"]]


if __name__ == "__main__":
    sys.exit(main())
