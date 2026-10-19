# Ops runbook (T789)

_(Last checked against v0.4.0.)_

Backup, restore, rotate, drain — the four procedures an operator needs at
3am. Everything here is a file or a command that actually ships; T-boxes
cite where the behavior is pinned.

## Backup

State lives in four places (paths are yours; defaults shown):

| what | default path | written by | notes |
|---|---|---|---|
| audit log | `bouncer-audit.jsonl` (`BOUNCER_AUDIT`) | every decision | hashes only, never text (T273); append-only |
| review queue | `review-queue.jsonl` (`BOUNCER_REVIEW`) | flags/escalations | raw text ≤500 chars/row, file is 0600 (T784) |
| counters + strikes | any path you pick | `bouncer snapshot save FILE` | 0600 via the atomic writer (T783) |
| decision cache | in-process | — | not backed up; it rebuilds itself |

The audit log is append-only, so a plain copy is a consistent snapshot:

```bash
cp -a bouncer-audit.jsonl "audit-$(date +%F-%H%M).jsonl"
bouncer snapshot save snap-$(date +%F).json
```

Honest scope: counters and strikes live in process memory (per worker), so
`snapshot save` sees what *that* process accumulated — with the default
`--workers 1` (T322) that's everything; with more workers, save from the
one that serves the traffic you care about.

## Restore

* **counters + strikes**: `bouncer snapshot load FILE`. An unknown schema
  version (`v` not 1 or 2) refuses with `E_SNAPSHOT` (T438+T876) —
  nothing is half-applied. A v1 snapshot from an older bouncer migrates
  in memory to v2 and the load line says so; its stats section rides the
  same migration (v1 predates the per-adapter counters, T867). A snapshot
  from a *different bouncer version* warns on
  stderr and restores best-effort (T449); strikes merge taking the max of
  old and new, so a restore never downgrades a standing ban.
* **audit log / review queue**: they're plain JSONL — `cp` them back to
  the env-var paths and keep the mode at 0600.
* After a restore the cache is empty and repopulates on the next decisions.

## Rotate (API key)

The full runbook (including the timing-safe compare notes) is in
[SECURITY.md](SECURITY.md) under *Key rotation — two-key window*. The short
version — the two-key window means no client deadline:

1. `export BOUNCER_KEY_OLD="$BOUNCER_KEY"` — the old key keeps working
   (constant-time compare, T776).
2. Set the new `BOUNCER_KEY` (≥16 chars or boot warns), restart serve.
3. Migrate clients at your own pace; both keys validate meanwhile.
4. Unset `BOUNCER_KEY_OLD`, restart — window closed in one step.

## Drain

1. Pull the instance out of the load balancer. `/ready` reports
   `{"ready": false, ...}` when the router can't load (T518) — check the
   body, not the status code.
2. Let in-flight requests finish: uvicorn completes open requests on
   SIGTERM; serve enforces its own per-request timeouts (`E_TIMEOUT`), so
   one timeout window is a safe wait. On shutdown the lifespan drains the
   inference pool (a timed-out predict keeps running in its thread — this
   waits for it) and fsyncs+closes the audit tail before the process goes;
   the last log line reports both: `{"event": "shutdown",
   "inference_drained_s": ..., "audit": "closed"}` (T839).
3. `bouncer snapshot save` before the process exits, then stop it.
4. The review queue drains by hand: `bouncer review` to list, adjudicate
   out-of-band, then `bouncer review --clear --yes` (T318) — `--clear`
   without `--yes` refuses, because it drops the whole queue.
