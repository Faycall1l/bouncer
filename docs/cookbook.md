# Cookbook (T794)

_(Last checked against v0.4.0.)_

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

## 4. Run a multilingual community

```bash
bouncer check "eso es trampa" --preset es     # Spanish pack, language-tagged
bouncer check "هذا غش" --preset ar            # non-latin script → multilingual checkpoint
bouncer presets                               # es, fr, ar + the English packs
```

* Presets carry a language tag (`PRESET_LANG`): picking `es`/`fr`/`ar`
  also hints the downstream language (reason language, model routing).
* `--lang TAG` overrides or sets the hint explicitly (the CLI notes a
  preset/hint mismatch instead of silently disagreeing).
* Routing is automatic from there: non-latin scripts (ar/zh/ru/fa/ur/he)
  pin the `multilingual` checkpoint, latin rides laya's own auto-routing.
  Pin a checkpoint per request with `model=...` when you want to overrule.
* `bouncer pack init FILE --preset gaming` exports any pack as editable
  JSON — translate the rule *texts*, keep the ids slugs, ship it back with
  `--rules FILE`. Ids stay language-neutral on purpose (they're machine
  keys, and `E_RULES_ID` enforces it). `bouncer pack diff OLD NEW` lists
  what changed between two packs (`+` added, `-` removed, `~` changed,
  one rule per line) and exits 2 on drift, so a CI job can gate on it
  (T872).

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

Terms used here are defined in the [Glossary](glossary.md).
