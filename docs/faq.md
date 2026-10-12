# FAQ (T143)

**Why not regex?** Regex can't read new phrasings; bouncer scores meaning in 30ms
and shows a regex baseline side-by-side in the demo so you can see the gap.

**Why not an LLM judge?** Cost and latency: 5 questions in one 33ms pass, $0
self-hosted, vs 5 sequential LLM calls at ~$0.50/1M tokens and seconds of latency.
Use the LLM for the hard escalations, not every message.

**Why not classical BERT?** Fixed label sets. Every server has different rules;
classical needs retraining per community. Here rules are just text in the request.

**Is it calibrated?** Base Laya ships overconfident (ECE ~0.2); temperature refit
on your data brings ~0.08. Never trust raw conf — use gates + margin abstention.

**NSFW/CSAM?** This tool flags; it does not replace human review or platform
reporting flows for illegal content. Escalate, don't automate, high-stakes calls.
