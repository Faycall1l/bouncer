# Harness Architecture and Honest Scientific Reporting

## What are the standard components of an evaluation harness (task specs, dataset loaders, model adapters, metrics, reproducibility metadata, artifact generation, regression gates)?

### Takeaway

Mature harnesses converge on a small set of decoupled pieces: declarative task/config specs, dataset+prompt construction, a model-backend interface, post-processing + metrics, and a summarizer that persists results. Reproducibility is engineered in via pinned configs, reference implementations, self-comparison checks, and versioned data/metrics — not via prose claims.

### Cited Findings

- OpenCompass's architecture is explicitly five components — Configuration System, Partitioner, Runner, Task, Summarizer — with four stages: configuration construction, inference, evaluation, visualization — [Source](https://arxiv.org/html/2605.19276v2)
- OpenCompass's configuration system accepts Python config files or CLI input, parses/aligns heterogeneous configs into a global evaluation config object, and performs consistency checks on the working directory and data; dataset config comprises data-loading, inference, and evaluation configs — [Source](https://arxiv.org/html/2605.19276v2)
- OpenCompass's Partitioner maps model × dataset requirements to a Cartesian product, splits work into independent atomic subtasks by worker count/dataset size/equal partitioning, and assigns each subtask its own output file path — [Source](https://arxiv.org/html/2605.19276v2)
- OpenCompass's Runner abstracts cluster heterogeneity, tracks subtask status, triggers configurable retries, and manages subtask logs and output files; a Task carries the complete execution information and context of one batch — [Source](https://arxiv.org/html/2605.19276v2)
- OpenCompass separates inference from evaluation: an InferTask dumps predictions, then an EvalTask loads predictions plus dataset gold labels, applies a configurable PostProcessor (format normalization, redundant-information filtering), and passes them to an Evaluator that produces structured evaluation results — [Source](https://arxiv.org/html/2605.19276v2)
- OpenCompass ships rule-based evaluators (option extraction, content regex, LaTeX math parsing, BLEU/ROUGE/AUC-ROC/F1), LLM-as-a-Judge evaluators, and cascade evaluators (rule pre-filter then judge, or parallel with "either says correct → correct"); it reports rule accuracy, judge accuracy, and combined accuracy separately — [Source](https://arxiv.org/html/2605.19276v2)
- OpenCompass's Summarizer aggregates results, uses dataset `abbr` identifiers as unique keys, and supports user-defined summary groups and aggregation rules; its paper notes a current limitation: inference/evaluation for one dataset are serial, with pipeline parallelism across datasets only planned future work — [Source](https://arxiv.org/html/2605.19276v2)
- lm-evaluation-harness uses config-based task creation, Jinja2 prompt design, output post-processing, answer extraction, multiple generations per document, configurable few-shot settings, and external YAML task configs — [Source](https://github.com/EleutherAI/lm-evaluation-harness)
- As of 2026 the lm-eval CLI has subcommands `run`, `ls`, `validate` and YAML config support via `--config`; model backends, filters, metrics, and aggregations can be registered as plugins via `lm_eval.*` entry points instead of forking — [Source](https://github.com/EleutherAI/lm-evaluation-harness)
- lm-eval defines four model request/output types (`generate_until`, `loglikelihood`, `loglikelihood_rolling`, `multiple_choice`); API models without logits/logprobs can only be used with `generate_until` tasks — [Source](https://github.com/EleutherAI/lm-evaluation-harness)
- lm-eval states that evaluation with publicly available prompts ensures reproducibility and comparability between papers, and that "vLLM occasionally differs in output from Huggingface": HF is treated as the reference implementation, with a `scripts/model_comparator.py` validity-check script; ONNX backends have a standing `tests/models/test_onnxruntime_parity.py` check — [Source](https://github.com/EleutherAI/lm-evaluation-harness)
- HELM describes itself as a framework for "holistic, reproducible and transparent evaluation," with standardized datasets, models behind a unified interface, metrics beyond accuracy (efficiency, bias, toxicity), a web UI for inspecting individual prompts and responses, and leaderboards; its README states HELM entered maintenance mode on June 1, 2026 — [Source](https://github.com/stanford-crfm/helm)
- BIG-bench JSON tasks are declarative: required fields are `name`, `description`, `keywords`, `metrics`, `canary`, and `examples` (each `input` plus `target` and/or `target_scores`); optional fields control `task_prefix`, example prefixes, `stop_string`, and `output_regex` — [Source](https://github.com/google/BIG-bench/blob/main/docs/doc.md)
- BIG-bench programmatic tasks return typed `ScoreData` objects carrying `score_dict`, `preferred_score`, `number_of_shots`, and low/high score bounds; tasks expose `TaskMetadata` (max input length, max queries) via `get_task_details()` — [Source](https://github.com/google/BIG-bench/blob/main/docs/doc.md)
- BIG-bench review criteria require correctness (passes unit tests), specificity (justify construction choices in the task README), thoroughness (control for/average over confounders), ≥32 input-output pairs, and explicit justification of what the task measures; it uses a benchmark canary string to reduce training-data contamination — [Source](https://github.com/google/BIG-bench/blob/main/docs/doc.md)
- DVC versions data alongside code via small `.dvc` metadata placeholders containing content hashes (e.g., `md5`), stores data in a cache with remotes (`dvc push`/`dvc pull`), and provides `dvc repro` pipelines, params/metrics/plots tracking, experiment comparison, CI/CD-for-ML scenarios, and an auditable model registry — [Source](https://dvc.org/doc/start)

### Inferences

- Practical decomposition for a small moderation system: (1) immutable `task.yaml`/JSON task specs (id, input schema, gold labels, metric list, preferred metric, example count, canary/version hash); (2) a dataset loader that emits normalized records plus a dataset hash; (3) a model adapter interface with explicit capability declaration (e.g., `returns_scores` vs `returns_text`, `supports_seed`); (4) post-processor → typed outcome → metric functions; (5) a run manifest writer; (6) a summarizer that writes CSV/JSON + figures. This mirrors the OpenCompass/lm-eval/BIG-bench split while staying small [Source: synthesis of the citations above].
- Make the run manifest the unit of reproducibility: `task_spec_hash`, `dataset_hash`, `config_hash`, `code_git_sha`, `model_id` + revision/pinned version, prompt template id, sampler params, seed, library versions, timestamp, and output artifact hashes. DVC's `.dvc` hash placeholders and Git-tracked metadata are a lightweight template for this [Source](https://dvc.org/doc/start).
- Implement two distinct regression gates: (a) **parity gate** — a fixed fixture set where a new backend/implementation must match the reference implementation exactly or within a declared tolerance (lm-eval's comparator and ONNX parity test are the pattern); (b) **self-stability gate** — rerun the identical config twice and require zero symmetric difference in outcomes (Google's Rule #24 explicitly says a model compared with itself should have low, ideally zero, symmetric difference) [Source](https://developers.google.com/machine-learning/guides/rules-of-ml).
- Emit at least three artifact tiers: raw per-item records (inputs, extracted decision, latency, error), aggregate metrics JSON/CSV, and human-readable summary/figures. Keep raw records immutable so figures can be regenerated without re-invoking the model [Source](https://arxiv.org/html/2605.19276v2).
- Treat metric multiplicity honestly: report each evaluator/metric separately (as OpenCompass reports rule/judge/combined accuracy) rather than silently collapsing to a single headline score [Source](https://arxiv.org/html/2605.19276v2).

### Gaps

- I did not find a primary source in the fetched set for a "standard" checklist that mandates a specific regression-gate schedule (e.g., nightly vs per-PR); the recommended gates are inferences from parity/self-comparison practices.
- HELM's detailed schema (Scenario/Model/Adapter/Metric objects) could not be fetched: `https://crfm-helm.readthedocs.io/en/latest/schema/` returned 404. HELM component names are therefore not asserted here.

## What does a decision/runtime harness need to be deterministic and auditable: structured traces, explicit configuration, seeded behavior, no hidden fallbacks, typed outcomes?

### Takeaway

Auditability comes from making every decision input, branch, and outcome an explicit typed record under a pinned config — and from treating silent degradation as a bug. Strong guidance here is mostly engineering discipline: test infrastructure separately, log serving-time inputs, detect silent failures, and check that a system compared with itself produces zero delta.

### Cited Findings

- Google's Rules of ML Rule #5 says to test infrastructure independently from the ML component, encapsulate learning so surrounding code is testable, verify feature columns are populated, and check that a model gives the same score in training and serving environments — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- Rule #10 is explicitly "Watch for silent failures": stale joined tables and dropped feature coverage can degrade behavior gradually while the system keeps operating; tracking data statistics and occasional manual inspection reduces this — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- Rule #6 warns that copied pipelines silently drop needed data (e.g., older posts, unlogged negatives), and Rule #11 calls for owners and documentation for each feature column — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- Rule #29 recommends saving the features used at serving time and piping them into a training log so serving/training consistency can be verified; Rule #31 warns that joined tables can change between training and serving — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- Rule #24 says to measure the delta between models over the same sample, examine cases with the largest symmetric difference, and ensure a model compared with itself has low (ideally zero) symmetric difference — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- Rule #9 says to run sanity checks immediately before exporting a model to serving (e.g., held-out performance) and not to export when concerns remain, because user-facing issues have higher severity — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- Rule #2 says to design and implement metrics before formalizing system behavior, so instrumentation exists rather than requiring "grepping for strings in logs" later; Rule #27 says "measure first, optimize second" by turning qualitative complaints into numbers — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- OpenCompass tasks are the atomic, independently schedulable unit carrying "complete execution information and context," and the Runner manages subtask logs and output files; its config stage performs consistency checks before work begins — [Source](https://arxiv.org/html/2605.19276v2)
- HELM offers a web UI for inspecting individual prompts and responses, which is the concrete audit affordance for per-item decisions — [Source](https://github.com/stanford-crfm/helm)
- NIST AI RMF 1.0 is a voluntary framework for incorporating trustworthiness into design, development, use, and evaluation, organized around Govern, Map, Measure, and Manage; a Generative AI Profile was released July 26, 2024, and as of 2026 the RMF 1.0 is being revised under the White House AI Action Plan — [Source](https://www.nist.gov/itl/ai-risk-management-framework)

### Inferences

- Define a single frozen `RunConfig` dataclass/schema as the only entry point: task id + version, dataset id + hash, policy/rule versions, thresholds, model id + revision, temperature/top_p, seed, timeout, retry policy, fallback policy, and output schema version. Serialize it verbatim into every trace and artifact; refuse to run on unknown keys so typos cannot silently change behavior [Source: inferred from OpenCompass config consistency checks and Rules of ML #2/#6](https://arxiv.org/html/2605.19276v2).
- Trace shape for each decision: `case_id`, `config_hash`, `input_hash` (and redacted input ref), ordered `steps[]` with `{step_id, component, version, started_at, ended_at, inputs_ref, outputs_ref, decision, reason_code}`, terminal `outcome` from a closed enum (e.g., `ALLOW`, `BLOCK`, `REVIEW`, `ERROR_UNAVAILABLE`, `ERROR_TIMEOUT`, `ERROR_INVALID_OUTPUT`), plus `latency_ms` and `model_response_id`. A closed enum is the typed-outcome lesson from BIG-bench's `ScoreData`/`preferred_score` and from OpenCompass's structured evaluator outputs [Source](https://github.com/google/BIG-bench/blob/main/docs/doc.md).
- Determinism recipe: inject an RNG object created from the config seed (never call global `random`), pass it through every stochastic component, record the seed and RNG library version in the manifest, and make replay a separate code path that consumes the saved trace rather than re-calling the model. The self-comparison requirement in Rule #24 is the acceptance test [Source](https://developers.google.com/machine-learning/guides/rules-of-ml).
- No hidden fallbacks: any substitute path (rule-based classifier, cached verdict, different model, default "allow") must be an explicit enum-valued config choice, must appear as its own trace step with a reason code, and must be visible in the aggregate report as a count. This is the direct engineering implication of Rules #6, #10, #11, and #31 [Source](https://developers.google.com/machine-learning/guides/rules-of-ml).
- Separate offline evaluation from runtime decisioning but share the same post-processor/outcome types, so a verdict computed in evaluation and the same verdict in serving are literally the same function (Rules #5 and #32) [Source](https://developers.google.com/machine-learning/guides/rules-of-ml).

### Gaps

- I could not retrieve a primary OpenTelemetry GenAI/LLM semantic-convention page (the attempted URL returned 404), so I make no claims about official span names or attributes; the trace schema above is an inference, not a standard citation.
- No source in this research covered seeded RNG guidance for decision harnesses specifically; the seed recommendation is an inference from the determinism requirement and Rule #24's self-comparison check.
- I found no primary source in this set stating an authoritative "fail-closed vs fail-open" policy for moderation systems; NIST AI RMF is a process framework, not a per-request decision spec [Source](https://www.nist.gov/itl/ai-risk-management-framework).

## How do strong research READMEs and papers communicate claims: what to state, what to omit, how to show limitations, and how to avoid marketing language?

### Takeaway

Credible projects describe what was measured, how, and under which conditions — and they surface caveats next to the numbers. The strongest examples in this research use precise scope statements, separate metrics by evaluator, publish per-item inspection tooling, and state known divergences and limitations explicitly rather than maximizing a headline score.

### Cited Findings

- HELM's README describes the framework in plain, scope-limited terms ("Datasets and benchmarks in a standardized format," "Web UI for inspecting individual prompts and responses") and includes a maintenance-mode notice dated June 1, 2026 rather than presenting the project as perpetually current — [Source](https://github.com/stanford-crfm/helm)
- lm-eval's README explicitly warns that for closed chat APIs users should inspect ~10 sample outputs with `--limit 10` first to confirm answer extraction and scoring work as expected, and that `--device` flags do not function for externally hosted models — [Source](https://github.com/EleutherAI/lm-evaluation-harness)
- lm-eval states HF is the reference implementation and vLLM may differ, and supplies comparison scripts/tests rather than declaring results interchangeable — [Source](https://github.com/EleutherAI/lm-evaluation-harness)
- OpenCompass's paper states objective evaluation is "fully reproducible" only for tasks with definitive gold answers, and that subjective evaluation relies on LLM-as-a-Judge scoring against a reference model; it also explicitly reports cascade modes that trade strictness for cost/tolerance — [Source](https://arxiv.org/html/2605.19276v2)
- OpenCompass's paper publishes a "Future Works" section naming concrete limitations: serial infer→eval within a dataset, no multimodal or multi-turn support at the time of writing — [Source](https://arxiv.org/html/2605.19276v2)
- BIG-bench requires each task README to clearly explain what the task attempts to measure and why it matters, and its review criteria demand specificity, confounder control, and justification of construction choices — [Source](https://github.com/google/BIG-bench/blob/main/docs/doc.md)
- BIG-bench asks task authors to be wary of memorization of internet-visible input/output pairs and to include canary strings in task files — a concrete example of publishing a threat-to-validity caveat rather than implying a clean measurement — [Source](https://github.com/google/BIG-bench/blob/main/docs/doc.md)
- NIST frames AI RMF as voluntary and oriented to trustworthiness across design, development, use, and evaluation; the 2026 revision status is stated openly on the framework's own page — [Source](https://www.nist.gov/itl/ai-risk-management-framework)

### Inferences

- README structure that reads as research rather than marketing: (1) one-sentence scope statement ("a rule-based moderation decision harness evaluated on X"); (2) exactly what is claimed and the conditions (dataset version, model revision, seed, thresholds); (3) a table of metrics with denominators and confidence intervals/uncertainty; (4) "What this does not measure" bullet list; (5) "Failure modes observed" with counts; (6) exact reproduce command and artifact hashes; (7) citation/license; no adjective-only claims such as "state-of-the-art," "robust," "production-grade," or "safe" without an operational definition [Source: synthesis of HELM/lm-eval/OpenCompass/BIG-bench examples above].
- Omit: unreproducible numbers, metric averages without per-task breakdown, claims about real-world safety that the evaluated dataset cannot support, and any fallback/substitute result presented as if it came from the primary model. If a number is from a judge or rule-based proxy, name it as such (OpenCompass's separate accuracies are the model) [Source](https://arxiv.org/html/2605.19276v2).
- Show limitations as data, not adjectives: report counts of `ERROR_UNAVAILABLE`, `REVIEW`, judge-vs-rule disagreements, examples with changed extraction, and dataset contamination/canary status. The BIG-bench review criteria and OpenCompass "Future Works" are precedents for making limitations specific and checkable [Source](https://github.com/google/BIG-bench/blob/main/docs/doc.md).
- Distinguish three audiences in one document: reproduction instructions (exact commands + hashes), interpretability aids (per-item trace viewer / sample outputs as HELM and lm-eval recommend), and claim scope (what the metrics license you to say) [Source](https://github.com/stanford-crfm/helm).

### Gaps

- I could not retrieve venue-specific author/reviewer guidance: the attempted NeurIPS 2025 reviewer-instructions URL returned 404. I therefore make no claims about NeurIPS/ACL checklist requirements.
- I did not retrieve the Model Cards paper or a reputable lab research README beyond the harness projects above, so there is no sourced citation for a generic "Limitations section" template; the suggested README structure is an inference from project examples.
- No source in this set gives quantitative guidance on how many seeds or bootstrap replicates to report; uncertainty treatment beyond "report denominators" is left as an inference.

## What are best practices for generating figures/GIFs from system traces for documentation, and for keeping generated artifacts reproducible?

### Takeaway

Generate visuals as a pure, deterministic render of an immutable trace file: fixed frame order, explicit timing and disposal parameters, pinned encoder/library versions, and a regenerated artifact hash. Pillow's GIF API and DVC's hash-versioned artifacts supply the concrete mechanisms.

### Cited Findings

- Pillow reads GIF87a/GIF89a and writes GIF87a by default unless GIF89a features are used; multi-frame output uses `im.save(out, save_all=True, append_images=[...])` — [Source](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif)
- Pillow GIF `duration` is per-frame display time in milliseconds and accepts one integer for constant duration or a list/tuple for per-frame durations; `loop=0` means loop forever, and omitting/None means no loop — [Source](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif)
- Pillow GIF `disposal` controls post-display treatment with values 0 (unspecified), 1 (do not dispose), 2 (restore to background), 3 (restore to previous content), and can be a single integer or per-frame list; `optimize` attempts palette compression and marking unchanged pixels transparent, and is on by default unless a palette is supplied — [Source](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif)
- Pillow exposes a `comment` save option for GIFs, and GIF `info` may carry `duration`, `loop`, and `comment` metadata — [Source](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif)
- When an image originates from an existing GIF, options not explicitly passed to `save()` default to the values in its `info` dictionary — a source of implicit, non-reproducible behavior — [Source](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif)
- DVC tracks data via small `.dvc` metadata files containing content hashes and versions that metadata in Git while the payload lives in a cache/remote; it provides reproducible pipelines (`dvc repro`), tracked metrics/params/plots, and CI/CD-for-ML workflows — [Source](https://dvc.org/doc/start)
- HELM's leaderboard/README workflow separates `helm-run` (produce run data), `helm-summarize` (aggregate), and `helm-server` (inspect), which is a trace→artifact→presentation pipeline with inspectable intermediate state — [Source](https://github.com/stanford-crfm/helm)

### Inferences

- Render pipeline: `trace.jsonl` (immutable) → `frames/*.png` (one deterministic frame per trace event or decision step, laid out from fixed field order and a fixed font/theme) → `trace.gif`. Never sample from a live process or wall-clock; derive frame index from the trace's monotonic `step_index`, not timestamps. This follows from Pillow's explicit per-frame duration/loop/disposal controls [Source](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif).
- Pin all encoder parameters in code/config: `duration=...`, `loop=0` or `None` deliberately, `disposal=2` (or explicit per-frame list) to avoid ghost frames, `optimize` explicitly True/False, `palette` if a fixed palette matters, and a fixed `comment` containing the `trace_sha256` and config hash. Because Pillow inherits omitted options from source-image `info`, always pass values explicitly [Source](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif).
- Ship a `make figures` target that regenerates from the saved trace and asserts the output SHA-256 matches the value recorded in the run manifest. DVC's hash-based `.dvc` placeholders plus Git-tracked metadata are a direct way to do this without storing binaries in Git [Source](https://dvc.org/doc/start).
- Keep figure generation separate from evaluation so adding a caption or changing colors cannot invalidate results: HELM's run/summarize/server separation is the architectural precedent [Source](https://github.com/stanford-crfm/helm).
- Include a static PNG first frame alongside the GIF so documentation remains readable where animation is unsupported; generate both in the same pass from the same frame buffer [Source: inference from Pillow GIF/PNG save options](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif).

### Gaps

- I did not fetch imageio/imageio.v3 documentation, so I make no claims about its `fps`/`loop` APIs or about GIF byte-level determinism across Pillow/imageio versions.
- No source in this set quantifies whether GIF output is byte-identical across Pillow versions; pinning the library version and hashing the output is a mitigation, not a verified guarantee.
- I found no sourced guidance specific to animating *moderation decision traces*; the frame-design advice is a direct inference from generic GIF mechanics.

## How do projects handle model unavailability honestly (no silent fallbacks) while remaining safe in production?

### Takeaway

The defensible pattern is: declare substitute behavior explicitly in config, expose it in traces and reports, verify it before it ships, and prefer a deliberately degraded but well-understood path over an undocumented improvised one. Published engineering guidance warns sharply about silent failures and unreported data changes.

### Cited Findings

- Google's Rule #1 says not to be afraid to launch without machine learning: heuristics can capture much of the value when data is lacking — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- Rule #7 lists "Preprocess using the heuristic" as a legitimate explicit design (e.g., a blacklisted sender is blocked outright rather than re-learned), alongside using heuristics as features or modifying labels — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- Rule #9 advises sanity-checking before export and withholding a model when concerns remain; Rule #10 warns that silent failures decay quality gradually and may go unnoticed for months — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- Rule #33 says to test a model on data gathered after its training cutoff (train through Jan 5, test Jan 6 onward) because it better reflects production behavior; Rule #34 warns about sampling bias when filtering hides negatives and suggests a small held-out traffic slice for clean labels — [Source](https://developers.google.com/machine-learning/guides/rules-of-ml)
- lm-eval documents that externally hosted models ignore local-placement flags and recommends a specific self-hosted path (`local-completions` with vLLM's OpenAI-compatible API) for a 405B model — i.e., capability constraints are stated rather than papered over — [Source](https://github.com/EleutherAI/lm-evaluation-harness)
- OpenCompass requires a fallback-free evaluation contract in its own design: rule-based evaluation is "fully reproducible" for gold-answer tasks; when rule-based judgment is incomplete it offers a cascade with explicitly reported rule accuracy, judge accuracy, and combined accuracy, and requires objective-correctness criteria — [Source](https://arxiv.org/html/2605.19276v2)
- NIST AI RMF is voluntary and organized around Govern/Map/Measure/Manage for trustworthiness across the AI lifecycle; its GenAI Profile (July 26, 2024) exists to identify generative-AI-specific risks — [Source](https://www.nist.gov/itl/ai-risk-management-framework)

### Inferences

- Encode availability as a typed outcome, not an exception swallowed upstream: `ERROR_UNAVAILABLE` / `ERROR_TIMEOUT` / `ERROR_INVALID_OUTPUT` are first-class results in the trace and in aggregate metrics, with `reason_code`, model id, attempt count, and elapsed time. Never let an exception map silently to `ALLOW`.
- If a fallback is required for safety, make it a named, versioned policy object (e.g., `fallback_policy: "conservative_rule_v2"`), require it to appear as a trace step, and report `fallback_used_count` and its own measured precision/recall on the same eval set. Rule #7's explicit heuristic preprocessing and OpenCompass's separately reported cascade components are the precedents [Source](https://developers.google.com/machine-learning/guides/rules-of-ml).
- Decide fail-closed vs fail-open per action, in writing, in the config and README: for a moderation system, an unavailable classifier can route to `REVIEW` or `BLOCK` under a named policy, but the choice must be an auditable experiment result, not an implicit default. Some systems legitimately choose an ML-free heuristic launch (Rule #1) — the honesty requirement is that the chosen path is named [Source](https://developers.google.com/machine-learning/guides/rules-of-ml).
- Gate any fallback behind a pre-export check (Rule #9) and a post-deployment monitor for silent failures (Rule #10): track drift in outcome distribution, fallback rate, and feature coverage; alert when a fallback rate moves without a config change. Evaluate on a temporally held-out split (Rule #33) so unavailability handling is tested on data resembling production.
- Report degraded-mode results separately in the README: a table with rows `primary model available`, `model unavailable → named policy`, and `mixed`, each with counts and metrics. Do not average them into one number — OpenCompass's separate rule/judge/combined reporting is the model [Source](https://arxiv.org/html/2605.19276v2).

### Gaps

- I found no primary source in this set giving an authoritative, domain-specific moderation policy for fail-open vs fail-closed under model outage; that decision must be made by the project owners and recorded explicitly.
- OWASP LLM Top 10 and production SRE guidance on graceful degradation were not retrieved; claims about industry-standard fallback patterns are therefore omitted.
- No source in this set provided empirical data on how often silent fallbacks occur in moderation systems; the recommendation is precautionary, based on Rules #6/#10/#31.
