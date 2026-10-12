"""FastAPI: /predict + Jev-compatible /v1/systemone passthrough."""
import time
from fastapi import FastAPI
from pydantic import BaseModel
from . import moderate, build_questions, get_router
from . import __version__

app = FastAPI(title="bouncer")
_START = time.time()


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

@app.post("/predict")
def predict(req: ModReq):
    return moderate(req.message, req.rules, req.context, req.threshold)

# Jev wire compat: {state, questions} -> {answers}. Lets TypeSafe SDKs hit us.
@app.post("/v1/systemone")
def systemone(body: dict):
    r = get_router()
    return r.predict(body.get("state", {}), body.get("questions", {}))
