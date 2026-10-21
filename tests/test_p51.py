"""P51 tests: security refresh (T971–T990)."""
# Apache-2.0. See LICENSE.

import inspect
import json
from pathlib import Path


def test_t973_adjudicate_is_operator_only_cli(monkeypatch, tmp_path):  # T973
    """T973: the appeal path answers, the operator decides. Pin, not hope:
    serve.py exposes no adjudicate/amnesty route (checked against the live
    app.routes, not just the source), no adapter wires user input to the
    mutating review.adjudicate / strikes.amnesty — the platform-facing
    `appeal` command only RENDERS the user's newest queue row through
    appeal_reply (read-only, T864) — and the only entry points are the
    CLI's cmd_adjudicate (T865) and cmd_amnesty (T881). A platform user
    can ask; only the operator can decide."""
    from gatekeeper import review as rv
    from gatekeeper import serve

    # 1. no HTTP surface at all: route paths never mention adjudication
    paths = [r.path for r in serve.app.routes]
    for word in ("adjudicat", "amnesty", "verdict", "approve"):
        assert not any(word in p for p in paths), (word, paths)

    # 2. the source has no hidden wiring either
    src = inspect.getsource(serve)
    assert "adjudicate" not in src and "amnesty" not in src

    # 3. adapters can neither adjudicate nor amnesty; their `appeal`
    #    command answers via appeal_reply only
    adp = Path("src/gatekeeper/adapters")
    for p in sorted(adp.glob("*.py")):
        text = p.read_text()
        assert "adjudicate" not in text, p.name
        assert "strikes.amnesty" not in text, p.name
    common = (adp / "common.py").read_text()
    assert "appeal_reply" in common  # the read-only renderer (T864)

    # 4. mutating entry points are CLI-only
    cli = Path("src/gatekeeper/cli.py").read_text()
    assert "def cmd_adjudicate" in cli and "def cmd_amnesty" in cli

    # 5. functional: appeal_reply renders without mutating the queue row
    q = str(tmp_path / "t973-q.jsonl")
    monkeypatch.setattr(rv, "_PATH", q)
    row = {"t": 1, "id": "ab12cd34", "user": "telegram:42",
           "message": "hello", "action": "review", "rule": "r1",
           "conf": 0.9, "cause": "", "model": "", "preset": ""}
    with open(q, "w") as f:
        f.write(json.dumps(row) + "\n")
    reply = rv.appeal_reply("telegram:42", {"rules": []})
    assert "ab12cd34" in reply  # the row id links the appeal to adjudication
    after = json.loads(Path(q).read_text().splitlines()[0])
    assert "verdict" not in after and "vt" not in after, after
    assert after == row  # byte-identical: rendering changed nothing
