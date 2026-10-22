# Ops runbook (T789)

_(Last checked against v0.5.0.)_

Backup, restore, rotate, drain — the four procedures an operator needs at
3am. Everything here is a file or a command that actually ships; T-boxes
cite where the behavior is pinned.

## Backup

State lives in four places (paths are yours; defaults shown):

| what | default path | written by | notes |
|---|---|---|---|
| audit log | `bouncer-audit.jsonl` (`BOUNCER_AUDIT`) | every decision | hashes only, never text (T273); append-only |
| review queue | `review-queue.jsonl` (`BOUNCER_REVIEW`) | flags/escalations | raw text ≤500 chars/row, file is 0600 (T784) |
| counters + strikes + cache | any path you pick | `bouncer snapshot save FILE` | 0600 via the atomic writer (T783); the cache section holds live entries only (T877) |

The audit log is append-only, so a plain copy is a consistent snapshot:

```bash
cp -a bouncer-audit.jsonl "audit-$(date +%F-%H%M).jsonl"
bouncer snapshot save snap-$(date +%F).json
```

The live file is not the whole trail: at 5MB (T030) it rotates, keeping
exactly two generations — `bouncer-audit.jsonl.1` and `.2` (T987). A
backup that copies only the live file misses the older decisions:

```bash
cp -a bouncer-audit.jsonl* "audit-$(date +%F-%H%M)/"   # live + .1 + .2
```

Honest scope: counters, strikes and the cache live in process memory (per
worker), so `snapshot save` sees what *that* process accumulated — with
the default `--workers 1` (T322) that's everything; with more workers,
save from the one that serves the traffic you care about. `/stats` and
`/metrics` have the same scope (T939): each scrape is answered by one
worker only, so the numbers under-report a multi-worker fleet; `bouncer
serve --workers >1` prints this warning at startup.

## Restore

* **counters + strikes + cache**: `bouncer snapshot load FILE`. An unknown schema
  version (`v` not 1 or 2) refuses with `E_SNAPSHOT` (T438+T876) —
  nothing is half-applied, and a malformed cache section refuses the same
  way before anything is applied (T877). A v1 snapshot from an older bouncer migrates
  in memory to v2 and the load line says so; its stats section rides the
  same migration (v1 predates the per-adapter counters, T867). A snapshot
  from a *different bouncer version* warns on
  stderr and restores best-effort (T449); strikes merge taking the max of
  old and new, so a restore never downgrades a standing ban.
* **audit log / review queue**: they're plain JSONL — `cp` them back to
  the env-var paths and keep the mode at 0600.
* The cache section restores still-fresh entries and prunes expired ones
  at load time (T877); a snapshot with no cache section (v1, or saved
  before T877) restores an empty cache that repopulates on the next
  decisions.

## Rotate (API key)

The full runbook (including the timing-safe compare notes) is in
[SECURITY.md](SECURITY.md) under *Key rotation — two-key window*. The short
version — the two-key window means no client deadline:

1. `export BOUNCER_KEY_OLD="$BOUNCER_KEY"` — the old key keeps working
   (constant-time compare, T776).
2. Set the new `BOUNCER_KEY` (≥16 chars or boot warns), restart serve.
3. Migrate clients at your own pace; both keys validate meanwhile.
4. Unset `BOUNCER_KEY_OLD`, restart — window closed in one step.

## Scrape + alerts (T946)

`/metrics` is Prometheus text (exposed to loopback, or with `X-API-Key`
once `BOUNCER_KEY` is set — T778 gates the route; send the key as the
`X-API-Key` header, and T945 documents every family):

```yaml
scrape_configs:
  - job_name: bouncer
    metrics_path: /metrics
    static_configs:
      - targets: ["127.0.0.1:8000"]
    # with BOUNCER_KEY set (loopback still exempts a local Prometheus):
    # headers:
    #   X-API-Key: <key>
```

Three alerts cover the failure modes this runbook's other procedures
exist for:

```yaml
groups:
  - name: bouncer
    rules:
      - alert: BouncerBreakerOpen
        expr: bouncer_breaker_open == 1
        for: 2m
        labels: {severity: page}
        annotations:
          summary: "model failures tripped the breaker — decisions are escalating"
      - alert: BouncerModelFails
        expr: increase(bouncer_breaker_fails[10m]) > 5
        labels: {severity: ticket}
        annotations:
          summary: "breaker-eligible failures climbing before it opens"
      - alert: BouncerReviewBacklog
        expr: bouncer_review_queue_depth > 100
        for: 30m
        labels: {severity: ticket}
        annotations:
          summary: "escalations piling up unseen — the queue is not a discard bin"
```

Notes that keep these honest:

* **Per worker, not per fleet** (T939): with `--workers N` each process
  holds its own counters and each scrape lands on one of them, so a
  dashboard sums across targets; the startup warning says this out loud.
* **`_other` is a fold, not a rule** (T942): past 200 distinct rule ids
  new ones count under `rule="_other"` — an alert on a *specific* rule id
  misses that traffic by design, so alert on families, not on rule labels.
* **A reset is a counter reset**, not a crash: `rate()`/`increase()`
  handle restarts; `bouncer_uptime_seconds` dropping is the restart tell.
* The queue-depth alert fires on *depth*, never on message text — the
  queue holds raw text by design (T784); the metric counts bytes, not
  content (T940).

## Drain

The procedure below is the one an operator follows at 3am (T988
re-verified it end-to-end against the P51 surface — ready check, forced
exit, snapshot, hand-drain of the queue).

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
   **Drain vs force (T978):** the drain is an unbounded wait by design —
   the same unboundedness the interpreter already applies to non-daemon
   threads at exit — so a wedged predict means SIGTERM alone won't exit
   the process. After one timeout window, force it: a second signal, then
   `SIGKILL` if the second signal was also swallowed. Forcing is
   data-safe — every audit row is flushed to the OS per write (T758), so
   the worst a force-kill costs is the fsync batching window, never a
   flushed row. The `inference_drained_s` shutdown line prints only when
   the drain *completed*; its absence is how you know the force path ran.
3. `bouncer snapshot save` before the process exits, then stop it.
4. The review queue drains by hand: `bouncer review` to list (rows carry
   cause/model/preset adjudication context, T882), adjudicate
   out-of-band, then `bouncer review --clear --yes` (T318) — `--clear`
   without `--yes` refuses, because it drops the whole queue. A rejected
   row amnesties that user's strikes by the row's weight (T865); for an
   appeal decided off the queue entirely, `bouncer amnesty USER` clears
   the user's strikes directly (T881, `--weight N` subtracts N).

## Amnesty (strikes forgiveness)

The forgiveness procedure, as it stands after the P51 audit (T988).
Two paths give strikes back — both operator-only on the CLI (no HTTP
surface, T973/T974), both audited:

1. **Off a rejected row** — `bouncer adjudicate ROW_ID reject` (T865):
   the row's user loses exactly the weight that verdict accrued
   (delete → 2, flag → 1, escalate → 0), recorded on the row itself as
   `verdict`/`vt`/`after`.
2. **Direct** — `bouncer amnesty USER [--weight N]` (T881/T974): clears
   everything by default, subtracts exactly N with `--weight`. A
   successful run writes one audit row — who as the 16-hex hash (the
   audit stays hash-only, T029/T883), when = the row's `t`, why =
   `weight=N strikes A->B`. No strikes → exit 1, nothing written.

```bash
bouncer review                 # find the row and its user (0600 file)
bouncer adjudicate <row_id> reject   # in-row amnesty, or:
bouncer amnesty "discord:42" --weight 2   # direct, audited (T974)
```

A plain `bouncer amnesty USER` (no `--weight`) clears the whole count —
use it after an appeal is upheld; use `--weight` to give back only what
one mistaken verdict added. The strikes table itself is 0600 (T783) and
amnesty never touches the review queue: rows stay for the record, the
table's count drops.
