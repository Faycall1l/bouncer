# Architecture (T140, updated T395)

```mermaid
flowchart LR
    msg[chat message] --> norm[normalize: clean, flood, links]
    norm --> fp{fastpath?}
    fp -->|link-rules, no links| allow[allow + stats/audit]
    fp -->|else| cache{cache?}
    cache -->|hit| out[decision]
    cache -->|miss| model[Laya: 5 questions, 1 pass]
    model --> gate{gates: jailbreak, escalate, severity, margin, quiet}
    gate --> out
    out --> audit[audit + stats + strikes + coalescing]
```

Cache key covers every decision input: message, rules, both thresholds,
severity, lang, bounded context, history window, quiet state, gate knobs —
same text under other settings never gets a stale verdict. Cheap paths
(empty/fastpath) and model-failure fallbacks are recorded in stats + audit too.
Gate precedence: `docs/gates.md`.
