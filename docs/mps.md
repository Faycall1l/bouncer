# Local MPS setup (T219, Apple Silicon)

_(Last checked against v0.5.0.)_

```bash
python3.12 -m venv /tmp/laya-venv
/tmp/laya-venv/bin/pip install "laya>=0.4.3"
# weights (~1.6GB) download on first Router() — 5+ min on slow links
/tmp/laya-venv/bin/pip install --no-deps -e /path/to/bouncer
BOUNCER_AUDIT=/tmp/a.jsonl python -c "
from gatekeeper import moderate, get_preset
print(moderate('GG all', get_preset('gaming')))"
```

Notes: first call ~45s (Metal compile), then 1–5s per 5-question call.
CPU fallback is ~2x slower. Laya picks device automatically (CUDA → MPS → CPU).

Terms used here are defined in the [Glossary](glossary.md).
