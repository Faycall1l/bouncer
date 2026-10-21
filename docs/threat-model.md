# Threat model (T771)

_(Last checked against v0.4.0.)_
_(Refreshed for the 0.5.x surface — T971: stream body cap, typed
systemone shape, appeal/adjudicate flow, namespaced strikes.)_

Scope: bouncer as deployed — the HTTP API (`bouncer serve`, including the
`/v1/systemone` passthrough), the CLI, and the files it writes (audit log,
review store, strikes). Non-goals: the caller's product (we moderate its
inputs, we don't secure it), and transport — TLS terminates at your proxy;
bouncer trusts the transport after the key check.

A threat model that hides its gaps is worse than none. Everything "enforced"
below cites the box that enforces it; every known gap cites the box tracking
it and stays here until that box closes it. Current set: none — T772–T775
each opened with a row here and moved up when it landed.

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

```text
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
| request floods | rate buckets (≤512), shared by batch + passthrough; per-client keying reads `X-Forwarded-For` only from a `BOUNCER_TRUSTED_PROXY` peer (rightmost hop), so spoofed headers can't split buckets — rotation, fake-prefix and full-chain attacks all hit the same wall | T409, T224, T777, T782 |
| oversized messages | 8000-char cap → 413 (single + per batch item) | T064, T309 |
| oversized batch | body-size pre-parse check + ≤32 messages → 413 | T291, T224 |
| unbounded context lists | ≤20 items → `422 E_CONTEXT`; token budget on top | T308, T756 |
| threshold / model abuse | thresholds outside `[0,1]` → 422, `model` whitelist → 422, per-request timeout budget | T223, T459, T515 |
| response leaks | `raw` model output stripped from responses (`_clean`); every error response is a machine code + fixed message — a sweep pins that no failure body or header carries an install path, a version, or a traceback (exception text with a planted internal path dies at `E_INTERNAL`), and the CLI converts known error CLASSES into one-line `bouncer: E_*` exits instead of tracebacks | T787 |
| rule-set ambiguity | rules XOR preset, unknown preset → 422 `E_PRESET` | T471, T482 |
| hostile input (random bytes, JSON bombs, lone surrogates) | seeded fuzz over `/predict` proves no 5xx: malformed bodies 400, nesting 422, surrogate text sanitized (message/history) or rejected (`E_RULES_TEXT`) at the engine boundary | T772 |
| rule-set bombs (oversized value/id/count) | `validate_rules` rejects >280-char values (`E_RULES_TEXT`), non-slug ids >24 chars (`E_RULES_ID`), >12 rules (`E_RULES_COUNT`) — was already enforced, now pinned end-to-end and documented; `pack lint` also refuses hostile pack *documents* (path-looking ids, NUL/bidi/format-string ids, non-mapping or 300-deep JSON, missing file) with machine codes and exit 4, never a traceback | T004–T006, T773, T786 |
| rule-pack tampering in transit or at rest | `pack sign FILE` writes a sha256 manifest beside the pack; `pack verify` recomputes it — a flipped byte fails with `E_PACK_SIG` and a machine-code exit, so a poisoned rules file (an integrity asset above) is caught before it redefines verdicts | T873, T888 |
| rushed rotation = leaked old key | two-key window: `BOUNCER_KEY_OLD` accepted constant-time beside the new key — clients migrate with no deadline, closing the window kills the old key in one step; both compares always run | T776 |
| metrics intel leak (traffic, breaker, cache) | `/metrics` needs `BOUNCER_KEY` off-box the moment a key exists; `/stats` rides the same gate (T842) — and what both expose is aggregates only: counts by action/rule/adapter, causes, p95, strike **totals** (T884/T885), never user ids (T439) or payload text; loopback-without-forwarding stays free; the socket peer is unspoofable — a forwarding header can only lose the local exemption, never gain it | T778, T842, T884, T885 |
| log/terminal injection (CWE-117) | log lines are `json.dumps` (fixed keys, escaped values); `X-Request-ID` scrubbed before echo+log; reasons scrubbed at the source in `explain()`; watch previews and error lines scrubbed | T779 |
| public demo discloses rules/messages | `bouncer demo --share` prints a structured `{"warn"}` at launch — before gradio loads or the port binds; docs tell operators a shared link is full disclosure (rulebook, messages, review rows) | T780 |
| vulnerable dependency ships | CI `audit` job runs pip-audit over the versions pip resolves from pyproject on **every push** — a known CVE turns the build red before anything ships | T781 |
| forwarder as internal scanner (SSRF) | `forward()` refuses non-http(s) schemes before any socket opens; opt-in `BOUNCER_FORWARD_ALLOW` pins exact destination hosts (case-insensitive, no subdomain wildcards) | T785 |
| unbounded history on the raw path | `/v1/systemone` trims `state.history` to the newest 20 items server-side before forwarding — same window as `/predict`'s context (T308); under-cap and non-list states pass through untouched | T774 |
| context item / dict-key / body-size bounds | context items ≤ 8000 chars → 422 `E_CONTEXT` (structured path **rejects**); `/v1/systemone`'s wire shape is typed since T832 (non-object `state`/`questions` → 422 at the door instead of a forwarded 500 — contents stay the router's to bound), its `state`/`questions` keys ≤ 64 → 422 `E_STATE` and its history items **trim** to 8000 (passthrough precedent from T774); every POST with `Content-Length` > 1 MB → 413 from the request middleware *before* the body is read or parsed (T775); a chunked or lying body that crosses the cap **mid-stream** is cut at the byte level before the handler runs (T831). Both 413s fire **before auth by design**: the reject is for the body's size, so the key check is never spent on a body the server would refuse anyway — an unauthenticated prober learns only the documented 1 MB cap | T832, T775, T831, T843 |
| strikes crossing identities | strike keys are namespaced `platform:user` (T858): a Discord id 42 and a Telegram id 42 are two table entries, so an identity collision on one platform can neither revoke nor inflate another platform's strikes; a payload without a sender accrues to no one (`None` never becomes the literal target), and cached/coalesced verdicts carry only the asking user's strikes — never another row's | T858, T864 |
| appealed verdicts manipulated over the API | adjudication has no HTTP surface at all: approve/reject is `bouncer adjudicate` on the operator's CLI (T865), so no key holder can end an appeal; queue rows carry the namespaced user and the pre-decision strike count as appeal context (T864), and `export --queue` emits the full appeal trail for review | T864, T865, T886 |

## Known gaps (tracked, not hidden)

_None open. Every gap this doc ever carried named its box (T772–T775) and
moved into *Countermeasures* the day that box landed — the next gap starts
the same way: a risk row here, a box in TODO.md, no promises without one._

_Re-audited at T972 against every P44–P50 addition (server hardening
T831–T848, adapter depth T851–T870, CLI/rules/storage T871–T890,
multilingual routing T891–T910, fine-tune pipeline T911–T930,
observability T931–T950, refactor T951–T970): each new surface is either
enforced in *Countermeasures* above or has a P51 box (T973–T988) pinning
it there. The two citation gaps the audit itself found are fixed in the
same pass — /stats behind the key (T842) and pack sign/verify (T873) are
now cited rows._
