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


def test_t974_amnesty_operator_only_and_audited(monkeypatch, tmp_path):  # T974
    """T974: strike forgiveness is operator-only and leaves evidence. The
    mutating amnesty exists only on the CLI — no HTTP route, no adapter
    mentions it — and a successful run writes exactly one audit row:
    who = the subject as the standard 16-hex hash (the audit log stays
    hash-only, T029/T883 — plaintext user ids live only in the 0600
    strikes table), when = the row's `t`, why = the applied weight and
    the before->after count in `cause`. The adjudicate-reject path was
    already recorded in-row (verdict/vt/after, T865); this row closes
    the standalone CLI path (T881)."""
    import hashlib
    import importlib
    import inspect

    from gatekeeper import audit as _au
    from gatekeeper import serve
    from gatekeeper import strikes as _st
    from gatekeeper.cli import main

    # operator-only: no route, no source wiring, no adapter command
    assert not any("amnesty" in r.path for r in serve.app.routes)
    assert "amnesty" not in inspect.getsource(serve)
    for p in sorted(Path("src/gatekeeper/adapters").glob("*.py")):
        assert "amnesty" not in p.read_text(), p.name

    # functional: amnesty leaves one hash-only row with who/when/why
    _st.reset()
    _st.add_strike("u1")       # 3 strikes accrued in total
    _st.add_strike("u1")
    _st.add_strike("u1")
    monkeypatch.setattr(_st, "_PATH", str(tmp_path / "strikes.json"))
    monkeypatch.setenv("BOUNCER_AUDIT", str(tmp_path / "audit.jsonl"))
    importlib.reload(_au)
    try:
        assert main(["amnesty", "u1", "--weight", "2"]) == 0
        lines = (tmp_path / "audit.jsonl").read_text().splitlines()
        assert len(lines) == 1, lines
        row = json.loads(lines[0])
        assert row["action"] == "amnesty" and row["rule"] == "amnesty"
        assert row["cause"] == "weight=2 strikes 3->1", row["cause"]
        assert row["t"] > 0  # when: the row's own timestamp
        digest = hashlib.sha256(b"amnesty u1").hexdigest()[:16]
        assert row["msg"] == digest  # who, hashed like every other row
        assert "u1" not in lines[0]  # plaintext user never reaches the audit

        # no effect, no row: a no-strikes amnesty exits 1, logs nothing
        assert main(["amnesty", "nobody"]) == 1
        assert len((tmp_path / "audit.jsonl").read_text().splitlines()) == 1
    finally:
        if _au._F:
            _au._F.close()
        importlib.reload(_au)  # restore the default audit path
