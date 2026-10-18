# bouncer

Programmable live-chat moderation over a System One router — regex speed,
one forward pass, evidence-carrying decisions.

```bash
pip install -e ".[server]"
bouncer check "you all suck" --preset gaming   # → prints ACTION: reason, exits 0/2/3
bouncer serve                                  # API on :8000
```

## Find your page

**Using bouncer** — [Getting started](getting-started.md) ·
[Cookbook](cookbook.md) · [Rules guide](rule-guide.md) ·
[Presets](presets.md) ·
[Gates](gates.md) · [Thresholds](thresholds.md) ·
[Answer shape](answer-shape.md) · [FAQ](faq.md) ·
[Demo script](demo-script.md)

**Reference** — [Environment variables](environment.md) ·
[API](api.md) · [Error codes](error-codes.md) ·
[Architecture](architecture.md) ·
[Glossary](glossary.md) · [Golden set](golden.md) · [MPS scoring](mps.md) ·
[Version notes](versions.md) · [Roadmap](ROADMAP.md)

**Operations** — [Security](SECURITY.md) · [Threat model](threat-model.md) ·
[Runbook](runbook.md) · [Release checklist](RELEASE-CHECKLIST.md)
