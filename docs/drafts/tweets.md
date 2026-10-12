# Tweet thread draft (T190)

1/ Chat mod shouldn't need an LLM call per message. Bouncer: your rules as text,
5 typed questions, ONE 30ms forward pass. No generation, nothing to parse.
2/ allow/flag/delete/escalate with calibrated confidence + margin abstention.
Unsure? Human reviews. That's the whole trick classical softmax can't do.
3/ Zero-shot base scores 0.305 on our rules — we published the bad number too.
Fine-tune recipe (RLCD, Kaggle 2xT4) included. Apache-2.0.
4/ `pip install -e .` → `bouncer check "GG all" --preset gaming`. Demo + bots included.
