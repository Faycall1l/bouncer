# Rule-writing guide (T138)

The scorer reads rule *text*, not ids. Good rules are concrete and self-contained.

Good:
* `no-spam: no ads, links, self-promo, or crypto giveaways`
* `be-kind: no insults, hate, slurs, or harassment of players`

Bad:
* `spam: no spam` (circular — model can't ground it)
* `rule1: be nice` (vague; overlaps every other rule)

Limits: ≤12 rules (options share a 256-token head budget — past ~20, labels blur,
the Banking77 lesson). Run `bouncer pack lint` to catch overlap. Keep each rule
under a sentence; put examples in the text (`links like http://...`).
