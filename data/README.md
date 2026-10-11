# Gatekeeper-ChatMix dataset

`gatekeeper-12k.jsonl`: one row = one message + THAT server's rule-set (K varies 3-6) + 5 labels.

```json
{"state": {"message": "...", "history": [], "rules": {"no-spam": "...", "be-kind": "..."}},
 "labels": {"rule": "no-spam", "harm": "harmful", "hype": "hyped", "jailbreak": false, "escalate": false}}
```

Splits: 10k train / 1k dev / 1k test, server-disjoint (test rule-sets unseen). Teacher: template bootstrap + Qwen/GPT distillation, spot-checked 200 rows.

Why classical fails: fixed 77-way classifier memorizes labels; here criteria text + K change per row. Must read rules, not memorize ids.

Build: `python data/synth_rules.py --n 12000 --out data/gatekeeper-12k.jsonl`
HF push: `huggingface-cli upload YOUR_HF/gatekeeper-chatmix-12k data/gatekeeper-12k.jsonl`
