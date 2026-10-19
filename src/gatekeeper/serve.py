# Apache-2.0. See LICENSE.
"""FastAPI: /predict + Jev-compatible /v1/systemone passthrough."""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware  # T055
from pydantic import BaseModel
from starlette.middleware.gzip import GZipMiddleware  # T284

from . import __version__, get_router, moderate


@asynccontextmanager
async def _lifespan(app: FastAPI):  # T226: lifespan replaces deprecated on_event
    try:  # T059+T177: preload + warmup; weights may be absent at boot
        r = get_router()
        r.predict({"message": "warmup"}, {"q": {"type": "noul", "instructions": "warmup?"}})
    except Exception as e:  # noqa: BLE001 — first real call loads instead
        print(f"warmup skipped: {e}", flush=True)
    yield  # T839: the shutdown note below used to be ALL this was — now we
    # actually drain the inference pool (a timed-out predict keeps running in
    # its thread) and fsync+close the audit tail before the process goes.
    from . import audit, drain_inference
    drained_s = drain_inference()
    audit.close()
    import json as _json
    print(_json.dumps({"event": "shutdown", "inference_drained_s": round(drained_s, 3),
                       "audit": "closed"}), flush=True)


def _cors_origins() -> list:
    """T303: comma-separated origins, default open (demo-friendly)."""
    raw = __import__("os").environ.get("BOUNCER_CORS", "*").strip()
    return [o.strip() for o in raw.split(",") if o.strip()] or ["*"]


app = FastAPI(title="bouncer", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins(), allow_methods=["*"],
                   allow_headers=["*"])  # T055: demo-friendly
app.add_middleware(GZipMiddleware, minimum_size=1000)  # T284


class _BodyTooLarge(Exception):  # T831: raised inside the wrapped receive
    """Marker: the real byte count crossed MAX_BODY mid-stream."""


class _StreamBodyCap:  # T831: byte-level cap — Content-Length is client-trust
    """T775's check reads the Content-Length HEADER, so a chunked POST (no
    header at all) or a lying one slips past untouched. This middleware
    wraps receive and counts actual body bytes; past the cap it raises
    _BodyTooLarge inside the body read — before the handler runs and
    before any response starts — and answers the same 413 as the header
    path. Sits under _mw so the access log and X-Request-ID still see it."""

    def __init__(self, app, limit: int | None = None):
        self.app = app
        self.limit = limit  # None = MAX_BODY at call time (defined later)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        limit = self.limit if self.limit is not None else MAX_BODY
        total = 0
        started = False

        async def _send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        async def counting_receive():
            nonlocal total
            message = await receive()
            if message.get("type") == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, counting_receive, _send)
        except _BodyTooLarge:
            if started:  # response already streaming — nothing honest to do
                raise
            body = b'{"detail": "body too large"}'
            await send({"type": "http.response.start", "status": 413,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})


app.add_middleware(_StreamBodyCap)  # T831: under _mw, over the routes
_START = time.time()

_KEY = __import__("os").environ.get("BOUNCER_KEY", "")  # T053: optional shared key
_KEY_OLD = __import__("os").environ.get("BOUNCER_KEY_OLD", "")  # T776: rotation window
if 0 < len(_KEY) < 16:  # T292: short keys fall to guessing; warn loudly, still enforce
    print('{"warn": "BOUNCER_KEY shorter than 16 chars"}', flush=True)
if 0 < len(_KEY_OLD) < 16:  # T776: the outgoing key deserves the same warning
    print('{"warn": "BOUNCER_KEY_OLD shorter than 16 chars"}', flush=True)

_BUCKETS: dict = {}  # T054: >60 req/min per IP -> 429


def _sweep(now: float) -> None:
    """T227: evict idle IPs so the bucket map can't grow without bound."""
    if len(_BUCKETS) > 512:
        for ip, hits in list(_BUCKETS.items()):
            if not hits or now - hits[-1] > 120:
                del _BUCKETS[ip]


_TRUSTED = [s.strip() for s in __import__("os").environ.get(  # T777: peers whose
    "BOUNCER_TRUSTED_PROXY", "").split(",") if s.strip()]  # forwarding headers we believe


def _client_ip(request) -> str:
    """T777: socket peer — unless that peer is a trusted proxy, in which
    case the RIGHTMOST X-Forwarded-For hop (what our proxy appended;
    anything the client sent itself sits further left and never counts)."""
    ip = request.client.host if request.client else "?"
    if _TRUSTED and ip in _TRUSTED:
        xff = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if xff:
            return xff
    return ip


def _rate(request: Request) -> None:
    if request is None:
        return
    ip = _client_ip(request)
    now = time.time()
    _sweep(now)  # T227
    hits = [t for t in _BUCKETS.get(ip, []) if now - t < 60]
    hits.append(now)
    _BUCKETS[ip] = hits[-60:]
    if len(hits) > 60:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="rate limited",
                            headers={"Retry-After": "60"})  # T306


def _auth(request) -> None:
    if _KEY:
        import hmac  # T307: constant-time compare blunts timing probes
        # T776: rotation window — the outgoing key stays valid beside the
        # new one so clients migrate with no deadline. `|=` never
        # short-circuits: both compares run, so timing can't say which
        # key was close. Bytes compare: raw header bytes can hold
        # non-ASCII that compare_digest(str) would TypeError on (-> 500).
        got = request.headers.get("X-API-Key", "").encode("utf-8", "replace")
        good = hmac.compare_digest(got, _KEY.encode("utf-8", "replace"))
        if _KEY_OLD:
            good |= hmac.compare_digest(got, _KEY_OLD.encode("utf-8", "replace"))
        if not good:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="bad API key")


def _metrics_gate(request) -> None:  # T778: /metrics is the box's or a key holder's
    """Loopback with no forwarded hop → always. Anyone else → the key.
    Key off the socket peer (unspoofable): an X-Forwarded-For header can
    only *remove* the local exemption (a local proxy forwarded it), never
    grant it. No key configured → open server, open metrics — the same
    bargain as every other route."""
    if not _KEY:
        return
    host = request.client.host if request.client else ""
    local = host == "::1" or host.startswith("127.")
    if local and not request.headers.get("x-forwarded-for"):
        return
    _auth(request)  # 401 unless the key checks out (Prometheus: X-API-Key)


@app.middleware("http")  # T052+T056+T065: request id, access log, latency header
async def _mw(request, call_next):
    import json as _json  # T779: log lines are DUMPED, never interpolated
    import uuid

    from .normalize import strip_controls  # T779: rid scrubbed before echo+log
    rid = strip_controls(request.headers.get("X-Request-ID", "")) or uuid.uuid4().hex[:12]
    request.state.rid = rid  # T840: BEFORE call_next — handlers log against it
    t0 = time.time()
    if request.method == "POST" and _body_too_big(request):  # T775: 413 BEFORE
        from fastapi.responses import JSONResponse  # the body is ever read/parsed
        resp = JSONResponse(status_code=413, content={"detail": "body too large"})
    else:
        resp = await call_next(request)
    ms = (time.time() - t0) * 1000
    resp.headers["X-Request-ID"] = rid
    resp.headers["X-Bouncer-ms"] = f"{ms:.1f}"
    resp.headers["X-Content-Type-Options"] = "nosniff"  # T304
    print(_json.dumps({"rid": rid, "method": request.method,  # T840: method+status
                       "path": request.url.path,  # were missing from the access log
                       "status": resp.status_code,
                       "ms": round(ms, 1)}), flush=True)
    return resp


@app.exception_handler(Exception)  # T269: structured 500, no traceback to clients
async def _internal(request: Request, exc: Exception):
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    if isinstance(exc, HTTPException):  # T269: HTTP errors keep status + detail
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail},
                            headers=exc.headers)
    import json as _json  # T779: dumped, not interpolated — path can carry %22
    print(_json.dumps({"event": "internal-error", "path": request.url.path,
                       "err": type(exc).__name__}), flush=True)
    return JSONResponse(status_code=500,
                        content={"detail": {"code": "E_INTERNAL",
                                            "message": "internal error"}})


@app.get("/health")  # T046
def health():
    try:
        get_router()
        model = "loaded"
    except Exception:  # noqa: BLE001 — T305: never leak loader internals
        model = "unavailable"
    return {"ok": True, "model": model, "uptime_s": round(time.time() - _START, 1)}


@app.get("/ready")  # T518: readiness for load balancers (model, not just process)
def ready():
    from .pool import POOL  # T519
    try:
        get_router()
        return {"ready": True, "model": "loaded", "pool": POOL.stats()}
    except Exception:  # noqa: BLE001
        return {"ready": False, "model": "unavailable", "pool": POOL.stats()}


@app.get("/version")  # T047
def version():
    return {"name": "bouncer", "version": __version__}


@app.get("/models")  # T048
def models():
    from . import list_presets
    return {"checkpoints": ["english", "multilingual", "typed-decisions"],
            "presets": sorted(list_presets())}


@app.get("/stats")  # T057
def stats():
    from . import coalesce_stats  # T754: joined/total effectiveness
    from . import strikes as _strikes  # T439: counts only, never user ids
    from .cache import CACHE
    from .stats import get_stats
    table = _strikes._strikes
    from . import _BREAKER, _BREAKER_LOCK  # T522
    from .pool import POOL  # T462
    with _BREAKER_LOCK:
        breaker = {"fails": _BREAKER["fails"],
                   "open": time.time() < _BREAKER["open_until"],
                   "half_open": _BREAKER["half_open"]}
    return {"name": "bouncer", "version": __version__,  # T240
            "uptime_s": round(time.time() - _START, 1),
            "decisions": get_stats(), "cache": CACHE.stats(), "pool": POOL.stats(),
            "coalesce": coalesce_stats(),  # T754: joined/total effectiveness
            "breaker": breaker,  # T522
            "strikes": {"users": len(table), "total": sum(table.values()),
                        "ban_suggested": sum(1 for n in table.values()
                                            if n >= _strikes.BAN_AT)}}


@app.get("/presets")  # T058
def presets():
    from . import get_preset, list_presets
    return {n: get_preset(n) for n in list_presets()}


@app.get("/presets/{name}")  # T477+T478
def preset_one(name: str):
    from fastapi import HTTPException

    from . import get_preset, list_presets
    if name not in list_presets():
        raise HTTPException(status_code=404,
                            detail={"code": "E_PRESET",
                                    "message": f"unknown preset {name!r}"})
    return {"name": name, "rules": get_preset(name)}


@app.get("/metrics")  # T178: prometheus-style text
def metrics(request: Request):  # T778: exposure gate before any counters leave
    from fastapi.responses import PlainTextResponse

    _metrics_gate(request)
    from .cache import CACHE
    from .stats import get_stats
    g = get_stats()
    lines = [f'bouncer_decisions_total{{action="{k}"}} {v}' for k, v in g["actions"].items()]
    c = CACHE.stats()  # T235
    tot = c["hits"] + c["misses"]
    lines += [f"bouncer_cache_hits {c['hits']}", f"bouncer_cache_misses {c['misses']}",
              f"bouncer_cache_hit_rate {round(c['hits'] / tot, 3) if tot else 0.0}",
              f"bouncer_latency_p50_ms {g['latency']['p50_ms']}",
              f'bouncer_info{{version="{__version__}"}} 1',  # T236
              f"bouncer_uptime_seconds {round(time.time() - _START, 1)}"]  # T236
    from . import _BREAKER, _BREAKER_LOCK  # T520
    with _BREAKER_LOCK:
        is_open = time.time() < _BREAKER["open_until"]
    lines.append(f"bouncer_breaker_open {int(is_open)}")
    from .pool import POOL  # T628: pool health in the same scrape
    ps = POOL.stats()
    lines += [f"bouncer_pool_size {ps['size']}", f"bouncer_pool_max {ps['max_n']}",
              f"bouncer_pool_hits {ps['hits']}", f"bouncer_pool_creates {ps['creates']}",
              f"bouncer_pool_evictions {ps['evictions']}"]
    return PlainTextResponse("\n".join(lines) + "\n")


class ModReq(BaseModel):
    message: str
    rules: dict[str, str] | None = None  # T471: rules XOR preset
    preset: str | None = None  # T471: server-side pack by name
    context: list[str] = []
    threshold: float = 0.85
    allow_threshold: float | None = None  # T223: split gates; None falls back to threshold
    delete_threshold: float | None = None
    lang: str | None = None
    model: str | None = None  # T459: pin a checkpoint or omit for auto-routing
    timeout_s: float | None = None  # T515: per-request budget (0.5–60s)

    # T835: a typo like "thresold" used to be silently dropped — the request
    # fell back to defaults and the client never learned. Now it's a 422.
    model_config = {"extra": "forbid",  # T835
                    "json_schema_extra": {"examples": [  # T063
        {"message": "FREE NITRO http://x.gg", "rules": {"no-spam": "no ads or links"},
         "threshold": 0.85}]}}


def _clean(res: dict) -> dict:
    res = dict(res)
    res.pop("raw", None)
    return res


def _resolve_rules(rules: dict | None, preset: str | None) -> tuple[dict, str | None]:
    """T472+T476: exactly one of rules/preset; unknown presets are 422 E_PRESET."""
    from fastapi import HTTPException

    from . import get_preset, list_presets
    if rules is not None and preset is not None:  # T482: ambiguous source rejected
        raise HTTPException(status_code=422,
                            detail={"code": "E_PRESET",
                                    "message": "pass rules or preset, not both"})
    if preset is not None:
        if preset not in list_presets():  # T476
            raise HTTPException(status_code=422,
                                detail={"code": "E_PRESET",
                                        "message": f"unknown preset {preset!r}"})
        return get_preset(preset), preset
    if rules is not None:
        return rules, None
    default = __import__("os").environ.get("BOUNCER_DEFAULT_PRESET", "")  # T475
    if default:
        if default not in list_presets():
            raise HTTPException(status_code=422,
                                detail={"code": "E_PRESET",
                                        "message": f"bad BOUNCER_DEFAULT_PRESET {default!r}"})
        return get_preset(default), default
    raise HTTPException(status_code=422,
                        detail={"code": "E_PRESET",
                                "message": "pass rules or preset"})


def _thresholds(threshold: float, allow: float | None,
                delete: float | None) -> tuple[float, float]:
    """T223: split gates with back-compat single float; 422 on out-of-range."""
    from fastapi import HTTPException
    a = threshold if allow is None else allow
    d = threshold if delete is None else delete
    for t in (a, d):
        if not 0.0 <= t <= 1.0:
            raise HTTPException(status_code=422, detail="thresholds must be in [0, 1]")
    return a, d


MAX_BATCH = 32  # T224: bound one request's work
MAX_BODY = 1_000_000  # T291: 1MB cap on batch payloads
MAX_CONTEXT = 20  # T308: bound per-request history
MAX_ITEM = 8000  # T775: bound one context/history item (same as a message)
MAX_KEY = 64  # T775: bound dict keys on the raw passthrough
MODELS = ("english", "multilingual", "typed-decisions")  # T459: laya checkpoints


def _check_model(model: str | None) -> None:
    """T459: only real checkpoint names route explicitly."""
    if model is not None and model not in MODELS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422,
                            detail={"code": "E_MODEL_NAME",
                                    "message": f"unknown model {model!r} (pick from {list(MODELS)})"})


def _request_timeout(req_timeout: float | None) -> float:
    """T515+T524: per-request budget, else BOUNCER_TIMEOUT, else 10s. Capped 0.5–60."""
    import os as _os
    if req_timeout is not None:
        if not 0.5 <= req_timeout <= 60:
            from fastapi import HTTPException
            raise HTTPException(status_code=422,
                                detail={"code": "E_TIMEOUT",
                                        "message": "timeout_s must be in [0.5, 60]"})
        return req_timeout
    try:
        return max(0.5, min(60.0, float(_os.environ.get("BOUNCER_TIMEOUT", "10.0"))))
    except (TypeError, ValueError):
        return 10.0


def _check_lang(lang: str | None) -> None:
    """T496: lang hints are short slugs, not sentences."""
    import re as _re
    if lang is not None and not _re.fullmatch(r"[a-z-]{2,16}", lang):
        from fastapi import HTTPException
        raise HTTPException(status_code=422,
                            detail={"code": "E_LANG",
                                    "message": f"bad lang hint {lang!r} (want like 'es', 'fr')"})


def _body_too_big(request: Request, limit: int = MAX_BODY) -> bool:
    """T291: honor Content-Length before parsing a batch body."""
    try:
        return int(request.headers.get("content-length", 0)) > limit
    except (TypeError, ValueError):
        return False


@app.post("/predict")
def predict(req: ModReq, request: Request):
    from fastapi import HTTPException
    _rate(request)
    _auth(request)
    if len(req.message) > 8000:  # T064
        raise HTTPException(status_code=413, detail="message too long")
    if len(req.context) > MAX_CONTEXT:  # T308
        raise HTTPException(status_code=422,
                            detail={"code": "E_CONTEXT",
                                    "message": f"context capped at {MAX_CONTEXT} items"})
    if any(len(c) > MAX_ITEM for c in req.context):  # T775: count caps miss this
        raise HTTPException(status_code=422,
                            detail={"code": "E_CONTEXT",
                                    "message": f"context item capped at {MAX_ITEM} chars"})
    from fastapi import HTTPException

    from .config import GateConfig, questions_knob
    from .explain import explain
    from .rules import RuleError
    allow_t, delete_t = _thresholds(req.threshold, req.allow_threshold, req.delete_threshold)
    _check_model(req.model)  # T459
    _check_lang(req.lang)  # T496
    rules, preset_name = _resolve_rules(req.rules, req.preset)  # T472
    lang = req.lang
    if lang is None and preset_name is not None:  # T502: pack knows its language
        from .presets import preset_lang
        lang = preset_lang(preset_name)
    cfg = GateConfig(allow_threshold=allow_t, delete_threshold=delete_t,
                     timeout_s=_request_timeout(req.timeout_s),  # T515
                     questions=questions_knob())  # T755: BOUNCER_QUESTIONS
    try:
        res = moderate(req.message, rules, req.context, config=cfg,
                       lang=lang, model=req.model)
    except RuleError as e:
        raise HTTPException(status_code=422,  # T256: machine-readable code
                            detail={"code": getattr(e, "code", "E_RULES"),
                                    "message": str(e)})
    res["reason"] = explain(res, rules)
    import json as _json  # T246: decision line for operators (no message text)
    print(_json.dumps({"event": "decision", "rid": getattr(request.state, "rid", ""),  # T840
                       "action": res["action"], "rule": res["rule"],
                       "conf": round(res["confidence"], 3),
                       "preset": preset_name}), flush=True)  # T474
    return _clean(res)


class BatchReq(BaseModel):
    messages: list[str]
    rules: dict[str, str] | None = None  # T473: rules XOR preset
    preset: str | None = None  # T473
    threshold: float = 0.85
    allow_threshold: float | None = None  # T223
    delete_threshold: float | None = None
    lang: str | None = None  # T836: batch rows route like single ones
    model: str | None = None  # T459
    timeout_s: float | None = None  # T515

    model_config = {"extra": "forbid"}  # T835: same typo-blindness as ModReq


@app.post("/predict/batch")  # T050
def predict_batch(req: BatchReq, request: Request):
    from fastapi import HTTPException
    _rate(request)  # T224: batch shares the same guards as single
    _auth(request)
    if _body_too_big(request):  # T291
        raise HTTPException(status_code=413, detail="batch body too large")
    if len(req.messages) > MAX_BATCH:  # T224
        raise HTTPException(status_code=413, detail=f"batch capped at {MAX_BATCH} messages")
    if not req.messages:  # T279
        raise HTTPException(status_code=422,
                            detail={"code": "E_BATCH_EMPTY",
                                    "message": "messages must be a non-empty list"})
    if any(len(m) > 8000 for m in req.messages):  # T309
        raise HTTPException(status_code=413, detail="batch message too long")
    from . import moderate_batch
    from .config import GateConfig, questions_knob
    allow_t, delete_t = _thresholds(req.threshold, req.allow_threshold, req.delete_threshold)
    _check_model(req.model)  # T459
    _check_lang(req.lang)  # T836: same hint validation as /predict (T496)
    rules, preset_name = _resolve_rules(req.rules, req.preset)  # T473+T485: one pack, all msgs
    lang = req.lang
    if lang is None and preset_name is not None:  # T836: T502 parity — pack knows its language
        from .presets import preset_lang
        lang = preset_lang(preset_name)
    cfg = GateConfig(allow_threshold=allow_t, delete_threshold=delete_t,
                     timeout_s=_request_timeout(req.timeout_s),  # T525
                     questions=questions_knob())  # T755: BOUNCER_QUESTIONS
    # T837: timeout_s was applied PER MESSAGE (32 msgs x 60s = 1920s worst
    # case for one request). It's the per-REQUEST budget T515 documents —
    # the whole batch shares one deadline; stragglers get escalate fallbacks.
    deadline = time.monotonic() + cfg.timeout_s
    return [_clean(r) for r in moderate_batch(req.messages, rules, config=cfg,
                                              model=req.model, lang=lang,
                                              deadline=deadline)]

# Jev wire compat: {state, questions} -> {answers}. Lets TypeSafe SDKs hit us.
class SystemoneReq(BaseModel):  # T832: typed SHAPE, passthrough CONTENTS
    """The Jev wire contract is exactly {state, questions} — both JSON
    objects. Untyped, a `"state": "oops"` used to be forwarded raw into
    the router and died as a 500; now it's a 422 at the door. Contents
    stay untyped on purpose: the router owns state's fields (T774 pins
    non-list history straight through), and explicit null means absent."""
    state: dict | None = None
    questions: dict | None = None


@app.post("/v1/systemone")
def systemone(body: SystemoneReq, request: Request):
    _rate(request)  # T224: passthrough shares guards too
    _auth(request)
    state = body.state or {}
    questions = body.questions or {}
    # T775: keys and item text are unvalidated on this raw path — bound the
    # keys (reject: they can't be trimmed coherently) at both top levels
    for part in (state, questions):
        if isinstance(part, dict) and any(len(k) > MAX_KEY for k in part):
            from fastapi import HTTPException
            raise HTTPException(status_code=422,
                                detail={"code": "E_STATE",
                                        "message": f"state/questions key capped at "
                                                   f"{MAX_KEY} chars"})
    # T774: this raw path forwards `state` straight to the router, so nothing
    # else caps it — bound history to the newest MAX_CONTEXT items, the same
    # window /predict's context (T308) and the engine's [-history_n:] use.
    if isinstance(state, dict) and isinstance(state.get("history"), list):
        hist = state["history"][-MAX_CONTEXT:]
        # T775: per-item text is bounded too — trim (passthrough precedent
        # from T774), while structured /predict rejects the same bound
        hist = [h[:MAX_ITEM] if isinstance(h, str) else h for h in hist]
        state = {**state, "history": hist}
    r = get_router()
    # T833: the passthrough used to call r.predict raw — no timeout, no
    # breaker, no retry. It now shares the engine's reliability path: the
    # same env-driven timeout (BOUNCER_TIMEOUT, else 10s), one retry, and
    # breaker accounting. Failures surface as coded 503 E_MODEL — the Jev
    # contract stays honest (no fabricated answers) and the model's sick
    # days are counted like everyone else's.
    import time as _time

    from . import ModelError, _breaker_fail, _breaker_ok, _breaker_tripped, _predict_safe
    tripped = _breaker_tripped()  # T512: passthrough honors the breaker now
    t0 = _time.time()
    try:
        if tripped:
            raise ModelError("breaker open (model failing, cooling down)")
        answers = _predict_safe(r, state, questions, _request_timeout(None))
        _breaker_ok()  # T514: success closes the circuit
    except ModelError as e:
        if not tripped:  # T512: open-state short-circuits don't extend the trip
            _breaker_fail(5, 30.0)  # T511: engine defaults (GateConfig values)
        import json as _json  # T787: str(e) can carry internal paths — the
        # real text goes to the operator's log only; the client gets the
        # code plus a message we constructed (timeout/breaker) or a generic
        print(_json.dumps({"event": "model-error", "path": "/v1/systemone",
                           "err": str(e)[:300]}), flush=True)
        # T834: the passthrough used to be invisible — failures now count
        # like /predict's (action + cause in /stats, hashed line in audit)
        _record_passthrough(state, cause="breaker-open" if tripped else "model-error")
        msg = str(e)
        if "timed out after" not in msg and "breaker open" not in msg:
            msg = "model unavailable (details in server logs)"
        from fastapi import HTTPException as _HE
        raise _HE(status_code=503,
                  detail={"code": getattr(e, "code", "E_MODEL"),
                          "message": msg})
    # T834: successes are counted and audited too — a raw-path decision
    # lands in /stats (action "passthrough") and the audit log (hashed
    # message), exactly like the structured path's rows
    _record_passthrough(state, latency_ms=(_time.time() - t0) * 1000)
    return answers


def _record_passthrough(state: dict, latency_ms: float = 0.0,
                        cause: str | None = None) -> None:  # T834
    """One decision row for the raw path: hashed message, no text stored."""
    from .audit import log_decision
    from .stats import record
    text = state.get("message", "") if isinstance(state, dict) else ""
    record("passthrough", "ok", latency_ms, cause=cause)  # T834
    log_decision(str(text), "ok", 0.0, "passthrough", latency_ms)
