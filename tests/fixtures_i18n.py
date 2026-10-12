"""T042: multilingual smoke fixtures (state-building only; weights needed for scores)."""
import sys
sys.path.insert(0, "src")
from gatekeeper import build_questions

CASES = [
    ("es", "hola a todos, buen juego", {"charla": "conversacion normal sin spam"}),
    ("fr", "bon jeu tout le monde", {"discussion": "conversation normale"}),
    ("de", "gutes spiel leute", {"chat": "normale unterhaltung"}),
]

for lang, msg, rules in CASES:
    q = build_questions(rules)
    assert "ok" in q["rule"]["criteria"], (lang, "missing ok")
    print(lang, "OK", msg)
