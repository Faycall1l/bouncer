"""`bouncer` CLI: check/serve/demo/watch/stats/review/pack. Exit codes: 0 allow, 2 delete/flag, 3 escalate."""
from __future__ import annotations

# Apache-2.0. See LICENSE.
import argparse
import json
import sys


def _load_rules(args) -> dict:
    from gatekeeper import get_preset
    if args.preset and getattr(args, "rules", None):  # T483: explicit conflict
        print("bouncer: pass --preset or --rules, not both", file=sys.stderr)
        sys.exit(4)
    if args.preset:
        return get_preset(args.preset)
    path = args.rules or "rules.json"  # T483: None default = not passed
    if not __import__("os").path.exists(path):  # T214
        print(f"bouncer: no rules file {path!r} — pass --rules PATH or --preset NAME",
              file=sys.stderr)
        sys.exit(4)
    with open(path) as f:
        rules = json.load(f)
    from gatekeeper.rules import RuleError, validate_rules  # T314: fail fast, not per-line
    try:
        validate_rules(rules)
    except RuleError as e:
        print(f"bouncer: bad rules: {e}", file=sys.stderr)
        sys.exit(4)
    return rules

def _cfg_from_args(args):
    """T223: split gates; unset flags fall back to the single --threshold."""
    from gatekeeper import GateConfig, questions_knob
    if getattr(args, "config", None):  # T531+T532: file is the base, flags override
        import json as _json
        with open(args.config) as f:
            cfg = GateConfig.from_dict(_json.load(f))
    else:
        cfg = GateConfig(questions=questions_knob())  # T755: BOUNCER_QUESTIONS
    if args.allow_threshold is not None:
        cfg.allow_threshold = args.allow_threshold
    if args.delete_threshold is not None:
        cfg.delete_threshold = args.delete_threshold
    if (args.allow_threshold is None and args.delete_threshold is None
            and (args.threshold != 0.85 or getattr(args, "config", None) is None)):
        cfg.allow_threshold = cfg.delete_threshold = args.threshold
    cfg.validate()
    sev = {}  # T313: ["no-scams=high", ...] -> {"no-scams": "high"}
    for item in getattr(args, "severity", None) or []:
        if "=" not in item:
            print(f"bouncer: bad --severity {item!r} (want RULE=low|high)", file=sys.stderr)
            sys.exit(4)
        rid, level = item.split("=", 1)
        sev[rid.strip()] = level.strip()
    if sev:
        cfg.severity = sev
    if getattr(args, "history", None) is not None:  # T329
        cfg.history_n = args.history
    return cfg


def cmd_check(args) -> int:  # T066+T067+T071+T072
    from gatekeeper import moderate
    from gatekeeper.explain import explain
    rules = _load_rules(args)
    cfg = _cfg_from_args(args)
    model = getattr(args, "model", None)
    if getattr(args, "timeout", None) is not None:  # T516
        cfg.timeout_s = args.timeout
        cfg.validate()
    if args.preset and getattr(args, "lang", None):  # T504: pack/language mismatch note
        from gatekeeper.presets import preset_lang
        want = preset_lang(args.preset)
        if want != args.lang:
            print(f"bouncer: note: preset {args.preset!r} is {want!r} "
                  f"but --lang is {args.lang!r}", file=sys.stderr)
    if model is not None:  # T460: same allowlist as the server
        from gatekeeper.serve import MODELS
        if model not in MODELS:
            print(f"bouncer: bad --model {model!r} (pick from {list(MODELS)})",
                  file=sys.stderr)
            return 4
    res = moderate(args.message, rules, config=cfg, lang=args.lang,  # T311+T312
                   context=args.context or [], model=model,
                   user_id=getattr(args, "user", None))  # T533
    res["reason"] = explain(res, rules)
    if getattr(args, "quiet", False):  # T320
        print(res["action"])
    else:
        print(json.dumps(res, default=str, indent=2) if args.json else f"{res['action']}: {res['reason']}")
    return {"allow": 0, "delete": 2, "flag": 2, "escalate": 3}[res["action"]]


COLORS = {"allow": "\033[32m", "flag": "\033[33m", "delete": "\033[31m", "escalate": "\033[37m"}
RESET = "\033[0m"


def cmd_watch(args) -> int:
    import time

    from gatekeeper import moderate
    from gatekeeper.normalize import strip_controls  # T779: previews/errors scrubbed
    rules = _load_rules(args)
    cfg = _cfg_from_args(args)
    only = {a.strip() for a in (getattr(args, "action", None) or "").split(",")
            if a.strip()}  # T535: comma list of actions to print
    t0 = time.perf_counter()  # T757: wall time under the whole stream
    totals: dict = {}  # T286
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        user, lang, msg = getattr(args, "user", None), getattr(args, "lang", None), line
        if getattr(args, "json_in", False):  # T542: per-line {"message", "user_id"}
            try:
                obj = json.loads(line)
                msg = obj.get("message", "")
                user = obj.get("user_id", user)
                lang = obj.get("lang", lang)
            except (json.JSONDecodeError, AttributeError) as e:
                print(f"bouncer: watch bad json line: {e}", file=sys.stderr)
                continue
            if not isinstance(msg, str) or not msg.strip():
                continue
        try:
            res = moderate(msg, rules, config=cfg, user_id=user,  # T534
                           lang=lang)  # T541
        except Exception as e:  # noqa: BLE001
            print(f"bouncer: watch error: {strip_controls(str(e))}", file=sys.stderr)  # T328
            continue
        totals[res["action"]] = totals.get(res["action"], 0) + 1
        if sum(totals.values()) % 100 == 0:  # T326: heartbeat for long tails
            n = sum(totals.values())
            el = max(time.perf_counter() - t0, 1e-9)  # T757: never /0
            print("totals: " + " ".join(f"{a}={x}" for a, x in sorted(totals.items()))
                  + f" ({n} lines in {el:.2f}s = {n / el:.1f} lines/sec)",
                  file=sys.stderr, flush=True)
        if only and res["action"] not in only:  # T535: filter keeps stdout pipe-clean
            continue
        c = COLORS.get(res["action"], "")
        extra = " -> review queue" if res["action"] in ("flag", "escalate") else ""  # T208
        preview = strip_controls(msg)[:120]  # T779: raw user text on a TTY, scrubbed
        print(f"{c}{res['action']:8}\033[0m {res['rule']}@{res['confidence']:.2f} {preview}{extra}",
              flush=True)
    if totals:  # T286: EOF summary to stderr (keeps stdout pipe-clean)
        print("totals: " + " ".join(f"{a}={n}" for a, n in sorted(totals.items())),
              file=sys.stderr)
        n = sum(totals.values())
        elapsed = max(time.perf_counter() - t0, 1e-9)  # T757: never /0
        print(f"throughput: {n} lines in {elapsed:.2f}s = {n / elapsed:.1f} lines/sec",
              file=sys.stderr)
    return 0


def cmd_models(args) -> int:  # T538: checkpoints + pool stats, never weights
    from gatekeeper.pool import POOL
    print("checkpoints (laya):")
    for name in ("english", "multilingual", "typed-decisions"):
        print(f"  {name}")
    s = POOL.stats()
    print(f"pool: size={s['size']}/{s['max_n']} hits={s['hits']} "
          f"creates={s['creates']} evictions={s['evictions']}")
    return 0


def cmd_presets(args) -> int:  # T539: names + descriptions
    from gatekeeper import list_presets
    from gatekeeper.presets import PRESET_LANG
    for name, desc in list_presets().items():
        print(f"{name:10} [{PRESET_LANG.get(name, '?')}] {desc}")
    return 0


def cmd_review(args) -> int:
    from gatekeeper.review import clear_queue, list_queue
    if args.clear:  # T318
        if not args.yes:
            print("bouncer: review --clear needs --yes (drops the whole queue)",
                  file=sys.stderr)
            return 4
        print(f"cleared {clear_queue()} queued rows")
        return 0
    if getattr(args, "prune", False):  # T540: age-based drop, keeps the rest
        from gatekeeper.review import prune
        print(f"pruned {prune(args.older_than)} rows older than {args.older_than}s")
        return 0
    for row in list_queue(args.limit, action=args.action,
                          since=getattr(args, "since", 0) or 0,  # T537
                          rule=getattr(args, "rule", None)):  # T543
        print(f"{row['action']:8} {row['rule']}@{row['conf']:.2f} {row['message'][:100]}")
    return 0


def cmd_stats(args) -> int:
    from gatekeeper.cache import CACHE
    from gatekeeper.pool import POOL  # T461
    from gatekeeper.stats import get_stats
    snap = {"decisions": get_stats(), "cache": CACHE.stats(), "pool": POOL.stats()}
    if getattr(args, "json", False):  # T315
        print(json.dumps(snap, indent=2))
        return 0
    a = snap["decisions"]["actions"]  # T315: one-line human summary
    print(f"allow={a.get('allow', 0)} flag={a.get('flag', 0)} delete={a.get('delete', 0)} "
          f"escalate={a.get('escalate', 0)} total={snap['decisions']['total']} "
          f"cache_hits={snap['cache']['hits']} p50={snap['decisions']['latency']['p50_ms']}ms")
    from gatekeeper import strikes as _st  # T443
    users = len(_st._strikes)
    print(f"strikes: {users} users, {sum(_st._strikes.values())} total")
    print(f"pool: size={snap['pool']['size']}/{snap['pool']['max_n']} "  # T461
          f"hits={snap['pool']['hits']} creates={snap['pool']['creates']}")
    return 0


def cmd_snapshot(args) -> int:  # T437+T438
    import json as _json
    import time as _t

    from gatekeeper import __version__
    from gatekeeper import strikes as _strikes
    from gatekeeper.persist import SnapshotError, atomic_write, read_json
    from gatekeeper.stats import restore as _restore
    from gatekeeper.stats import snapshot as _snap
    if args.action == "save":
        snap = _snap()
        doc = {"v": 1, "t": int(_t.time()), "bouncer": __version__,
               "stats": snap, "strikes": dict(_strikes._strikes)}
        atomic_write(args.file, _json.dumps(doc, indent=2))
        print(f"snapshot -> {args.file} "
              f"(total={sum(snap['counts'].values())}, users={len(doc['strikes'])})")
        return 0
    data = read_json(args.file)
    if data.get("v") != 1:  # T438+T449: version mismatch warns, never fails
        raise SnapshotError(f"E_SNAPSHOT: unsupported snapshot version {data.get('v')!r}")
    if data.get("bouncer") != __version__:
        print(f"bouncer: snapshot from {data.get('bouncer')} (running {__version__})",
              file=sys.stderr)
    _restore(data.get("stats", {}))
    for user, n in (data.get("strikes", {}) or {}).items():
        if isinstance(n, int) and n > 0:
            _strikes._strikes[user] = max(_strikes._strikes.get(user, 0), n)
    print(f"snapshot <- {args.file}")
    return 0


def cmd_export(args) -> int:
    import csv

    from gatekeeper.audit import _PATH
    if getattr(args, "stats", None):  # T445: snapshot JSON instead of audit CSV
        import json as _json

        from gatekeeper import strikes as _strikes
        from gatekeeper.persist import atomic_write
        from gatekeeper.stats import snapshot as _snap
        snap = _snap()
        atomic_write(args.stats, _json.dumps({"stats": snap,
                                             "strikes": dict(_strikes._strikes)},
                                            indent=2))
        print(f"snapshot -> {args.stats} (total={sum(snap['counts'].values())})")
        return 0
    since = getattr(args, "since", 0) or 0  # T327: epoch filter on audit "t"
    limit = getattr(args, "limit", 0) or 0  # T449: bounded tail read
    as_json = getattr(args, "format", "csv") == "json"  # T536: raw JSON array out
    only = {a.strip() for a in (getattr(args, "action", None) or "").split(",")
            if a.strip()}  # T544: comma list of actions to keep
    rows, mss = [], []
    if limit:
        from gatekeeper.audit import tail as _tail
        rows = [d for d in _tail(limit)
                if d["t"] >= since and (not only or d["action"] in only)]
    elif __import__("os").path.exists(_PATH):
        with open(_PATH) as af:
            for line in af:
                d = json.loads(line)
                if d["t"] >= since and (not only or d["action"] in only):
                    rows.append(d)
    for d in rows:
        mss.append(d["ms"])
    if as_json:  # T536: exact audit dicts, nothing dropped
        from gatekeeper.persist import atomic_write
        atomic_write(args.out, json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        with open(args.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", "msg", "rule", "conf", "action", "ms"])
            w.writerows([d["t"], d["msg"], d["rule"], d["conf"], d["action"], d["ms"]]
                        for d in rows)
    mss.sort()  # T316
    p50 = mss[len(mss) // 2] if mss else 0
    print(f"exported {len(rows)} rows -> {args.out} (latency p50 {p50}ms)")
    return 0


def cmd_pack(args) -> int:
    from gatekeeper import get_preset
    from gatekeeper.rules import validate_rules, warn_overlapping
    if args.action == "init":  # T545: template pack to edit, based on a preset
        import os
        if os.path.exists(args.file) and not getattr(args, "force", False):
            print(f"bouncer: {args.file!r} exists (pass --force to overwrite)",
                  file=sys.stderr)
            return 4
        from gatekeeper.persist import atomic_write
        template = get_preset(args.preset)
        atomic_write(args.file, json.dumps(template, indent=2, ensure_ascii=False))
        print(f"pack -> {args.file} ({len(template)} template rules from "
              f"{args.preset!r}); edit ids/text then `bouncer pack lint --rules {args.file}`")
        return 0
    if args.rules:
        with open(args.rules) as f:
            rules = json.load(f)
    else:
        rules = get_preset(args.preset)
    if args.action == "show":
        if getattr(args, "format", "json") == "lines":  # T325: grep-friendly
            for rid, text in rules.items():
                print(f"{rid}: {text}")
        else:
            print(json.dumps(rules, indent=2, ensure_ascii=False))
    else:
        validate_rules(rules)
        warns = warn_overlapping(rules)
        for w in warns:
            print("warn:", w)
        print(f"pack ok: {len(rules)} rules")
        if warns and getattr(args, "strict", False):  # T319
            return 2
    return 0


def _add_threshold_flags(p) -> None:
    p.add_argument("--threshold", type=float, default=0.85)
    p.add_argument("--allow-threshold", type=float, default=None)  # T223
    p.add_argument("--delete-threshold", type=float, default=None)  # T223


def _cmd_serve(args) -> int:  # T547+T549: secrets/flags applied before uvicorn starts
    import os
    if getattr(args, "key_file", None):
        try:
            with open(args.key_file) as f:
                key = f.read().strip()
        except OSError as e:
            print(f"bouncer: cannot read --key-file: {e}", file=sys.stderr)
            return 4
        if not key:
            print("bouncer: --key-file is empty", file=sys.stderr)
            return 4
        os.environ["BOUNCER_KEY"] = key  # serve.py reads BOUNCER_KEY (T547 fixed T609)
    if getattr(args, "cors", None):  # T549: flag beats env
        os.environ["BOUNCER_CORS"] = args.cors
    import uvicorn
    uvicorn.run("gatekeeper.serve:app", host=args.host, port=args.port,
                workers=args.workers)
    return 0


def cmd_doctor(args) -> int:  # T727: env/dep/route self-diagnosis
    """Weightless health report: interpreter, config, adapter env (presence
    only — values are never printed), importable deps, model routing.
    Never loads the model or touches the network. Warns are documented
    degraded modes (missing laya = escalate fallback); exit 1 only when
    something is actually broken (python floor, unreadable config)."""
    import ast
    import importlib.util
    import os
    import platform
    from pathlib import Path

    from gatekeeper import __version__
    from gatekeeper.adapters.common import AdapterError, load_config
    from gatekeeper.pool import model_for_lang

    findings: list[tuple[str, str, str, str]] = []  # level, area, name, detail

    def note(level: str, area: str, name: str, detail: str) -> None:
        findings.append((level, area, name, detail))

    # -- env: interpreter, package, config file (E_ADAPTER names the broken
    #    one), adapter requirements found by scanning require_env("NAME")
    pyv = sys.version_info[:2]
    note("ok" if pyv >= (3, 10) else "fail", "env", "python",
         f"{platform.python_version()} (requires >=3.10)")
    note("ok", "env", "bouncer", __version__)
    cfg_path = os.environ.get("BOUNCER_CONFIG", "").strip() or "bouncer.toml"
    if os.path.exists(cfg_path):
        try:
            load_config(cfg_path)
            note("ok", "env", "config", cfg_path)
        except AdapterError as e:  # E_ADAPTER: the file is the fault
            note("fail", "env", "config", str(e))
    else:
        note("ok", "env", "config", f"{cfg_path} absent (defaults)")
    adir = Path(__file__).parent / "adapters"
    for path in sorted(adir.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            is_req = (isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name)
                      and node.func.id == "require_env" and node.args
                      and isinstance(node.args[0], ast.Constant)
                      and isinstance(node.args[0].value, str))
            if is_req:
                env = node.args[0].value
                present = bool(os.environ.get(env))
                note("ok" if present else "info", "env", env,
                     f"{path.stem}: env "
                     f"{'set' if present else 'unset (bouncer.toml may supply it)'}")

    # -- dep: find_spec locates without importing — no side effects, no
    #    weights; missing pieces are warns because the engine degrades.
    #    T730: the list must cover every core dependency — the sweep test
    #    asserts set equality with pyproject, so drift fails the build.
    for mod, why in (("numpy", "tensor ops"),
                     ("laya", "System One router (predicts)"),
                     ("fastapi", "HTTP server"),
                     ("uvicorn", "HTTP server"),
                     ("pydantic", "HTTP request models"),
                     ("gradio", "demo app"),
                     ("datasets", "eval data loading"),
                     ("huggingface_hub", "weight downloads")):
        present = importlib.util.find_spec(mod) is not None
        note("ok" if present else "warn", "dep", mod,
             "importable" if present else f"missing — {why} unavailable")

    # -- route: checkpoint per language + device policy. The pool is json/os
    #    only (T458), so this never wakes the model.
    for lang in ("en", "es", "zh", "ar", "ja"):
        note("ok", "route", f"model[{lang}]", model_for_lang(lang) or "default")
    dev = os.environ.get("BOUNCER_DEVICE", "").strip()
    note("ok", "route", "device", dev or "auto")

    for level, area, name, detail in findings:
        print(f"{level:4}  {area:5}  {name}: {detail}")
    fails = sum(1 for lv, *_ in findings if lv == "fail")
    warns = sum(1 for lv, *_ in findings if lv == "warn")
    print(f"doctor: {len(findings)} checks, {warns} warn, {fails} fail")
    return 1 if fails else 0


def build_parser() -> argparse.ArgumentParser:  # T610: testable without dispatch
    p = argparse.ArgumentParser(prog="bouncer",  # T321: exit codes up front
                                epilog="exit codes: 0 allow · 2 delete/flag · 3 escalate · "
                                       "4 usage/rules error")
    p.add_argument("--version", action="store_true")  # T215
    sub = p.add_subparsers(dest="cmd", required=False)
    sub.required = False
    c = sub.add_parser("check")
    c.add_argument("message")
    c.add_argument("--rules", default=None)  # T483: None = not passed (conflict check)
    c.add_argument("--preset")
    _add_threshold_flags(c)
    c.add_argument("--lang", default=None)  # T311
    c.add_argument("--context", action="append", default=None)  # T312: repeatable
    c.add_argument("--severity", action="append", default=None)  # T313: RULE=low|high
    c.add_argument("--quiet", action="store_true")  # T320: action word only
    c.add_argument("--history", type=int, default=None)  # T329: override history_n
    c.add_argument("--model", default=None)  # T460: pin checkpoint
    c.add_argument("--timeout", type=float, default=None)  # T516: inference budget
    c.add_argument("--config", default=None)  # T531: JSON gate config file
    c.add_argument("--user", default=None)  # T533: strikes attribution
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_check)
    s = sub.add_parser("serve")  # T068
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--workers", type=int, default=1)  # T322
    s.add_argument("--key-file", default=None)  # T547: read API key from a file
    s.add_argument("--cors", default=None)  # T549: comma origins, overrides env
    s.set_defaults(fn=_cmd_serve)
    d = sub.add_parser("demo")  # T069
    d.add_argument("--port", type=int, default=7860)  # T323
    d.add_argument("--share", action="store_true")  # T323
    d.add_argument("--preset", default=None)  # T548: default selection on launch
    d.set_defaults(fn=lambda a: (_demo(a), 0))
    w = sub.add_parser("watch")  # T070+T169: stdin pipe, colored live tail
    w.add_argument("--rules", default=None)  # T483
    w.add_argument("--preset")
    w.add_argument("--config", default=None)  # T532
    w.add_argument("--user", default=None)  # T534: attribute piped lines to one user
    w.add_argument("--action", default=None)  # T535: comma list, e.g. flag,escalate
    w.add_argument("--lang", default=None)  # T541: language hint for the whole pipe
    w.add_argument("--json-in", action="store_true")  # T542: per-line {"message","user_id"}
    _add_threshold_flags(w)
    w.set_defaults(fn=cmd_watch)
    r = sub.add_parser("review")  # T170
    r.add_argument("--limit", type=int, default=20)
    r.add_argument("--action", default=None)  # T317
    r.add_argument("--since", type=float, default=0)  # T537: epoch seconds
    r.add_argument("--rule", default=None)  # T543
    r.add_argument("--prune", action="store_true")  # T540: drop aged rows
    r.add_argument("--older-than", type=float, default=86400.0)  # T540: seconds
    r.add_argument("--clear", action="store_true")  # T318
    r.add_argument("--yes", action="store_true")  # T318
    r.set_defaults(fn=cmd_review)
    md = sub.add_parser("models")  # T538
    md.set_defaults(fn=cmd_models)
    ps = sub.add_parser("presets")  # T539
    ps.set_defaults(fn=cmd_presets)
    st = sub.add_parser("stats")  # T171
    st.add_argument("--json", action="store_true")  # T315
    st.set_defaults(fn=cmd_stats)
    ex = sub.add_parser("export")  # T172
    ex.add_argument("--out", default="audit.csv")
    ex.add_argument("--since", type=float, default=0)  # T327: epoch seconds
    ex.add_argument("--stats", default=None)  # T445: snapshot JSON path
    ex.add_argument("--limit", type=int, default=0)  # T449: bounded tail export
    ex.add_argument("--format", choices=["csv", "json"], default="csv")  # T536
    ex.add_argument("--action", default=None)  # T544: comma list, e.g. delete
    ex.set_defaults(fn=cmd_export)
    sn = sub.add_parser("snapshot")  # T437+T438
    sn.add_argument("action", choices=["save", "load"])
    sn.add_argument("file")
    sn.set_defaults(fn=cmd_snapshot)
    pk = sub.add_parser("pack")  # T173+T174
    pk.add_argument("action", choices=["show", "lint", "init"])  # T545
    pk.add_argument("file", nargs="?", default=None)  # T545: init target path
    pk.add_argument("--force", action="store_true")  # T545: overwrite on init
    pk.add_argument("--preset", default="gaming")
    pk.add_argument("--rules")
    pk.add_argument("--strict", action="store_true")  # T319: exit 2 on warnings
    pk.add_argument("--format", choices=["json", "lines"], default="json")  # T325
    pk.set_defaults(fn=cmd_pack)
    dr = sub.add_parser("doctor")  # T727: env/dep/route self-diagnosis
    dr.set_defaults(fn=cmd_doctor)
    return p


def main(argv=None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    if args.version or args.cmd is None:
        if args.version:
            from gatekeeper import __version__
            print(f"bouncer {__version__}")
            return 0
        p.print_help()
        return 2
    return args.fn(args)


def _demo(args=None):
    from gatekeeper.demo_app import launch
    kw = {} if args is None else {"port": args.port, "share": args.share}  # T323
    if args is not None and getattr(args, "preset", None):  # T548
        from gatekeeper import list_presets
        if args.preset not in list_presets():
            print(f"bouncer: unknown preset {args.preset!r} "
                  f"(pick from {sorted(list_presets())})", file=sys.stderr)
            sys.exit(4)
        kw["preset"] = args.preset
    launch(**kw)


if __name__ == "__main__":
    sys.exit(main())
