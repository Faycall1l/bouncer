# Fine-tune on Kaggle 2xT4 (4-5h)

Don't write RLCD from scratch — fork Laya's notebook, swap dataset:

1. Open [laya_finetune_typed_decisions_2xT4_kaggle.ipynb](https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb) → Copy to your Kaggle.
2. Replace dataset cell with:
```python
# gatekeeper rows -> laya format (state + questions + teacher dist)
import json
from gatekeeper_format import to_laya_records  # see finetune_kaggle.py
records = to_laya_records("/kaggle/input/gatekeeper-12k.jsonl")
```
3. Keep RLCD defaults: backbone lr 1e-5, head lr 1e-4, 4 epochs, Gaussian logit noise, log+spherical reward + soft CE.
4. Run all → temperature refit on dev → push `YOUR_HF/gatekeeper-laya-421m`.

`finetune_kaggle.py` here = the 3 cells you paste (converter + train call + push). Full loop already proven by Laya; your novelty is the dynamic-K dataset.
