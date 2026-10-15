# Apache-2.0. See LICENSE.
"""FastAPI: /predict + Jev-compatible /v1/systemone passthrough."""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware  # T055
from pydantic import BaseModel

from . import __version__, get_router, moderate


@asynccontextmanager
async def _lifespan(app: FastAPI):  # T226: lifespan replaces deprecated on_event
    try:  # T059+T177: preload + warmup; weights may be absent at boot
        r = get_router()
        r.predict({"message": "warmup"}, {"q": {"type": "noul", "instructions": "warmup?"}})
    except Exception as e:  # noqa: BLE001 — first real call loads instead
        print(f"warmup skipped: {e}", flush=True)
    yield
    print('{"event": "shutdown", "note": "in-flight predict calls drain with workers"}',  # T179
          flush=True)


app = FastAPI(title="bouncer", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])  # T055: demo-friendly
_START = time.time()

_KEY = __import__("os").environ.get("BOUNCER_KEY", "")  # T053: optional shared key

_BUCKETS: dict = {}  # T054: >60 req/min per IP -> 429


def _sweep(now: float) -> None:
    """T227: evict idle IPs so the bucket map can't grow without bound."""
    if len(_BUCKETS) > 512:
        for ip, hits in list(_BUCKETS.items()):
            if not hits or now - hits[-1] > 120:
                del _BUCKETS[ip]


def _rate(request: Request) -> None:
    if request is None:
        return
    ip = request.client.host if request.client else "?"
    now = time.time()
    _sweep(now)  # T227
    hits = [t for t in _BUCKETS.get(ip, []) if now - t < 60]
    hits.append(now)
    _BUCKETS[ip] = hits[-60:]
    if len(hits) > 60:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="rate limited")


def _auth(request) -> None:
    if _KEY and request.headers.get("X-API-Key") != _KEY:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="bad API key")


@app.middleware("http")  # T052+T056+T065: request id, access log, latency header
async def _mw(request, call_next):
    import uuid
    rid = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    t0 = time.time()
    resp = await call_next(request)
    ms = (time.time() - t0) * 1000
    resp.headers["X-Request-ID"] = rid
    resp.headers["X-Bouncer-ms"] = f"{ms:.1f}"
    print(f'{{"rid": "{rid}", "path": "{request.url.path}", "ms": {ms:.1f}}}', flush=True)
    return resp


@app.exception_handler(Exception)  # T269: structured 500, no traceback to clients
async def _internal(request: Request, exc: Exception):
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    if isinstance(exc, HTTPException):  # T269: HTTP errors keep status + detail
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail},
                            headers=exc.headers)
    print(f'{{"event": "internal-error", "path": "{request.url.path}", '
          f'"err": "{type(exc).__name__}"}}', flush=True)
    return JSONResponse(status_code=500,
                        content={"detail": {"code": "E_INTERNAL",
                                            "message": "internal error"}})


@app.get("/health")  # T046
def health():
    try:
        get_router()
        model = "loaded"
    except Exception as e:  # noqa: BLE001
        model = f"error: {e}"
    return {"ok": True, "model": model, "uptime_s": round(time.time() - _START, 1)}


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
    from .cache import CACHE
    from .stats import get_stats
    return {"name": "bouncer", "version": __version__,  # T240
            "uptime_s": round(time.time() - _START, 1),
            "decisions": get_stats(), "cache": CACHE.stats()}


@app.get("/presets")  # T058
def presets():
    from . import get_preset, list_presets
    return {n: get_preset(n) for n in list_presets()}


@app.get("/metrics")  # T178: prometheus-style text
def metrics():
    from fastapi.responses import PlainTextResponse

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
    return PlainTextResponse("\n".join(lines) + "\n")


class ModReq(BaseModel):
    message: str
    rules: dict[str, str]
    context: list[str] = []
    threshold: float = 0.85
    allow_threshold: float | None = None  # T223: split gates; None falls back to threshold
    delete_threshold: float | None = None
    lang: str | None = None

    model_config = {"json_schema_extra": {"examples": [  # T063
        {"message": "FREE NITRO http://x.gg", "rules": {"no-spam": "no ads or links"},
         "threshold": 0.85}]}}


def _clean(res: dict) -> dict:
    res = dict(res)
    res.pop("raw", None)
    return res


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


@app.post("/predict")
def predict(req: ModReq, request: Request):
    from fastapi import HTTPException
    _rate(request)
    _auth(request)
    if len(req.message) > 8000:  # T064
        raise HTTPException(status_code=413, detail="message too long")
    from fastapi import HTTPException

    from .config import GateConfig
    from .explain import explain
    from .rules import RuleError
    allow_t, delete_t = _thresholds(req.threshold, req.allow_threshold, req.delete_threshold)
    try:
        res = moderate(req.message, req.rules, req.context,
                       config=GateConfig(allow_threshold=allow_t, delete_threshold=delete_t),
                       lang=req.lang)
    except RuleError as e:
        raise HTTPException(status_code=422,  # T256: machine-readable code
                            detail={"code": getattr(e, "code", "E_RULES"),
                                    "message": str(e)})
    res["reason"] = explain(res, req.rules)
    import json as _json  # T246: decision line for operators (no message text)
    print(_json.dumps({"event": "decision", "action": res["action"], "rule": res["rule"],
                       "conf": round(res["confidence"], 3)}), flush=True)
    return _clean(res)


class BatchReq(BaseModel):
    messages: list[str]
    rules: dict[str, str]
    threshold: float = 0.85
    allow_threshold: float | None = None  # T223
    delete_threshold: float | None = None


@app.post("/predict/batch")  # T050
def predict_batch(req: BatchReq, request: Request):
    from fastapi import HTTPException
    _rate(request)  # T224: batch shares the same guards as single
    _auth(request)
    if len(req.messages) > MAX_BATCH:  # T224
        raise HTTPException(status_code=413, detail=f"batch capped at {MAX_BATCH} messages")
    if not req.messages:  # T279
        raise HTTPException(status_code=422,
                            detail={"code": "E_BATCH_EMPTY",
                                    "message": "messages must be a non-empty list"})
    from . import moderate_batch
    from .config import GateConfig
    allow_t, delete_t = _thresholds(req.threshold, req.allow_threshold, req.delete_threshold)
    cfg = GateConfig(allow_threshold=allow_t, delete_threshold=delete_t)
    return [_clean(r) for r in moderate_batch(req.messages, req.rules, config=cfg)]

# Jev wire compat: {state, questions} -> {answers}. Lets TypeSafe SDKs hit us.
@app.post("/v1/systemone")
def systemone(body: dict, request: Request):
    _rate(request)  # T224: passthrough shares guards too
    _auth(request)
    r = get_router()
    return r.predict(body.get("state", {}), body.get("questions", {}))
