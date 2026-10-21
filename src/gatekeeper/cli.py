"""`bouncer` CLI: check/serve/demo/watch/stats/review/pack.

Exit codes: 0 allow, 2 delete/flag, 3 escalate.
"""
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
    rules = _pack_rules(rules)  # T878: a typed pack runs like a bare one
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


def _cli_lang(hint: str | None, msg: str) -> str | None:  # T893
    """`--lang auto` = detect from the message's own script (ar/zh/ru, else
    None — the same refusal to claim a language from latin text, T857).
    Every other value passes through as the explicit hint it is."""
    if hint != "auto":
        return hint
    from gatekeeper.adapters.common import detect_lang
    return detect_lang(msg)


def cmd_check(args) -> int:  # T066+T067+T071+T072+T874
    from gatekeeper import moderate
    from gatekeeper.explain import explain
    path = getattr(args, "file", None)  # T874: argument checks before rules
    if path is not None and args.message is not None:
        print("bouncer: pass exactly one of MESSAGE or --file", file=sys.stderr)
        return 4
    if path is None and args.message is None:
        print("bouncer: check needs MESSAGE or --file", file=sys.stderr)
        return 4
    lines: list = []
    if path is not None:
        import os
        if not os.path.exists(path):
            print(f"bouncer: no message file {path!r}", file=sys.stderr)
            return 4
        try:
            with open(path) as f:
                lines = f.readlines()
        except OSError as e:
            print(f"bouncer: cannot read message file {path!r} "
                  f"({e.strerror or e})", file=sys.stderr)
            return 4
    rules = _load_rules(args)
    cfg = _cfg_from_args(args)
    model = getattr(args, "model", None)
    if getattr(args, "timeout", None) is not None:  # T516
        cfg.timeout_s = args.timeout
        cfg.validate()
    if args.preset and getattr(args, "lang", None) not in (None, "auto"):  # T504:
        from gatekeeper.presets import preset_lang  # T893: auto has no opinion
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
    if path is not None:  # T874: batch scoring — args checked, lines read up top
        code = {"allow": 0, "delete": 2, "flag": 2, "escalate": 3}
        worst = 0
        for i, line in enumerate(lines, 1):  # 1-based: maps back to the file
            msg = line.rstrip("\r\n")
            if not msg.strip():  # blank separators aren't messages
                continue
            res = moderate(msg, None if args.preset else rules,  # T883:
                           config=cfg, lang=_cli_lang(args.lang, msg),  # T893
                           context=args.context or [], model=model,  # preset resolves inside
                           user_id=getattr(args, "user", None),
                           preset=args.preset)  # the audit row names the pack
            res["line"] = i
            res["reason"] = explain(res, rules)  # the CLI's own wording
            print(json.dumps(res, default=str))  # one JSON per input line
            worst = max(worst, code[res["action"]])
        return worst  # the worst action in the batch, like the single shot
    res = moderate(args.message, None if args.preset else rules,  # T311+T312
                   config=cfg, lang=_cli_lang(args.lang, args.message),  # T883+
                   context=args.context or [], model=model,  # T893: auto detects
                   user_id=getattr(args, "user", None),  # T533 names the pack
                   preset=args.preset)
    res["reason"] = explain(res, rules)
    if getattr(args, "quiet", False):  # T320
        print(res["action"])
    else:
        print(json.dumps(res, default=str, indent=2) if args.json
              else f"{res['action']}: {res['reason']}")
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
            res = moderate(msg, None if getattr(args, "preset", None)
                           else rules,  # T883: preset resolves inside
                           config=cfg, user_id=user,  # T534
                           lang=_cli_lang(lang, msg),  # T541+T893: auto detects
                           preset=getattr(args, "preset", None))
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
        tag = f" [{row['verdict']}]" if row.get("verdict") else ""  # T865
        ctx = "".join(f" {k}={row[k]}" for k in ("cause", "model", "preset")  # T882
                      if row.get(k))  # old rows predate the fields: stay quiet
        print(f"{row.get('id', '-'):8} {row['action']:8} "
              f"{row['rule']}@{row['conf']:.2f}{tag}{ctx} {row['message'][:100]}")
    return 0


def cmd_adjudicate(args) -> int:  # T865: operator verdict on one queued row
    from gatekeeper.review import adjudicate
    try:
        row = adjudicate(args.row_id, args.verdict)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if row is None:
        print(f"bouncer: no queue row {args.row_id}", file=sys.stderr)
        return 1
    line = f"{row.get('id', args.row_id)} {args.verdict} " \
           f"{row['action']}@{row['conf']:.2f}"
    if row.get("after") is not None:  # reject: amnesty recorded the result
        line += f" user={row['user']} strikes {row['after']['strikes']}"
    print(line)
    return 0


def cmd_amnesty(args) -> int:  # T881: operator forgiveness, outside the queue
    """`bouncer amnesty USER [--weight N]` — clear a user's strikes after an
    appeal, without needing a queue row (adjudicate's amnesty only fires on
    a rejected row). Loads the persisted table first (the CLI is a fresh
    process), clears everything by default, subtracts exactly N with
    --weight (the T865 primitive), then saves back."""
    import os

    from gatekeeper import strikes
    if os.path.exists(strikes._PATH):  # a missing table is an empty table
        strikes.load()  # SnapshotError (E_SNAPSHOT) propagates to the wrapper
    before = strikes.standing(args.user)["strikes"]
    if not before:
        print(f"bouncer: no strikes for {args.user}", file=sys.stderr)
        return 1
    weight = before if args.weight is None else max(0, args.weight)
    after = strikes.amnesty(args.user, weight)
    strikes.save()
    print(f"amnesty {args.user}: strikes {before} -> {after['strikes']}")
    return 0


def cmd_config(args) -> int:  # T871: standalone config lint
    """`bouncer config validate` — parse bouncer.toml (E_ADAPTER) and/or a
    GateConfig JSON (E_CONFIG: unknown keys, bad ranges, wrong shape,
    malformed JSON) without running a decision, a server, or the doctor.
    No paths given = the default adapter file (absent is fine); an
    explicitly named file that doesn't exist fails. Exit 0 all valid,
    1 any failure, 2 a bare `config` with no subcommand."""
    import os

    from gatekeeper.adapters.common import AdapterError, load_config
    from gatekeeper.config import ConfigError, GateConfig

    if getattr(args, "cfg_cmd", None) != "validate":
        print("bouncer: config needs a subcommand (validate)", file=sys.stderr)
        return 2
    toml_path = getattr(args, "toml", None)
    json_path = getattr(args, "json", None)
    if toml_path is None and json_path is None:  # default target: adapter file
        toml_path = os.environ.get("BOUNCER_CONFIG", "").strip() or "bouncer.toml"
    bad = 0
    if toml_path is not None:
        if not os.path.exists(toml_path):
            if getattr(args, "toml", None) is not None:  # named: must exist
                print(f"fail: {toml_path} — no such file")
                bad += 1
            else:
                print(f"ok: {toml_path} absent (defaults)")
        else:
            try:
                load_config(toml_path)
                print(f"ok: {toml_path}")
            except AdapterError as e:  # E_ADAPTER names the file
                print(f"fail: {toml_path} — {e}")
                bad += 1
    if json_path is not None:
        try:
            with open(json_path) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ConfigError("E_CONFIG: expected a JSON object of gate keys")
            cfg = GateConfig.from_dict(data)
            cfg.validate()
            print(f"ok: {json_path}")
        except FileNotFoundError:
            print(f"fail: {json_path} — no such file")
            bad += 1
        except json.JSONDecodeError as e:
            print(f"fail: {json_path} — not valid JSON: {e}")
            bad += 1
        except ConfigError as e:  # E_CONFIG: unknown keys or bad ranges
            print(f"fail: {json_path} — {e}")
            bad += 1
        except OSError as e:
            print(f"fail: {json_path} — unreadable: {e.strerror or e}")
            bad += 1
    return 1 if bad else 0


def cmd_completion(args) -> int:  # T875: shell completion from the parser
    """Print a completion script for `bouncer` — `source <(bouncer
    completion bash)` (or zsh). Generated from build_parser() itself: the
    subcommand list and every option line come from the parser's actions,
    so a new command or flag completes without touching this function."""
    p = build_parser()
    subs = next(a for a in p._actions
                if isinstance(a, argparse._SubParsersAction)).choices
    top = sorted(subs)
    per = {name: sorted({o for a in pa._actions for o in a.option_strings})
           for name, pa in sorted(subs.items())}
    if args.shell == "bash":
        words = " ".join(top + ["--version", "--help"])
        out = ["_bouncer_complete() {",
               '    local cur="${COMP_WORDS[COMP_CWORD]}"',
               '    if [ "$COMP_CWORD" -eq 1 ]; then',
               f"        COMPREPLY=( $(compgen -W \"{words}\" -- \"$cur\") )",
               "        return",
               "    fi",
               '    case "${COMP_WORDS[1]}" in']
        for name, opts in per.items():
            ow = " ".join(opts) or "--help"
            out += [f"        {name})",
                    f"            COMPREPLY=( $(compgen -W \"{ow}\" -- \"$cur\") )",
                    "            ;;"]
        out += ["    esac", "}", "complete -F _bouncer_complete bouncer"]
        print("\n".join(out))
        return 0
    out = ["#compdef bouncer", "_bouncer() {", "    local -a cmds",
           f"    cmds=({' '.join(top)})",
           "    if (( CURRENT == 2 )); then",
           "        _describe 'command' cmds",
           "        return",
           "    fi",
           "    case $words[2] in"]
    for name, opts in per.items():
        ow = " ".join(opts) or "--help"
        out += [f"        {name}) compadd -- {ow} ;;"]
    out += ["    esac", "}", "compdef _bouncer bouncer"]
    print("\n".join(out))
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
    from gatekeeper.cache import CACHE  # T877: the cache rides along
    from gatekeeper.persist import SnapshotError, atomic_write, read_json
    from gatekeeper.stats import restore as _restore
    from gatekeeper.stats import snapshot as _snap
    if args.action == "save":
        snap = _snap()
        doc = {"v": 2, "t": int(_t.time()), "bouncer": __version__,  # T876
               "stats": snap, "strikes": dict(_strikes._strikes),
               "cache": CACHE.dump()}  # T877: live decisions only
        atomic_write(args.file, _json.dumps(doc, indent=2))
        print(f"snapshot -> {args.file} "
              f"(total={sum(snap['counts'].values())}, users={len(doc['strikes'])},"
              f" cache={len(doc['cache']['entries'])})")
        return 0
    data = read_json(args.file)
    v = data.get("v")
    migrated = v == 1  # T876: v1 migrates in memory, v2 is native
    if migrated:
        data = dict(data, v=2)  # sections ride through unchanged
    elif v != 2:
        raise SnapshotError(f"E_SNAPSHOT: unsupported snapshot version {v!r}")
    if not isinstance(data.get("strikes", {}), dict):  # v2 contract (T876)
        raise SnapshotError("E_SNAPSHOT: strikes table must be an object")
    if "cache" in data:  # T877: every section validated before any applies
        CACHE.check(data["cache"])
    if data.get("bouncer") != __version__:
        print(f"bouncer: snapshot from {data.get('bouncer')} (running {__version__})",
              file=sys.stderr)
    _restore(data.get("stats", {}))
    for user, n in (data.get("strikes", {}) or {}).items():
        if isinstance(n, int) and n > 0:
            _strikes._strikes[user] = max(_strikes._strikes.get(user, 0), n)
    cached = CACHE.restore(data["cache"]) if "cache" in data else 0  # T877
    print(f"snapshot <- {args.file}"
          + (" (migrated v1 -> v2)" if migrated else "")  # T876: say so
          + (f", cache={cached}" if "cache" in data else ""))
    return 0


def cmd_export(args) -> int:
    import csv

    from gatekeeper.audit import _PATH
    if getattr(args, "stats", None):  # T445: snapshot JSON instead of audit CSV
        import json as _json

        from gatekeeper import __version__
        from gatekeeper import strikes as _strikes
        from gatekeeper.persist import atomic_write
        from gatekeeper.stats import snapshot as _snap
        snap = _snap()
        atomic_write(args.stats, _json.dumps({"v": 2,  # T876: a loadable doc
                                              "bouncer": __version__,
                                              "stats": snap,
                                              "strikes": dict(_strikes._strikes)},
                                             indent=2))
        print(f"snapshot -> {args.stats} (total={sum(snap['counts'].values())})")
        return 0
    since = getattr(args, "since", 0) or 0  # T327: epoch filter on audit "t"
    limit = getattr(args, "limit", 0) or 0  # T449: bounded tail read
    only = {a.strip() for a in (getattr(args, "action", None) or "").split(",")
            if a.strip()}  # T544: comma list of actions to keep
    if getattr(args, "queue", False):  # T886: the review queue as an appeal
        # audit trail — who was flagged, why, and how it was adjudicated
        from gatekeeper.review import list_queue
        rows = list_queue(limit=limit or 1000,  # no --limit = the whole queue
                          action=only.pop() if len(only) == 1 else None,
                          since=since)
        if len(only) > 1:  # multi-action filter: list_queue takes one action
            rows = [r for r in rows if r.get("action") in only]
        if getattr(args, "format", "csv") == "json":
            from gatekeeper.persist import atomic_write
            atomic_write(args.out, json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            with open(args.out, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["t", "id", "user", "action", "rule", "conf",
                            "cause", "model", "preset", "verdict", "vt",
                            "after_strikes", "message"])  # T886: appeal context
                w.writerows([d.get("t", 0), d.get("id", ""), d.get("user") or "",
                             d.get("action", ""), d.get("rule", ""),
                             d.get("conf", ""), d.get("cause", ""),
                             d.get("model", ""), d.get("preset", ""),
                             d.get("verdict", ""), d.get("vt", ""),
                             (d.get("after") or {}).get("strikes", ""),
                             d.get("message", "")]  # raw text: queue-only file
                            for d in rows)
        print(f"exported {len(rows)} queue rows -> {args.out} (appeal trail)")
        return 0
    as_json = getattr(args, "format", "csv") == "json"  # T536: raw JSON array out
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
            w.writerow(["t", "msg", "rule", "conf", "action", "ms",
                        "cause", "preset", "model", "rid", "v"])  # T883
            w.writerows([d["t"], d["msg"], d["rule"], d["conf"], d["action"],
                         d["ms"], d.get("cause", ""), d.get("preset", ""),
                         d.get("model", ""), d.get("rid", ""),
                         d.get("v", "")]  # pre-T883 rows export as ""
                        for d in rows)
    mss.sort()  # T316
    p50 = mss[len(mss) // 2] if mss else 0
    print(f"exported {len(rows)} rows -> {args.out} (latency p50 {p50}ms)")
    return 0


def _pack_digest(rules: dict) -> str:  # T873
    """sha256 over sorted `id \\0 text \\n` lines — canonical, so re-saving
    a pack with another key order never changes the signature."""
    import hashlib
    h = hashlib.sha256()
    for rid in sorted(rules):
        h.update(f"{rid}\0{rules[rid]}\n".encode())
    return h.hexdigest()


def _pack_rules(data: dict):
    """T878: a typed pack is {meta: {...}, rules: {id: text}}; a bare pack
    is {id: text} itself. Bare packs can't have dict-valued ids (texts are
    strings), so the shape is unambiguous — old packs keep working.
    Anything else (a list, a string) passes through to fail validation."""
    if (isinstance(data, dict) and isinstance(data.get("meta"), dict)
            and isinstance(data.get("rules"), dict)):
        return data["rules"]
    return data


def _read_pack(path: str):
    """T786+T872: one hardened read for every pack file — missing/unreadable/
    hostile nesting die with a machine code line, never a traceback; a
    parsed non-object isn't a rules pack ({id: text}) either. Returns the
    rules dict (unwrapping a typed pack, T878), or None (message already
    printed; caller exits)."""
    import os as _os

    def _no_dup_keys(pairs):
        # T879: the JSON scanner keeps the LAST of duplicate keys, so two
        # rules with the same id silently collapse before validate_rules
        # ever runs — reject at parse time instead.
        seen = set()
        for key, _value in pairs:
            if key in seen:
                raise ValueError(f"duplicate key {key!r} (rule id used twice)")
            seen.add(key)
        return dict(pairs)

    if not _os.path.exists(path):
        print(f"bouncer: no pack file {path!r}", file=sys.stderr)
        return None
    try:
        with open(path) as f:
            data = json.load(f, object_pairs_hook=_no_dup_keys)
    except (OSError, ValueError, RecursionError) as e:
        # ValueError == JSONDecodeError; the C scanner raises
        # RecursionError (not ValueError) on hostile deep nesting on
        # some versions — either way the pack is unreadable (T814)
        print(f"bouncer: cannot read pack {path!r} ({e})",
              file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"bouncer: {path!r} is not a rules object ({{id: text}})",
              file=sys.stderr)
        return None
    return _pack_rules(data)


def cmd_pack(args) -> int:
    from gatekeeper import get_preset
    from gatekeeper.rules import (
        RuleError,
        validate_rules,
        warn_overlapping,
        warn_preset_verbatim,  # T880: preset copy-paste
    )
    if args.action == "init":  # T545+T878: template pack to edit, based on a preset
        import os
        if os.path.exists(args.file) and not getattr(args, "force", False):
            print(f"bouncer: {args.file!r} exists (pass --force to overwrite)",
                  file=sys.stderr)
            return 4
        import time as _t

        from gatekeeper import __version__
        from gatekeeper.persist import atomic_write
        from gatekeeper.presets import preset_lang
        template = get_preset(args.preset)
        doc = {"meta": {"v": 1, "bouncer": __version__,  # T878: typed pack
                        "created": int(_t.time()),
                        "preset": args.preset,
                        "lang": preset_lang(args.preset),
                        "rules": len(template)},
               "rules": template}
        atomic_write(args.file, json.dumps(doc, indent=2, ensure_ascii=False))
        print(f"pack -> {args.file} ({len(template)} template rules from "
              f"{args.preset!r}); edit ids/text then `bouncer pack lint --rules {args.file}`")
        return 0
    if args.action == "diff":  # T872: compare two packs, exit 2 on drift
        if not args.file or not args.file2:
            print("bouncer: pack diff needs two files: bouncer pack diff OLD NEW",
                  file=sys.stderr)
            return 4
        old = _read_pack(args.file)
        if old is None:
            return 4
        new = _read_pack(args.file2)
        if new is None:
            return 4
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
        for rid in added:
            print(f"+ {rid}: {new[rid]}")
        for rid in removed:
            print(f"- {rid}: {old[rid]}")
        for rid in changed:
            print(f"~ {rid}: {old[rid]!r} -> {new[rid]!r}")
        if not (added or removed or changed):
            print(f"packs identical: {len(old)} rules")
            return 0
        print(f"pack drift: +{len(added)} -{len(removed)} ~{len(changed)}")
        return 2
    if args.action in ("sign", "verify"):  # T873: tamper-evident packs
        verb = args.action
        if not args.file:
            print(f"bouncer: pack {verb} needs a file: "
                  f"bouncer pack {verb} FILE", file=sys.stderr)
            return 4
        rules = _read_pack(args.file)
        if rules is None:
            return 4
        sig_path = args.file + ".sig"
        if verb == "sign":
            import time as _t

            from gatekeeper.persist import atomic_write
            manifest = {"v": 1, "algo": "sha256", "digest": _pack_digest(rules),
                        "rules": len(rules), "t": int(_t.time())}
            atomic_write(sig_path, json.dumps(manifest, indent=2))
            print(f"signed {args.file} -> {sig_path} "
                  f"({len(rules)} rules, sha256 {manifest['digest']})")
            return 0
        # verify: no manifest / unreadable manifest are file problems (4);
        # a content mismatch is drift against the manifest (2) — both coded
        import os
        if not os.path.exists(sig_path):
            print(f"bouncer: E_PACK_SIG: no manifest {sig_path!r} "
                  "(run bouncer pack sign)", file=sys.stderr)
            return 4
        try:
            with open(sig_path) as f:
                manifest = json.load(f)
        except (OSError, ValueError, RecursionError) as e:
            print(f"bouncer: E_PACK_SIG: cannot read manifest "
                  f"{sig_path!r} ({e})", file=sys.stderr)
            return 4
        want = manifest.get("digest") if isinstance(manifest, dict) else None
        if (not isinstance(manifest, dict) or manifest.get("algo") != "sha256"
                or not isinstance(want, str)):
            print(f"bouncer: E_PACK_SIG: {sig_path!r} is not a sha256 manifest",
                  file=sys.stderr)
            return 4
        got = _pack_digest(rules)
        if got != want.lower():
            print(f"bouncer: E_PACK_SIG: {args.file} does not match its manifest "
                  f"(pack {got} vs manifest {want.lower()})", file=sys.stderr)
            return 2
        print(f"verified {args.file}: {len(rules)} rules, sha256 {got}")
        return 0
    if args.rules:
        rules = _read_pack(args.rules)  # T786+T872: the shared hardened read
        if rules is None:
            return 4
    else:
        rules = get_preset(args.preset)
    if args.action == "show":
        if getattr(args, "format", "json") == "lines":  # T325: grep-friendly
            for rid, text in rules.items():
                print(f"{rid}: {text}")
        else:
            print(json.dumps(rules, indent=2, ensure_ascii=False))
    else:
        try:
            validate_rules(rules)
        except RuleError as e:  # T786: machine code + exit 4, never a traceback
            print(f"bouncer: bad rules: {e}", file=sys.stderr)
            return 4
        warns = warn_overlapping(rules)
        # T880: by-name lint excludes the preset itself; a file pack warns
        # against every preset — verbatim preset text means an unedited
        # template, which is exactly what init told the operator to edit
        warns += warn_preset_verbatim(rules, exclude=None if args.rules
                                      else args.preset)
        for w in warns:
            print("warn:", w)
        print(f"pack ok: {len(rules)} rules")
        if warns and getattr(args, "strict", False):  # T319
            return 2
    return 0


def _add_threshold_flags(p) -> None:
    p.add_argument("--threshold", type=float, default=0.85,
                   help="single allow/delete gate threshold (default 0.85)")
    p.add_argument("--allow-threshold", type=float, default=None,
                   help="allow gate threshold; falls back to --threshold when unset")  # T223
    p.add_argument("--delete-threshold", type=float, default=None,
                   help="delete gate threshold; falls back to --threshold when unset")  # T223


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
    if args.workers > 1:  # T939: the scrape sees ONE worker's counters
        print(f"bouncer: --workers {args.workers}: counters, strikes, cache and "
              "/stats//metrics are per-worker process state (no shared store) — "
              "each scrape hits one worker only; keep workers at 1 for exact "
              "numbers, or aggregate per-worker scrapes at the LB (docs/runbook.md)",
              file=sys.stderr)
    kw: dict = {"workers": args.workers}
    keep_alive = getattr(args, "keep_alive", None)  # T838: getattr — callers
    limit = getattr(args, "limit_concurrency", None)  # may build args by hand
    if keep_alive is not None:  # None keeps uvicorn's own default
        kw["timeout_keep_alive"] = keep_alive
    if limit is not None:
        kw["limit_concurrency"] = limit
    uvicorn.run("gatekeeper.serve:app", host=args.host, port=args.port, **kw)
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
                     ("huggingface_hub", "weight downloads"),
                     ("tomli", "TOML configs on python<3.11")):
        present = importlib.util.find_spec(mod) is not None
        detail = "importable" if present else f"missing — {why} unavailable"
        if mod == "tomli" and sys.version_info >= (3, 11):
            present, detail = True, "stdlib tomllib covers 3.11+ (backport for 3.10)"
        note("ok" if present else "warn", "dep", mod, detail)

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
    p.add_argument("--version", action="store_true",
                   help="print the bouncer version and exit")  # T215
    sub = p.add_subparsers(dest="cmd", required=False)
    sub.required = False
    c = sub.add_parser("check")
    c.add_argument("message", nargs="?", default=None,
                   help="text to moderate (or pass --file)")  # T874: or --file
    # T874: one message per line, JSONL out
    c.add_argument("--file", default=None,
                   help="moderate messages one per line from FILE (JSONL output)")
    # T483: None = not passed (conflict check)
    c.add_argument("--rules", default=None,
                   help="rules JSON file (conflicts with --preset; default rules.json)")
    c.add_argument("--preset",
                   help="named preset rules instead of a file (see bouncer presets)")
    _add_threshold_flags(c)
    c.add_argument("--lang", default=None,  # T311
                   help="language hint, or 'auto' to detect from script (T893)")
    c.add_argument("--context", action="append", default=None,
                   help="earlier chat line to condition on (repeatable)")  # T312: repeatable
    # T313: RULE=low|high
    c.add_argument("--severity", action="append", default=None,
                   help="per-rule severity override RULE=low|high (repeatable)")
    c.add_argument("--quiet", action="store_true",
                   help="print only the action word")  # T320: action word only
    # T329: override history_n
    c.add_argument("--history", type=int, default=None,
                   help="override how many recent lines are kept as context")
    c.add_argument("--model", default=None,
                   help="pin a specific model checkpoint")  # T460: pin checkpoint
    c.add_argument("--timeout", type=float, default=None,
                   help="inference time budget in seconds")  # T516: inference budget
    # T531: JSON gate config file
    c.add_argument("--config", default=None,
                   help="JSON gate config file (base; CLI flags override it)")
    c.add_argument("--user", default=None,
                   help="attribute the message to USER for strikes")  # T533: strikes attribution
    c.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON instead of text")
    c.set_defaults(fn=cmd_check)
    s = sub.add_parser("serve")  # T068
    s.add_argument("--host", default="127.0.0.1",
                   help="bind address (default 127.0.0.1)")
    s.add_argument("--port", type=int, default=8000,
                   help="HTTP port (default 8000)")
    s.add_argument("--workers", type=int, default=1,
                   help="uvicorn worker processes (default 1)")  # T322
    s.add_argument("--key-file", default=None,
                   help="read the API key from FILE")  # T547: read API key from a file
    # T549: comma origins, overrides env
    s.add_argument("--cors", default=None,
                   help="comma-separated allowed origins (overrides the env)")
    s.add_argument("--keep-alive", type=float, default=None,  # T838
                   help="uvicorn timeout_keep_alive seconds (default 5)")
    s.add_argument("--limit-concurrency", type=int, default=None,  # T838
                   help="max simultaneous connections (default unlimited)")
    s.set_defaults(fn=_cmd_serve)
    d = sub.add_parser("demo")  # T069
    d.add_argument("--port", type=int, default=7860,
                   help="demo UI port (default 7860)")  # T323
    d.add_argument("--share", action="store_true",
                   help="create a public gradio share link")  # T323
    # T548: default selection on launch
    d.add_argument("--preset", default=None,
                   help="preset selected in the demo on launch")
    d.set_defaults(fn=lambda a: (_demo(a), 0))
    w = sub.add_parser("watch")  # T070+T169: stdin pipe, colored live tail
    w.add_argument("--rules", default=None,
                   help="rules JSON file (conflicts with --preset; default rules.json)")  # T483
    w.add_argument("--preset",
                   help="named preset rules instead of a file (see bouncer presets)")
    w.add_argument("--config", default=None,
                   help="JSON gate config file (same shape as check --config)")  # T532
    # T534: attribute piped lines to one user
    w.add_argument("--user", default=None,
                   help="attribute every piped line to USER for strikes")
    # T535: comma list, e.g. flag,escalate
    w.add_argument("--action", default=None,
                   help="only print these actions, comma list (e.g. flag,escalate)")
    w.add_argument("--lang", default=None,  # T541: hint for the whole pipe,
                   help="or 'auto' to detect per line from script (T893)")
    # T542: per-line {"message","user_id"}
    w.add_argument("--json-in", action="store_true",
                   help='treat each line as {"message","user_id"} JSON (default: raw text)')
    _add_threshold_flags(w)
    w.set_defaults(fn=cmd_watch)
    r = sub.add_parser("review")  # T170
    r.add_argument("--limit", type=int, default=20,
                   help="max rows to list (default 20)")
    r.add_argument("--action", default=None,
                   help="filter rows by action, comma list")  # T317
    r.add_argument("--since", type=float, default=0,
                   help="only rows at or after this epoch time")  # T537: epoch seconds
    r.add_argument("--rule", default=None,
                   help="filter rows by rule name")  # T543
    # T540: drop aged rows
    r.add_argument("--prune", action="store_true",
                   help="drop queue rows older than --older-than, list the rest")
    r.add_argument("--older-than", type=float, default=86400.0,
                   help="age cutoff in seconds for --prune (default 86400)")  # T540: seconds
    r.add_argument("--clear", action="store_true",
                   help="drop the entire queue (requires --yes)")  # T318
    r.add_argument("--yes", action="store_true",
                   help="confirm destructive review actions")  # T318
    r.set_defaults(fn=cmd_review)
    aj = sub.add_parser("adjudicate")  # T865: approve/reject, strike amnesty
    aj.add_argument("row_id",
                    help="queue row id to adjudicate")
    aj.add_argument("verdict", choices=("approve", "reject"),
                    help="approve the row or reject it (grants strike amnesty)")
    aj.set_defaults(fn=cmd_adjudicate)
    am = sub.add_parser("amnesty")  # T881: strike forgiveness, no queue row needed
    am.add_argument("user",
                    help="user whose strikes are reset")
    am.add_argument("--weight", type=int, default=None,
                    help="subtract exactly N strikes (default: clear them all)")
    am.set_defaults(fn=cmd_amnesty)
    cf = sub.add_parser("config")  # T871: standalone config lint
    cf_sub = cf.add_subparsers(dest="cfg_cmd")
    cv = cf_sub.add_parser("validate")  # lint only — no decision, no server
    cv.add_argument("--toml", default=None,
                    help="adapter TOML (default: BOUNCER_CONFIG or bouncer.toml)")
    cv.add_argument("--json", default=None,
                    help="GateConfig JSON (same shape as check --config)")
    cf.set_defaults(fn=cmd_config)
    cv.set_defaults(fn=cmd_config)
    cp = sub.add_parser("completion")  # T875: shell completion script
    cp.add_argument("shell", choices=("bash", "zsh"),
                    help="shell to emit the completion script for")
    cp.set_defaults(fn=cmd_completion)
    md = sub.add_parser("models")  # T538
    md.set_defaults(fn=cmd_models)
    ps = sub.add_parser("presets")  # T539
    ps.set_defaults(fn=cmd_presets)
    st = sub.add_parser("stats")  # T171
    st.add_argument("--json", action="store_true",
                    help="emit stats as JSON")  # T315
    st.set_defaults(fn=cmd_stats)
    ex = sub.add_parser("export")  # T172
    ex.add_argument("--out", default="audit.csv",
                    help="output file (default audit.csv)")
    ex.add_argument("--since", type=float, default=0,
                    help="only rows at or after this epoch time")  # T327: epoch seconds
    ex.add_argument("--stats", default=None,
                    help="stats snapshot JSON to embed in the export")  # T445: snapshot JSON path
    ex.add_argument("--limit", type=int, default=0,
                    help="max rows to export (0 = all)")  # T449: bounded tail export
    ex.add_argument("--format", choices=["csv", "json"], default="csv",
                    help="output format (default csv)")  # T536
    ex.add_argument("--action", default=None,
                    help="rows to export, comma list of actions")  # T544: comma list, e.g. delete
    ex.add_argument("--queue", action="store_true",  # T886: appeal audit trail
                    help="export the review queue (who/why/verdict) instead")
    ex.set_defaults(fn=cmd_export)
    sn = sub.add_parser("snapshot")  # T437+T438
    sn.add_argument("action", choices=["save", "load"],
                    help="save the live snapshot or load it back")
    sn.add_argument("file",
                    help="snapshot file path")
    sn.set_defaults(fn=cmd_snapshot)
    pk = sub.add_parser("pack")  # T173+T174
    pk.add_argument("action", choices=["show", "lint", "init", "diff",
                                       "sign", "verify"],  # T545+T872+T873
                    help="show, lint, init, diff, sign or verify")
    # T545: init target path
    pk.add_argument("file", nargs="?", default=None,
                    help="pack file: init target, sign/verify subject, or diff base")
    pk.add_argument("file2", nargs="?", default=None,
                    help="second pack file for diff (the NEW side)")  # T872: diff NEW
    pk.add_argument("--force", action="store_true",
                    help="overwrite an existing file on init")  # T545: overwrite on init
    pk.add_argument("--preset", default="gaming",
                    help="base preset for show/lint/init (default gaming)")
    pk.add_argument("--rules",
                    help="pack file to show or lint instead of --preset")
    pk.add_argument("--strict", action="store_true",
                    help="exit 2 on warnings instead of 0")  # T319: exit 2 on warnings
    pk.add_argument("--format", choices=["json", "lines"], default="json",
                    help="output format (default json)")  # T325
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
    try:
        return args.fn(args)
    except Exception as e:
        code = getattr(e, "code", None)  # the operator as one coded line,
        if code is None:  # never as a traceback (paths, versions, frames)
            raise
        print(f"bouncer: {code}: {e}", file=sys.stderr)
        return 4


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
