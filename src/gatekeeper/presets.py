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

ES = {  # T191
    "sin-spam": "sin anuncios, enlaces, autopromoción ni regalos de cripto",
    "se-amable": "sin insultos, odio ni acoso a jugadores",
    "sin-spoilers": "sin spoilers sin etiqueta",
}

FR = {  # T192
    "pas-de-spam": "pas de pubs, liens, autopromo ni cadeaux crypto",
    "soyez-aimable": "pas d'insultes, de haine ni de harcèlement",
    "pas-de-spoilers": "pas de spoilers sans balise",
}

AR = {  # T193 (rtl-safe: plain strings, no bidi controls)
    "bla-spam": "ممنوع الإعلانات والروابط والترويج الذاتي",
    "khalik-latif": "ممنوع الشتائم والكراهية والمضايقة",
    "bla-harg": "ممنوع حرق الأحداث بدون وسم",
}

PRESETS = {"gaming": GAMING, "study": STUDY, "support": SUPPORT, "stream": STREAM,
           "es": ES, "fr": FR, "ar": AR}

PRESET_LANG = {"gaming": "en", "study": "en", "support": "en", "stream": "en",  # T501
               "es": "es", "fr": "fr", "ar": "ar"}


def preset_lang(name: str) -> str:
    """T501: primary language of a pack (for autofill + mismatch notes)."""
    try:
        return PRESET_LANG[name]
    except KeyError:
        raise KeyError(f"unknown preset {name!r}; pick from {sorted(PRESET_LANG)}")


ROUTED_LANGS = ("ar", "zh", "ru", "fa", "ur", "he")  # T457: multilingual route

PACKLESS = ("zh", "ru", "fa", "ur", "he")  # T894: routed, but no pack ships yet


def lang_coverage() -> dict:
    """T894: every routed language -> the pack that carries it, or None.
    None means packless by NAME, not by omission: those languages ride the
    multilingual checkpoint with whatever rules the deployment supplies
    (docs/presets.md lists them). The audit trail is the map itself — an
    unrouted-and-unlisted language fails the P47 sweep test."""
    packs: dict = {}
    for name, lang in PRESET_LANG.items():
        packs.setdefault(lang, []).append(name)
    return {lang: sorted(packs[lang]) if lang in packs else None
            for lang in ROUTED_LANGS}

DESCRIPTIONS = {
    "gaming": "clan / lobby chat: cheats, kindness, spam, spoilers",
    "study": "homework group: on-topic, hints-not-answers, kindness",
    "support": "help desk: no PII, on-topic, kindness",
    "stream": "twitch-style chat: spam, kindness, spoilers, flood",
    "es": "juego en español: spam, amabilidad, spoilers",
    "fr": "jeu en français: spam, amabilité, spoilers",
    "ar": "لعب بالعربية: سبام، أدب، حرق",
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
