# Preset catalogue (T147, lang tags T603)

_(Last checked against v0.3.0.)_

| preset | lang tag | rules | best for |
|---|---|---|---|
| gaming | `en` | no-cheat, be-kind, no-spam, no-spoiler | clan / lobby chat |
| study | `en` | stay-topic, no-answers, be-kind, en-only | homework groups |
| support | `en` | no-pii, stay-topic, be-kind, no-spam | help desk |
| stream | `en` | no-spam, be-kind, no-spoiler, chill | twitch-style chat |
| es 🇪🇸 | `es` | sin-spam, se-amable, sin-spoilers | juego en español |
| fr 🇫🇷 | `fr` | pas-de-spam, soyez-aimable, pas-de-spoilers | jeu en français |
| ar 🇸🇦 | `ar` | bla-spam, khalik-latif, bla-harg | لعب بالعربية (rtl-safe strings) |

`bouncer presets` prints this table with tags; `PRESET_LANG` in
`gatekeeper/presets.py` is the source of truth.

Example: `bouncer check "GG all" --preset gaming` → allow.

Non-English packs (T399): same 3-rule shape (spam/kindness/spoilers) in the
community's language. The pack knows its language (T502): choosing `es`/`fr`/`ar`
autofills the `lang` hint — reason language + routing: `ar` pins the
`multilingual` checkpoint, `es`/`fr` are latin and ride laya's own
auto-routing — so an explicit `--lang` is only needed to *override* the pack. The base model is English-first, so treat these
as hinted, not fluent.

Terms used here are defined in the [Glossary](glossary.md).
