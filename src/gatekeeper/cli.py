"""`bouncer` CLI: check/serve/demo/watch/stats/review/pack. Exit codes: 0 allow, 2 delete/flag, 3 escalate."""
from __future__ import annotations

import argparse
import json
import sys


def _load_rules(args) -> dict:
    from gatekeeper import get_preset
    if args.preset:
        return get_preset(args.preset)
    with open(args.rules) as f:
        return json.load(f)


def cmd_check(args) -> int:  # T066+T067+T071+T072
    from gatekeeper import moderate, GateConfig
    from gatekeeper.explain import explain
    rules = _load_rules(args)
    cfg = GateConfig(allow_threshold=args.threshold, delete_threshold=args.threshold)
    res = moderate(args.message, rules, config=cfg)
    res["reason"] = explain(res, rules)
    print(json.dumps(res, default=str, indent=2) if args.json else f"{res['action']}: {res['reason']}")
    return {"allow": 0, "delete": 2, "flag": 2, "escalate": 3}[res["action"]]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="bouncer")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("message")
    c.add_argument("--rules", default="rules.json")
    c.add_argument("--preset")
    c.add_argument("--threshold", type=float, default=0.85)
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_check)
    s = sub.add_parser("serve")  # T068
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=lambda a: (__import__("uvicorn").run("gatekeeper.serve:app",
                                                           host=a.host, port=a.port), 0)[1])
    d = sub.add_parser("demo")  # T069
    d.set_defaults(fn=lambda a: (_demo(), 0))
    args = p.parse_args(argv)
    return args.fn(args)


def _demo():
    from gatekeeper.demo_app import launch
    launch()


if __name__ == "__main__":
    sys.exit(main())
