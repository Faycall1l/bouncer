"""`bouncer` CLI: check/serve/demo/watch/stats/review/pack. Exit codes: 0 allow, 2 delete/flag, 3 escalate."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
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
    from gatekeeper import GateConfig, moderate
    from gatekeeper.explain import explain
    rules = _load_rules(args)
    cfg = GateConfig(allow_threshold=args.threshold, delete_threshold=args.threshold)
    res = moderate(args.message, rules, config=cfg)
    res["reason"] = explain(res, rules)
    print(json.dumps(res, default=str, indent=2) if args.json else f"{res['action']}: {res['reason']}")
    return {"allow": 0, "delete": 2, "flag": 2, "escalate": 3}[res["action"]]


COLORS = {"allow": "\033[32m", "flag": "\033[33m", "delete": "\033[31m", "escalate": "\033[37m"}
RESET = "\033[0m"


def cmd_watch(args) -> int:
    from gatekeeper import GateConfig, moderate
    rules = _load_rules(args)
    cfg = GateConfig(allow_threshold=args.threshold, delete_threshold=args.threshold)
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        try:
            res = moderate(line, rules, config=cfg)
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
            continue
        c = COLORS.get(res["action"], "")
        print(f"{c}{res['action']:8}\033[0m {res['rule']}@{res['confidence']:.2f} {line[:120]}",
              flush=True)
    return 0


def cmd_review(args) -> int:
    from gatekeeper.review import list_queue
    for row in list_queue(args.limit):
        print(f"{row['action']:8} {row['rule']}@{row['conf']:.2f} {row['message'][:100]}")
    return 0


def cmd_stats(args) -> int:
    from gatekeeper.cache import CACHE
    from gatekeeper.stats import get_stats
    print(json.dumps({"decisions": get_stats(), "cache": CACHE.stats()}, indent=2))
    return 0


def cmd_export(args) -> int:
    import csv

    from gatekeeper.audit import _PATH
    n = 0
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "msg", "rule", "conf", "action", "ms"])
        if __import__("os").path.exists(_PATH):
            with open(_PATH) as af:
                for line in af:
                    d = json.loads(line)
                    w.writerow([d["t"], d["msg"], d["rule"], d["conf"], d["action"], d["ms"]])
                    n += 1
    print(f"exported {n} rows -> {args.out}")
    return 0


def cmd_pack(args) -> int:
    from gatekeeper import get_preset
    from gatekeeper.rules import validate_rules, warn_overlapping
    if args.rules:
        with open(args.rules) as f:
            rules = json.load(f)
    else:
        rules = get_preset(args.preset)
    if args.action == "show":
        print(json.dumps(rules, indent=2, ensure_ascii=False))
    else:
        validate_rules(rules)
        for w in warn_overlapping(rules):
            print("warn:", w)
        print(f"pack ok: {len(rules)} rules")
    return 0


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
    w = sub.add_parser("watch")  # T070+T169: stdin pipe, colored live tail
    w.add_argument("--rules", default="rules.json")
    w.add_argument("--preset")
    w.add_argument("--threshold", type=float, default=0.85)
    w.set_defaults(fn=cmd_watch)
    r = sub.add_parser("review")  # T170
    r.add_argument("--limit", type=int, default=20)
    r.set_defaults(fn=cmd_review)
    st = sub.add_parser("stats")  # T171
    st.set_defaults(fn=cmd_stats)
    ex = sub.add_parser("export")  # T172
    ex.add_argument("--out", default="audit.csv")
    ex.set_defaults(fn=cmd_export)
    pk = sub.add_parser("pack")  # T173+T174
    pk.add_argument("action", choices=["show", "lint"])
    pk.add_argument("--preset", default="gaming")
    pk.add_argument("--rules")
    pk.set_defaults(fn=cmd_pack)
    args = p.parse_args(argv)
    return args.fn(args)


def _demo():
    from gatekeeper.demo_app import launch
    launch()


if __name__ == "__main__":
    sys.exit(main())
