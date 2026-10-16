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
    for cause in ("jailbreak", "needs-human", "violation", "suspected", "margin", "quiet"):
        assert cause in gates, cause
