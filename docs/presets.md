# Preset catalogue (T147)

| preset | rules | best for |
|---|---|---|
| gaming | no-cheat, be-kind, no-spam, no-spoiler | clan / lobby chat |
| study | stay-topic, no-answers, be-kind, en-only | homework groups |
| support | no-pii, stay-topic, be-kind, no-spam | help desk |
| stream | no-spam, be-kind, no-spoiler, chill | twitch-style chat |
| es 🇪🇸 | sin-spam, se-amable, sin-spoilers | juego en español |
| fr 🇫🇷 | pas-de-spam, soyez-aimable, pas-de-spoilers | jeu en français |
| ar 🇸🇦 | bla-spam, khalik-latif, bla-harg | لعب بالعربية (rtl-safe strings) |

Example: `bouncer check "GG all" --preset gaming` → allow.

Non-English packs (T399): same 3-rule shape (spam/kindness/spoilers) in the
community's language. Pair with `--lang es|fr|ar` (or the demo language
dropdown) so the router gets a language hint; the base model is English-first,
so treat these as hinted, not fluent.
