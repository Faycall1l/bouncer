# Threat model (T771)

Scope: bouncer as deployed — the HTTP API (`bouncer serve`, including the
`/v1/systemone` passthrough), the CLI, and the files it writes (audit log,
review store, strikes). Non-goals: the caller's product (we moderate its
inputs, we don't secure it), and transport — TLS terminates at your proxy;
bouncer trusts the transport after the key check.

A threat model that hides its gaps is worse than none. Everything "enforced"
below cites the box that enforces it; every known gap cites the box tracking
it (T773–T775) and stays here until that box closes it.

## Assets

| asset | why it matters | class |
|---|---|---|
| API key (`BOUNCER_KEY`) | the only shared secret: possession = moderation authority | secret |
| verdict integrity | a gamed `allow` lets harmful content through; a gamed `delete` censors — either breaks the caller's product | integrity |
| rules / presets | rule text defines what "bad" means: poisoned rules redefine every verdict | integrity |
| audit log (JSONL/CSV) | the evidence trail — tampering erases accountability | integrity |
| review store + strikes | repeat-offer decisions and per-user bans — tampering un-bans users | integrity |
| model checkpoint (~1.8GB) | the weights decide verdicts; a swapped checkpoint is a silent backdoor | supply chain |
| payloads (message, context, state) | end-user conversations flow through this process | confidential (caller's) |
| host CPU / RAM | the process must survive hostile inputs: bombs, floods, nesting | availability |

## Actors

| actor | access | trust |
|---|---|---|
| operator | env, config, filesystem | trusted — sets the key, thresholds, presets |
| API client (key holder) | full API | trusted to *set* rules/thresholds; payload **content** is still end-user text and untrusted |
| anonymous caller (key unset) | full API | untrusted — demo/localhost default; anything internet-facing must set `BOUNCER_KEY` |
| end user | text via the client | fully untrusted — content reaches the model |
| network attacker | on-path | out of scope for the process itself: protect the transport (TLS at the proxy) |
| supply chain (PyPI, HF hub) | deps + checkpoint | semi-trusted — pinned versions, reviewed updates |
| CI runners | repo, workflows | semi-trusted — no secrets on fork PRs, secret-scan (T746), pinned actions |

## Trust boundaries

```
[ end user text ]
      |  (1) untrusted strings: message, context[], state, rules{}
      v
[ API client ] ---(2) X-API-Key: constant-time, 401 (T292), rate
      |                 buckets (T409)--> [ FastAPI serve ]
      |                                    (3) work caps: msg 8000 (T064),
      |                                        context 20 items (T308),
      |                                        batch 32 (T224), body size
      |                                        (T291), model whitelist
      |                                        (T459), timeout (T515/T525)
      v
[ engine moderate ] -- cache (v2: keys) --> router pool --> verdict
      |                window + token budget (T018/T272/T756)
      v  (4) files on disk: audit log, review.jsonl, strikes
```

1. **Payload boundary** — request bodies become Python objects via Pydantic;
   no input is trusted, only *bounded* before use.
2. **Auth boundary** — the key check (and rate limiter) runs before any
   work, on every endpoint, passthrough included (T224).
3. **Work boundary** — every request's work is bounded before it reaches the
   model: message/context/batch/body caps, model whitelist, timeout budget.
4. **Persistence boundary** — verdicts, reviews, and strikes land on disk;
   paths are operator-configured, and the audit trail never contains keys
   or payload echoes in error paths (T292).

## Countermeasures enforced today

| risk | enforced by | box |
|---|---|---|
| key guessing / timing | constant-time compare, 401, `<16`-char boot warning | T292 |
| key material in `ps` / compose files | `serve --key-file` (docker-secrets style) | T547 |
| request floods | rate buckets (≤512), shared by batch + passthrough | T409, T224 |
| oversized messages | 8000-char cap → 413 (single + per batch item) | T064, T309 |
| oversized batch | body-size pre-parse check + ≤32 messages → 413 | T291, T224 |
| unbounded context lists | ≤20 items → `422 E_CONTEXT`; token budget on top | T308, T756 |
| threshold / model abuse | thresholds outside `[0,1]` → 422, `model` whitelist → 422, per-request timeout budget | T223, T459, T515 |
| response leaks | `raw` model output stripped from responses (`_clean`) | — |
| rule-set ambiguity | rules XOR preset, unknown preset → 422 `E_PRESET` | T471, T482 |
| hostile input (random bytes, JSON bombs, lone surrogates) | seeded fuzz over `/predict` proves no 5xx: malformed bodies 400, nesting 422, surrogate text sanitized (message/history) or rejected (`E_RULES_TEXT`) at the engine boundary | T772 |

## Known gaps (tracked, not hidden)

| gap | risk | tracked |
|---|---|---|
| no length cap on `rules` values | rule-text bombs: unbounded strings ride into the prompt | T773 |
| history item cap only on the `/predict` path | `/v1/systemone` forwards `state` raw — no item/length caps on its history | T774 |
| context per-item and dict-key lengths | long items/keys bypass count-based caps | T775 |
| no body-size pre-check on `/predict` | giant bodies are parsed before field caps apply (batch only has T291) | (covered with T775) |

Each row moves into *Countermeasures enforced today* when its box lands —
with the box that enforces it, never a promise.
