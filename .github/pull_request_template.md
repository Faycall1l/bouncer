## What & how verified

<!-- what changed; how verified (tests / Kaggle link). T158's question, kept. -->

## Checklist

- [ ] `pytest -q` green locally (the **full** suite, not just the new file)
- [ ] `ruff check .` clean
- [ ] Tests cover the change (or the comment says why they can't)
- [ ] Docs updated where behavior / CLI / output changed (README, `docs/`)
- [ ] `TODO.md` boxes ticked — each box landed as its own commit
- [ ] No secrets, tokens, or config values pasted into the diff
