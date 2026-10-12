"""FastAPI: /predict + Jev-compatible /v1/systemone passthrough."""
import time
from fastapi import FastAPI, Request
from pydantic import BaseModel
from . import moderate, build_questions, get_router
from . import __version__

app = FastAPI(title="bouncer")
_START = time.time()

_KEY = __import__("os").environ.get("BOUNCER_KEY", "")  # T053: optional shared key


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

class ModReq(BaseModel):
    message: str
    rules: dict[str, str]
    context: list[str] = []
    threshold: float = 0.85
    lang: str | None = None


def _clean(res: dict) -> dict:
    res = dict(res)
    res.pop("raw", None)
    return res


@app.post("/predict")
def predict(req: ModReq, request: Request):
    from fastapi import HTTPException
    _auth(request)
    from fastapi import HTTPException
    from .rules import RuleError
    from .explain import explain
    try:
        res = moderate(req.message, req.rules, req.context, threshold=req.threshold, lang=req.lang)
    except RuleError as e:
        raise HTTPException(status_code=422, detail=str(e))  # T049: rule errors are 422
    res["reason"] = explain(res, req.rules)
    return _clean(res)


class BatchReq(BaseModel):
    messages: list[str]
    rules: dict[str, str]
    threshold: float = 0.85


@app.post("/predict/batch")  # T050
def predict_batch(req: BatchReq):
    from . import moderate_batch
    from .config import GateConfig
    cfg = GateConfig(allow_threshold=req.threshold, delete_threshold=req.threshold)
    return [_clean(r) for r in moderate_batch(req.messages, req.rules, config=cfg)]

# Jev wire compat: {state, questions} -> {answers}. Lets TypeSafe SDKs hit us.
@app.post("/v1/systemone")
def systemone(body: dict):
    r = get_router()
    return r.predict(body.get("state", {}), body.get("questions", {}))
