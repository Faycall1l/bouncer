"""P22 tests (T391-T410): docs match code. No weights."""
import pathlib
import sys

sys.path.insert(0, "src")


def _read(name: str) -> str:
    return pathlib.Path(name).read_text()


def test_docs_consistency():  # T410
    from gatekeeper import list_presets
    readme = _read("README.md")
    for code in ("E_RULES", "E_CONFIG", "E_WEBHOOK", "E_SLACK", "E_INTERNAL", "E_MODEL"):
        assert code in readme, code
    presets_doc = _read("docs/presets.md")
    for name in list_presets():
        assert name in presets_doc, name
    api = _read("docs/api.md")
    for route in ("/predict", "/predict/batch", "/v1/systemone", "/health", "/metrics",
                  "Retry-After", "allow_threshold"):
        assert route in api, route
    gates = _read("docs/gates.md")
    for cause in ("jailbreak", "needs-human", "violation", "suspected", "margin", "quiet",
                  "breaker-open"):  # T609: breaker override row
        assert cause in gates, cause


def test_docs_consistency_extended():  # T609: codes, routes, presets, env vars
    import re

    from gatekeeper import list_presets
    from gatekeeper.presets import PRESET_LANG
    api = _read("docs/api.md")
    readme = _read("README.md")
    # error codes added since 0.2.0 are documented where requests are
    for code in ("E_PRESET", "E_LANG", "E_SNAPSHOT", "E_MODEL_NAME"):
        assert code in api or code in readme, code
    # routes: everything the server exposes appears in the API reference
    from gatekeeper.serve import app
    routes = {getattr(r, "path", "") for r in app.routes}
    for r in sorted(routes):
        if r.startswith(("/predict", "/health", "/version", "/models", "/stats",
                         "/presets", "/metrics", "/ready", "/v1/")):
            assert r in api, f"route {r} missing from docs/api.md"
    # presets: catalogue table and code agree, lang tags included
    presets_doc = _read("docs/presets.md")
    for name, lang in PRESET_LANG.items():
        assert name in presets_doc and f"`{lang}`" in presets_doc, name
    assert set(list_presets()) == set(PRESET_LANG)
    # env vars: every BOUNCER_* read by the code is documented somewhere
    src = " ".join(_read(p) for p in ("src/gatekeeper/__init__.py",
                                      "src/gatekeeper/pool.py",
                                      "src/gatekeeper/serve.py",
                                      "src/gatekeeper/cli.py"))
    envs = set(re.findall(r"BOUNCER_[A-Z_]+", src))
    docs = readme + api + _read("docs/thresholds.md") + _read("docs/SECURITY.md")
    missing = {e for e in envs if e not in docs}
    assert not missing, f"undocumented env vars: {sorted(missing)}"
