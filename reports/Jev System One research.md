# Modern research report: Jev, typed decision models, and a bouncer test path

_Scope: repository state at the modernization pass. Known numbers below are labelled by provenance; bouncer's own `0.305` zero-shot number is marked STALE and should be replaced by a real sealed receipt, not silently re-pointed._

## 1. Scope and method

This report is a modernization of the earlier Jev research write-up. It keeps the useful public evidence and removes hype-shaped language where it was not evidence. The bounded scope is:

- The shape of the decision interface that Jev/Laya expose.
- Public performance and calibration evidence that can be cited honestly.
- What bouncer can actually claim, and what it cannot.
- A concrete, falsifiable modernization agenda for this repository.

The authoritative public sources used as of the latest available citations are linked inline. All numbers are cited to a source or marked as unknown.

## 2. Executive conclusion

The useful distinction is between "a typed decision interface" and "a generative judge". The learning/adaptation mechanism is a separate question and is not the speed argument.

Known facts from public evidence:

1. Jev is a hosted, proprietary decision model. It returns fixed-option choices or probabilities; it does not generate text as its main contract.
2. Jev is not documented as a fast-weight or test-time weight-update model. Laya's cheap path fits a small readout over frozen features. The fast-weight literature is related lineage, not proof of what Jev or Laya do.
3. Public performance claims for speed favor typed one-pass models over generative judges. Exact gains are hardware- and request-shape-dependent, so the right answer is to measure locally rather than average vendor numbers.
4. Moderation accuracy on dynamic-rule live chat is weaker evidence than interface shape. Moderation accuracy, FPR, FN, precision, and coverage must be measured on adjudicated traffic.
5. Thresholds must be calibrated out of sample. The known478of "trade accuracy for latency" is not a claim this repository has measured yet.

## 3. Evidence hierarchy for this report

Rank the claims used below:

| Rank | Claim type | Example |
|---|---|---|
| A | Repository measurement | bouncer stub bench on template data; deferred |
| B | Own paired, pre-registered evaluation | planned; see section 8 |
| C | Independent preprints with scripts | see sources below |
| D | Author-run benchmarks | Laya's 30 ms/34 s figures |
| E | Vendor launch posts | TypeSafe Jev launch |
| F | Vague marketing/press repetition | unusable as claim |

Known independent numbers should be pinned to the exact paper, hardware, and model revision when used. Vendor numbers should never be presented as local bouncer results.

## 4. What Jev is, from public sources

- TypeSafe AI announced Jev on 2026-09-15 as the "System One Model" line. The service takes a state and typed questions and returns choices, rubric positions, or proposition probabilities in one pass ([TypeSafe AI](https://typesafe.ai/blog/introducing-system-one-models-and-jev)).
- Jev 1.13.0 is the version name used publicly; no authoritative TypeSafe technical report or peer-reviewed paper is cited here, so it should be treated as version metadata rather than a validated implementation receipt.
- Hugging Face added `JevForDecision` docs later and described the reproducible interface: linear scoring of single-token labels at the last prompt token, soft-capped logits, and related `is_causal=False` checkpoints. This is interface documentation, not proof of TypeSafe weights. The report still requires the exact pinned checkpoint/revision for any bouncer real receipt.

## 5. Public evidence with provenance

### Speed and architecture

- Independent characterization says Jev does not generate text and probabilities are described as calibrated; architecture and training data remain unpublished. Treat "calibrated" here as a vendor claim unless measured locally.
- Public figures include Jev p50/p95 of approximately 314 ms / 387 ms and Laya p50/p95 approximately 588 ms / 1,364 ms on CPU in the cited GitHub evaluation. These are architecture/request-shape comparisons, not bouncer local results.
- Laya's own published figures say 32.8 ms p50 and advertise 6-7x speedup over Jev, but hardware/request shape differ. Keep them separate.

### Accuracy / calibration evidence

The strongest public evaluation cited is a preprint that ran a large zero-shot request volume. Key numbers include:

- Jev scored 95-99% on IMDB, SST-2, HellaSwag, and ARC; Gemma scored 37/37 datasets better than the baseline, and there were 27 datasets where Jev beat a Qwen baseline.
- A paired self-audited evaluation found Jev more accurate than Laya on 9 of 11 agent decision points by a range of +10.8 to +46.0 percentage points; for option-order reversal, 30.3% of Laya's answers flipped versus 1.8% for Jev.
- Laya's held-out toxic-chat number is approximately 0.530 accuracy / 0.400 macro-F1, with a warning that real traffic differs from hand-picked examples.
- Laya's shipped ECE is 0.466 and falls to 0.081 only after refitting temperatures per question type and option count on held-out data.

These are useful evidence of capability shape, but they do not license bouncer claims about live-chat moderation. In particular, none of them establishes moderation FNR/FPR on community rules in this repository.

### Invalidated headline

The current report contains:

- Bouncer template zero-shot rule accuracy: 0.305, marked STALE.
- Regex floor: 0.403.

Both should remain visible until replaced by a real sealed receipt. The regex floor is already a measurable template-set result; the zero-shot bouncer number is bookkeeping unless tied to a manifest.

## 6. What this means for bouncer

Current bouncer evidence scope:

- Template stubs exercise control flow, not model quality or latency.
- The existing gate/action taxonomy is useful: typed outcomes, causes, quiet/margin post-checks, and audit traces.
- The current README should state the measurement scope, not claim dynamic-rule accuracy or serving speed from this repo.

Limits to avoid:

- Any claim that calibration or serving speed is established in this repo is an evidence claim; the default answer is no receipt, not a vendored name.
- Any claim of a specific speed multiplier or a general dominance claim over all other models is outside this report unless separately measured.
- Coincidence of rule names or prompt templates must not become an accuracy claim.

## 7. modernization receipts needed

Before any real claim, bouncer needs at minimum:

1. Repository receipt for the deterministic eval harness: task specs, dataset manifest hash, baseline ladder, paired comparison, metrics, parity gate.
2. Stub receipt: a `mode:"stub"` quality/latency envelope with counts of ERROR_UNAVAILABLE and fallback rows.
3. Real Jev receipt: exact checkpoint/revision, hardware, request mix, fallback tokens, and the same harness. Vendor-reported p50/p95 can be listed separately.
4. Calibration receipt: thresholds fitted on a separate split, ECE by question family, reliability slopes, false-positive rate, false-negative rate, coverage, and precision/recall at fixed coverage.
5. Dynamic-rule protocol: sealed adjudicated community rules, rule split to avoid leakage, option-order repeats, menu-size variants, and per-community FPR slices.
6. Tests: typed system diagram/research tests, real-vs-stale receipts, and CI gates that fail on missing `mode:"real"`.

## 8. Phased modernization plan

1. Add the system diagram and diagram/research tests (this push).
2. Modernize this research report with provenance, limits, and explicit uncertainty.
3. Add a small sealed paired eval harness if not already usable.
4. Add a repository `mode:"stub"` receipt.
5. Add a real Jev receipt with pinned revision/hardware; list public numbers only as public numbers.
6. Add per-rule-family calibration receipts and community-slice metrics.
7. Add regression gates: paired parity, self-stability, stale-marker policy, and README claims that are test-pinned.
8. Final push: full suite green and every commit pushed.

## 9. Key sources

- [TypeSafe AI](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- [HF Transformers Jev docs](https://github.com/huggingface/transformers/blob/main/docs/source/en/model_doc/jev.md)
- [Laya BENCHMARKS](https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md)
- [arXiv:2609.37647](https://arxiv.org/abs/2609.37647)
- [arXiv:2611.15592](https://arxiv.org/abs/2611.15592)
- [arXiv:2610.02267](https://arxiv.org/abs/2610.02267)
- [Dror et al., ACL 2018](https://aclanthology.org/P18-1128.pdf)
- [Google Rules of ML](https://developers.google.com/machine-learning/guides/rules-of-ml)
- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)
