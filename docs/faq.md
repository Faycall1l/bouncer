# FAQ (T143)

_(Last checked against v0.4.0.)_

**Why not regex?** Regex can't read new phrasings; bouncer scores meaning in 30ms
and shows a regex baseline side-by-side in the demo so you can see the gap.

**Why not an LLM judge?** Cost and latency: 5 questions in one 33ms pass, $0
self-hosted, vs 5 sequential LLM calls at ~$0.50/1M tokens and seconds of latency.
Use the LLM for the hard escalations, not every message.

**Why not classical BERT?** Fixed label sets. Every server has different rules;
classical needs retraining per community. Here rules are just text in the request.

**Is it calibrated?** Base Laya ships overconfident (ECE ~0.2); temperature refit
on your data brings ~0.08. Never trust raw conf — use gates + margin abstention.

**NSFW/CSAM?** This tool flags; it does not replace human review or platform
reporting flows for illegal content. Escalate, don't automate, high-stakes calls.

**Why split allow/delete thresholds?** (T406) Precision needs differ: a false
allow (missed spam) costs less than a false delete (censored user). Set delete
high (0.9) and allow lower (0.8) to auto-allow the obvious while only deleting
the certain.

**Why is batch capped at 32?** (T406) One request = one chunked loop over a
shared Router; unbounded batches let a single caller hog inference and blow
padding memory. 32 keeps p95 fair for everyone behind the rate limiter.

**Can cached decisions go stale?** (T406) No — since T221 the key covers every
decision input (both thresholds, lang, context, quiet state, gate knobs). Same
text under different settings recomputes instead of reusing.

**My counters reset on restart — how do I restore them?** (T600) Save before the
restart: `bouncer snapshot save snap.json`, then `bouncer snapshot load snap.json`
after. It restores decision counters and per-user strikes; version mismatches
warn but never fail, corrupt files raise `E_SNAPSHOT`. Snapshots hold counts
only, never message content.

**The breaker says `breaker-open` — what do I do?** (T600) The model failed
`breaker_n` times in a row (crash, OOM, bad device) and requests are now
short-circuiting to `escalate` instead of waiting for timeouts. Check the model
process/device, then either wait out `breaker_cool_s` (a half-open probe
recovers automatically) or restart the server. To disable the guard entirely
(not recommended): `BOUNCER_BREAKER=off`.

**Which model checkpoint should I use?** (T600) Default (`model=None`) is right
for most: it routes by language hint, pinning `multilingual` for non-latin
scripts. Pin explicitly only to compare behavior (`english` for
English-only communities, `typed-decisions` for the Jev-style checkpoint). The
pool caches every checkpoint you touch, so pinning costs memory × slots — size
`BOUNCER_POOL_MAX` accordingly. Note: base zero-shot accuracy is modest
(regex baseline 0.403 vs model 0.305 on our template data) — the Kaggle
fine-tune is the path to production quality.

Terms used here are defined in the [Glossary](glossary.md).
