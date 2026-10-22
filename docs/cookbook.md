# Cookbook (T794)

_(Last checked against v0.5.0.)_

Five copy-paste recipes. Each one is a complete loop — the linked pages
hold the full contracts. Finished scripts you can lift verbatim:
[01 in-process](examples/01_in_process.py) ·
[02 API client](examples/02_api_client.py) ·
[03 custom rules](examples/03_custom_rules.py).

## 1. Moderate a Discord server

```bash
pip install -e ".[server,discord]"
export DISCORD_TOKEN="your-bot-token"        # env only, never in code
export BOUNCER_DRY_RUN=1                     # phase 1: print decisions, change nothing
python -m gatekeeper.adapters.discord_bot
```

Watch the output with your real traffic first; when the verdicts look
right, drop the `BOUNCER_DRY_RUN` line and restart — from then on delete/
flag actions are performed. The adapter loads rules from a preset or your
own pack, redacts tokens from every outbound line, and shuts down cleanly
on SIGTERM. All platforms (Twitch, Telegram, Matrix, Mattermost, Zulip,
Slack events) and the shared config file (`bouncer.toml`) are documented
in [the adapters README](https://github.com/Faycall1l/bouncer/blob/main/src/gatekeeper/adapters/README.md).

## 2. Self-host the API

```bash
cp .env.example .env
echo "BOUNCER_KEY=$(python -c 'import secrets; print(secrets.token_hex(16))')" >> .env
docker compose up -d
```

Compose runs two services from the same image: `server` on **:8000** and
the `demo` UI on **:7860**. Secrets never live in `compose.yaml` — it
interpolates `BOUNCER_KEY` from `.env` (gitignored; the last value in the
file wins, which is why appending is safe). Two named volumes do
the persistence: `hf-cache` (checkpoint weights, so restarts don't
re-download) and `snapshots` (`bouncer snapshot save` lands in
`/app/snapshots`). Both dirs are pre-created as the non-root `bouncer`
user.

Without Docker it's the same two lines:

```bash
pip install -e ".[server]"
BOUNCER_KEY=... bouncer serve                # :8000
```

Put TLS and a reverse proxy in front for anything public; rate limiting
(60/min per IP) and the `/metrics` gate (T778) are built in. Details:
[Security](SECURITY.md), [Runbook](runbook.md).

## 3. Tune the gates for your community

The two bars are independent — a gaming clip channel and a support inbox
shouldn't share them:

```bash
# strict auto-allow, lazy delete: humans see more, machines delete less
bouncer check "$MSG" --preset gaming --allow-threshold 0.9 --delete-threshold 0.6
```

* **Allow gate** up → fewer auto-allows, more escalations to humans.
* **Delete gate** down → more automatic deletes — only when you trust the
  rule pack.
* Bare `--threshold` sets both (that's the default 0.85).

The same two keys exist as JSON fields on `POST /predict` and
`/predict/batch` (`allow_threshold` / `delete_threshold`), so a service
can tune per route. Strikes ride on top: after `BOUNCER_BAN_AT` strikes
(default 3) bouncer *suggests* a ban — the action stays yours. Verify any
gate change against your own messages with `bouncer check` in a loop, or
run the repo's `eval/gate.py` harness before shipping numbers you'd have
to defend. Full reference: [gates.md](gates.md) and
[thresholds.md](thresholds.md).

## 4. Run a multilingual community (recipe T899)

```bash
bouncer check "eso es trampa" --preset es     # Spanish pack, language-tagged
bouncer check "هذا غش" --preset ar            # non-latin script → multilingual checkpoint
bouncer presets                               # es, fr, ar + the English packs
bouncer check "هذا غش" --rules my-rules.json --lang auto   # no pack: detect the hint
```

The full recipe, in the order bouncer applies it:

* **Pack tags** — presets carry a language tag (`PRESET_LANG`): picking
  `es`/`fr`/`ar` also hints the downstream language (reason language, model
  routing). Every routed language either has a pack or is listed packless
  (`lang_coverage()` + [presets.md](presets.md): zh/ru/fa/ur/he ride the
  multilingual checkpoint with your own rules).
* **Explicit hint** — `--lang TAG` (API `lang=`) overrides everything; the
  CLI notes a preset/hint mismatch instead of silently disagreeing.
* **Script detection** — with no hint, the message's own script fills it:
  `--lang auto` (check/watch, T893) says so explicitly, `/predict` autofills
  per message (T892, batch rows too), and even an unhelpful `lang=` value
  never strands non-latin text on the auto route — routing falls back to
  the detected script (T891). Detection is script-honest, never a language
  claim: latin text stays unhinted and rides laya's auto-routing. Pin a
  checkpoint per request with `model=...` when you want to overrule.
* **Adapters** — platform bots detect per message too, and
  `BOUNCER_ADAPTER_LANG=telegram=ar,zulip=en` (T897) pins the hint per
  platform where detection can't know your deployment; `=auto` unpins one
  platform without clearing the rest.
* **Pool behavior** — every checkpoint touched lands in the shared pool
  (`BOUNCER_POOL_MAX`, default 2), so a mixed community holds english +
  multilingual routers side by side. `GET /stats` → `pool.by_model` (T895)
  counts checkouts per checkpoint: if `evictions` climbs while a language
  is active, that language is thrashing the pool — raise the cap. The
  risk is measured, not folklore: `eval/bench_pool.py`'s `languages`
  section runs english+multilingual alternating (T909) — two slots, zero
  evictions; one slot, a rebuild on every switch. A
  mixed-language batch scores per message (T902), so one Arabic line in an
  English batch doesn't misroute its neighbors.
* **Verify routing** — `python eval/eval_i18n.py` (T898) measures that
  script detection lands each fixture on the right checkpoint, and the gate
  fails on misfires — no model weights needed for that number.
* **`bouncer pack init FILE --preset gaming`** exports any pack as editable
  JSON — a `meta` block (schema version, bouncer version, creation time,
  preset, lang — T878) over the `rules` section. Translate the rule
  *texts*, keep the ids slugs, ship it back with
  `--rules FILE`; every reader also still accepts a bare `{id: text}`
  pack. Ids stay language-neutral on purpose (they're machine
  keys, and `E_RULES_ID` enforces it). `bouncer pack diff OLD NEW` lists
  what changed between two packs (`+` added, `-` removed, `~` changed,
  one rule per line) and exits 2 on drift, so a CI job can gate on it
  (T872). `bouncer pack sign FILE` writes `FILE.sig`, a sha256 manifest
  over the sorted ids+texts, and `bouncer pack verify FILE` recomputes it —
  a changed byte fails with `E_PACK_SIG` (T873).

## 5. Back up (and restore) state

Four files hold everything bouncer remembers — the full procedure,
including restore and per-worker caveats, is in the
[Runbook](runbook.md#backup). The two-command version:

```bash
cp -a bouncer-audit.jsonl "audit-$(date +%F).jsonl"   # append-only log: copy is consistent
bouncer snapshot save snap.json                       # counters + strikes, written 0600
# ...then, on the other side of the disaster:
bouncer snapshot load snap.json                       # schema mismatch refuses cleanly (E_SNAPSHOT)
```

Review queue and audit log are plain JSONL — `cp` them back to the paths
`BOUNCER_REVIEW`/`BOUNCER_AUDIT` name. Nothing here contains raw message
text except the review queue itself (bounded, 0600, clearable):
[Security § Data handling](SECURITY.md#data-handling).

## 6. Score a whole batch in one request (recipe T997)

```bash
curl -s localhost:8000/predict/batch \
  -H 'content-type: application/json' \
  -d '{"preset": "gaming",
       "messages": ["nice play", "kys noob", "gg wp"]}' \
  | jq -r '.[] | .action'      # one decision per message, order kept
```

* 1–32 messages per call (else 422/413), each ≤ 8000 chars; the array
  comes back in the same order, so results zip back by index.
* `rules`/`preset` are the same XOR as `/predict`; a preset autofills
  its pack's language (T502), and with neither, **each row autofills
  from its own script** (T902) — one Arabic line in an English batch
  doesn't misroute its neighbors.
* One `timeout_s` (or `BOUNCER_TIMEOUT`) bounds the **whole batch**
  (T837): rows that don't start before the deadline come back as
  escalate fallbacks (cause `batch-deadline`) — a slow model costs one
  budget, never `messages × 60 s`.
* Auth and rate limits are shared with `/predict` — one key, one
  bucket. An empty `messages` list is `422 E_BATCH_EMPTY`. Bigger
  scale-out is just sharded ≤32-row calls.

## 7. Work an appeal (recipe T997)

```bash
bouncer review --limit 50 --since "$(date -v-1d +%s)"  # GNU date: -d '1 day ago'
bouncer adjudicate ROW1234 approve   # the row was fine — no further strikes
bouncer adjudicate ROW1235 reject    # the row stood — strike amnesty granted
bouncer amnesty @user42 --weight 1   # no queue row needed: subtract exactly 1 (T974)
bouncer export --queue --out appeals.csv   # the whole trail, verdicts included
```

* Queue rows carry ids (T864); `adjudicate ROW_ID approve|reject` (T865)
  is the whole verdict. Reject grants strike amnesty with the weighted
  shape — delete wipes 2, flag 1, escalate 0 (T783).
* `amnesty USER [--weight N]` (T881) forgives without a queue row;
  both paths write one audit row — who, when, why (T988). The full
  moderator procedure, including rotation and drain interplay, is
  [Runbook § Amnesty](runbook.md#amnesty-strikes-forgiveness).
* `export --queue` is the appeal audit trail for a CSV tool: who was
  flagged, with cause/model/preset context, and how it was adjudicated.
  Queue text stays raw there — that file carries the queue's `0600`
  contract (T784).
* On the chat platforms, users type the `APPEAL` command (T864) and
  see the newest verdict rendered with its queue-row id — this recipe
  is the moderator side of that loop.

## 8. Scrape metrics into Prometheus (recipe T997)

```yaml
# prometheus.yml
scrape_configs:
  - job_name: bouncer
    metrics_path: /metrics
    static_configs:
      - targets: ["localhost:8000"]   # add -X-API-Key header below if BOUNCER_KEY is set
```

```bash
curl -s localhost:8000/metrics | head        # exactly what Prometheus sees
curl -s -H "X-API-Key: $KEY" host:8000/metrics   # the same gate as /stats (T778)
```

* `/metrics` is Prometheus text — open on loopback, `X-API-Key` once
  `BOUNCER_KEY` is set. The full family table lives in
  [api.md § Metrics export](api.md#metrics-export-t945).
* Cardinality is a constant, not a function of traffic (T942–T944):
  rule labels fold into `_other` past 200, so a scraper can't be
  cardinality-bombed through rule ids.
* Counters are **per worker process** (T939): `--workers N` under-reports
  every scrape by N — scrape each worker or keep one worker for honest
  totals.
* Useful alarms: `bouncer_breaker_open == 1` (model down),
  `bouncer_latency_p95_ms` climbing (rolling 200-request window, T884),
  `bouncer_ban_suggested` rising (strike pressure — counts only, never
  user ids).

## 9. Sign and verify a rules pack (recipe T997)

```bash
bouncer pack init my-rules.json      # optional: add the meta block (T878)
bouncer pack lint my-rules.json      # local lint before shipping
bouncer pack sign my-rules.json      # writes my-rules.json.sig — sha256 over sorted ids+texts
bouncer pack verify my-rules.json    # recomputes it; drift fails closed (E_PACK_SIG)
```

* Ship `FILE` and `FILE.sig` together; verify recomputes the manifest
  from the pack's own bytes — one changed byte fails (T873). Exit 4
  when the manifest is missing or unreadable, exit 2 on a mismatch
  (that's CI-gate territory).
* For drift *reporting* between two pack versions,
  `bouncer pack diff OLD NEW` prints `+`/`-`/`~` per rule and exits 2
  on any change (T872) — diff answers "what changed", verify answers
  "is this exactly what was signed".
* The signature is integrity, not authorship: distribute `FILE.sig`
  over a channel your deployment already trusts (the repo, the release
  artifact), and let every reader's `verify` refuse tampered copies.

Terms used here are defined in the [Glossary](glossary.md).
