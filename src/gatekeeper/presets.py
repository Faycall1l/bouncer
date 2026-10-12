"""Built-in rule packs. `get_preset(name)` -> {rule_id: rule_text}."""
from __future__ import annotations

# Apache-2.0. See LICENSE.

GAMING = {
    "no-cheat": "no cheat codes, exploits, stream-sniping, or smurf-bragging",
    "be-kind": "no insults, hate, slurs, or harassment of players",
    "no-spam": "no ads, links, self-promo, or crypto giveaways",
    "no-spoiler": "no plot spoilers without a spoiler tag",
}

STUDY = {
    "stay-topic": "keep to homework, exams, and study material",
    "no-answers": "no posting full solutions; hints and method only",
    "be-kind": "no insults, mockery, or harassment",
    "en-only": "English only in main chat during study hours",
}

SUPPORT = {
    "no-pii": "no passwords, tokens, card numbers, or personal data in chat",
    "stay-topic": "billing, refunds, outages, and account help only",
    "be-kind": "no abuse toward agents or other customers",
    "no-spam": "no ads, links, or repeated reposts",
}

STREAM = {
    "no-spam": "no link dumps, self-promo, or bot spam",
    "be-kind": "no hate, harassment, or backseating abuse toward the streamer",
    "no-spoiler": "no game spoilers or ending leaks",
    "chill": "no caps flood, emoji walls, or copypasta storms",
}

PRESETS = {"gaming": GAMING, "study": STUDY, "support": SUPPORT, "stream": STREAM}

DESCRIPTIONS = {
    "gaming": "clan / lobby chat: cheats, kindness, spam, spoilers",
    "study": "homework group: on-topic, hints-not-answers, kindness",
    "support": "help desk: no PII, on-topic, kindness",
    "stream": "twitch-style chat: spam, kindness, spoilers, flood",
}


def get_preset(name: str) -> dict:
    """T012: preset by name (KeyError lists valid names)."""
    try:
        return dict(PRESETS[name])
    except KeyError:
        raise KeyError(f"unknown preset {name!r}; pick from {sorted(PRESETS)}")


def list_presets() -> dict:
    """T012: name -> description."""
    return dict(DESCRIPTIONS)
