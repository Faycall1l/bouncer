"""Built-in rule packs. `get_preset(name)` -> {rule_id: rule_text}."""
from __future__ import annotations

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
