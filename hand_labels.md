# Hand labels — extraction schema + test set

Written before Step 4 (LLM extraction) exists. Purpose: force the entity/relation
schema decisions on real abstracts from `data/papers.jsonl` *before* writing a
single extraction prompt, and produce a small gold set the extractor's output can
be diffed against (precision/recall on these 5 before trusting it on the other
11,605 papers).

Extraction (Step 4) is only ever run on the pre-cutoff graph and, separately, on
the post-cutoff eval papers for ground-truth matching (EVAL.md) — never used to
rank candidates. See EVAL.md for why.

## Entity types (7)

| Type | What it captures | Examples from this set |
|---|---|---|
| `Method` | A named technique, algorithm, system, or training procedure. | SmoothQuant, oBERT, speculative decoding, deep task-based quantization, Quadapter, quantization-aware training |
| `ModelFamily` | The model/architecture class a method is applied to. | LLM, BERT, GPT-2, T5-XXL, Transformer, MIMO receiver |
| `Task` | The downstream problem being solved. | autoregressive decoding, MIMO channel estimation, symbol detection |
| `Metric` | A quantity used to evaluate success or cost. | inference speed, model size, task accuracy, bit error rate |
| `Resource` | A hardware/system constraint the method targets or consumes. | GPU memory, CPU, edge device, scalar ADC, single node |
| `Dataset/Benchmark` | A named evaluation dataset or benchmark. | (none forced by this set — see note below) |
| `Phenomenon` | An observed characteristic, side effect, or failure mode. Not a method, not a metric — a *thing that happens*. | activation outlier, quantization error, overfitting, accuracy–compression trade-off |

Note: none of the 5 abstracts happened to name a specific benchmark (they report
relative numbers — "1.56x speedup", "<1% accuracy drop" — not e.g. "WikiText-2").
`Dataset/Benchmark` stays in the schema because later batches will hit it
constantly (GLUE, WikiText, C4...); it just isn't exercised by this test set.
Flagged here rather than quietly dropped.

## Relation types (10)

| Relation | Direction | Meaning |
|---|---|---|
| `APPLIES_TO` | Method → ModelFamily \| Task \| Resource | Method is used on/for this target. |
| `IMPROVES` | Method → Metric | Method makes this metric better. |
| `DEGRADES` | Method → Metric | Method makes this metric worse (a cost the method pays). |
| `REDUCES` | Method → Resource \| Metric | Method lowers consumption of a resource or a cost-metric (memory, bit error rate). |
| `CAUSES` | Phenomenon → Phenomenon | One observed effect produces another. |
| `MITIGATES` | Method → Phenomenon | Method exists specifically to counteract a phenomenon. |
| `FAILS_AT` | Method → Task \| Phenomenon | **Limitation edge, first-class.** Method breaks down under a named condition. |
| `EXTENDS` | Method → Method | Method is built directly on top of a named prior method. |
| `COMBINES_WITH` | Method → Method (symmetric) | Methods are composed/stacked together. |
| `APPROXIMATES` | Method → Method \| ModelFamily | Method stands in for a more expensive method/model and inherits its target behavior. |

`FAILS_AT` is kept separate from `DEGRADES` on purpose: `DEGRADES` is a
quantified cost the authors accept ("<1% accuracy drop"); `FAILS_AT` is a
qualitative breakdown condition ("overfits when the original fine-tuning
pipeline isn't available"). Collapsing them would bury exactly the edges this
whole project cares about — limitations are where bridges hide, because a
limitation in field A is often already solved in field B.

## Properties vs. entities

Precision/format values (`INT8`, `W8A8`, `4-bit`, `FP16`) are **properties on
`Method` nodes**, not entities. Reasoning: `INT8` on its own has no citation
context, can't be a bridge endpoint, and would otherwise silently merge dozens
of unrelated methods that happen to share a bit-width. Same treatment for
speedup/compression magnitudes ("1.56x", "10x") — these are edge properties
(e.g. `IMPROVES.magnitude`), not nodes.

## Canonicalization

Entities are stored as `snake_case` canonical IDs with a `surface_forms` list
for aliases seen in the text, e.g. `quantization_error` with surface forms
`["not easy to quantize", "quantization difficulty", "large quantization
error"]`. This was forced by abstract 1 and abstract 5 independently describing
the same phenomenon in different words (see below) — without canonicalization
the recurring `CAUSES` edge that makes this a real signal would look like two
unrelated one-off edges.

---

## Labeled abstracts

### 1. SmoothQuant (2211.10438, 2022, core)

> Large language models (LLMs) show excellent performance but are compute- and
> memory-intensive. Quantization can reduce memory and accelerate inference.
> However, existing methods cannot maintain accuracy and hardware efficiency at
> the same time. We propose SmoothQuant, a training-free, accuracy-preserving,
> and general-purpose post-training quantization (PTQ) solution to enable 8-bit
> weight, 8-bit activation (W8A8) quantization for LLMs. Based on the fact that
> weights are easy to quantize while activations are not, SmoothQuant smooths
> the activation outliers by offline migrating the quantization difficulty from
> activations to weights with a mathematically equivalent transformation.
> SmoothQuant enables an INT8 quantization of both weights and activations for
> all the matrix multiplications in LLMs [...]. We demonstrate up to 1.56x
> speedup and 2x memory reduction for LLMs with negligible loss in accuracy.

**Entities:** `SmoothQuant` (Method; `precision=W8A8/INT8`, `training_required=false`),
`LLM` (ModelFamily), `activation_outlier` (Phenomenon), `quantization_error`
(Phenomenon), `memory` (Resource), `inference_speed` (Metric)

**Triples:**
1. `(SmoothQuant, APPLIES_TO, LLM)`
2. `(SmoothQuant, MITIGATES, activation_outlier)`
3. `(activation_outlier, CAUSES, quantization_error)`
4. `(SmoothQuant, REDUCES, memory)` — magnitude: 2x
5. `(SmoothQuant, IMPROVES, inference_speed)` — magnitude: 1.56x

### 2. The Optimal BERT Surgeon (2203.07259, 2022, core)

> Transformer-based language models [...] can be too large and computationally
> intensive to run on standard deployments. A variety of compression methods,
> including distillation, quantization, structured and unstructured pruning are
> known to decrease model size and increase inference speed, with low accuracy
> loss. [...] We introduce Optimal BERT Surgeon (oBERT), an efficient and
> accurate weight pruning method based on approximate second-order information
> [...] oBERT extends existing work on unstructured second-order pruning by
> allowing for pruning blocks of weights, and by being applicable at the BERT
> scale. [...] we investigate the impact of this pruning method when compounding
> compression approaches to obtain highly compressed but accurate models for
> deployment on edge devices. [...] relative to the dense BERT-base, we obtain
> 10x model size compression [...] with < 1% accuracy drop, 10x CPU-inference
> speedup with < 2% accuracy drop, and 29x CPU-inference speedup with < 7.5%
> accuracy drop.

**Entities:** `oBERT` (Method), `second_order_pruning` (Method), `pruning`
(Method, generic/background), `BERT` (ModelFamily), `edge_device` (Resource),
`model_size` (Metric), `inference_speed` (Metric), `task_accuracy` (Metric)

**Triples:**
1. `(oBERT, APPLIES_TO, BERT)`
2. `(oBERT, EXTENDS, second_order_pruning)`
3. `(oBERT, REDUCES, model_size)` — magnitude: 10x
4. `(oBERT, IMPROVES, inference_speed)` — magnitude: 10x–29x
5. `(oBERT, DEGRADES, task_accuracy)` — magnitude: <1%–7.5%, paired with the speed/size gain above (accuracy–compression trade-off)
6. `(oBERT, APPLIES_TO, edge_device)`
7. `(pruning, REDUCES, model_size)` — background claim, not oBERT-specific; kept because generic-method claims are exactly what lets a bridge search connect this paper to others that only mention "pruning" in the abstract, not oBERT by name.

### 3. Fast Inference from Transformers via Speculative Decoding (2211.17192, 2022, core)

> Inference from large autoregressive models like Transformers is slow [...]
> speculative decoding [...] hard language-modeling tasks often include easier
> subtasks that can be approximated well by more efficient models, and [...]
> using speculative execution and a novel sampling method, we can make exact
> decoding from the large models faster, by running them in parallel on the
> outputs of the approximation models [...] We demonstrate it on T5-XXL and show
> a 2X-3X acceleration [...] with identical outputs.

**Entities:** `speculative_decoding` (Method), `draft_model` (Method — the
"approximation model"), `Transformer` (ModelFamily), `T5_XXL` (ModelFamily),
`autoregressive_decoding` (Task), `inference_speed` (Metric)

**Triples:**
1. `(speculative_decoding, APPLIES_TO, autoregressive_decoding)`
2. `(speculative_decoding, APPLIES_TO, T5_XXL)`
3. `(speculative_decoding, IMPROVES, inference_speed)` — magnitude: 2x–3x
4. `(draft_model, APPROXIMATES, Transformer)`
5. `(speculative_decoding, COMBINES_WITH, draft_model)`

### 4. Deep Task-Based Quantization (1908.06845, 2019, **ring**)

> Quantizers play a critical role in digital signal processing systems. [...]
> the performance of quantization systems acquiring multiple analog signals
> using scalar analog-to-digital converters (ADCs) can be significantly
> improved by properly processing the analog signals prior to quantization.
> [...] we design data-driven task-oriented quantization systems with scalar
> ADCs [...] using deep learning tools. [...] Our main target application is
> multiple-input multiple-output (MIMO) communication receivers [...] the
> proposed deep task-based quantizer is capable of approaching the optimal
> performance limits dictated by indirect rate-distortion theory, achievable
> using vector quantizers and requiring complete knowledge of the underlying
> statistical model. Furthermore, for a symbol detection scenario [...] to
> minimize the bit error rate.

**Entities:** `deep_task_based_quantization` (Method; `hardware=scalar_ADC`,
`requires_full_statistical_model=false`), `vector_quantizer` (Method;
`requires_full_statistical_model=true`), `MIMO_receiver` (ModelFamily),
`MIMO_channel_estimation` (Task), `symbol_detection` (Task),
`bit_error_rate` (Metric)

**Triples:**
1. `(deep_task_based_quantization, APPLIES_TO, MIMO_channel_estimation)`
2. `(deep_task_based_quantization, APPLIES_TO, symbol_detection)`
3. `(deep_task_based_quantization, APPROXIMATES, vector_quantizer)`
4. `(deep_task_based_quantization, REDUCES, bit_error_rate)`

**Why this one's in the set:** it's a ring paper, chosen specifically to
pressure-test whether the schema built on core LLM papers survives contact with
signal-processing quantization. It does, cleanly — `APPLIES_TO`,
`APPROXIMATES`, `REDUCES` all transfer with no new relation types needed. More
interesting: `vector_quantizer` here is evaluated against "indirect
rate-distortion theory" as an optimality bound, which is the same
accuracy-vs-compression argument SmoothQuant and oBERT make in the core set,
just in information-theory vocabulary instead of ML vocabulary. That
terminology gap — same underlying trade-off, different field's word for it — is
the exact shape of bridge this project is built to surface. It's also a
concrete instance of the thing the corpus design bet on: "quantization" spans
communities, and the ring pull was there to catch this on purpose.

### 5. Quadapter: Adapter for GPT-2 Quantization (2211.16912, 2022, ring)

> Transformer language models such as GPT-2 are difficult to quantize because
> of outliers in activations leading to a large quantization error. To adapt to
> the error, one must use quantization-aware training, which entails a
> fine-tuning process [...] Pretrained language models, however, often do not
> grant access to their datasets and training pipelines, forcing us to rely on
> arbitrary ones for fine-tuning. In that case, it is observed that
> quantization-aware training overfits the model to the fine-tuning data. For
> quantization without overfitting, we introduce a quantization adapter
> (Quadapter), a small set of parameters that are learned to make activations
> quantization-friendly by scaling them channel-wise. It keeps the model
> parameters unchanged.

**Entities:** `Quadapter` (Method; `modifies_base_weights=false`),
`quantization_aware_training` (Method), `GPT2` (ModelFamily),
`activation_outlier` (Phenomenon), `quantization_error` (Phenomenon),
`overfitting` (Phenomenon)

**Triples:**
1. `(Quadapter, APPLIES_TO, GPT2)`
2. `(activation_outlier, CAUSES, quantization_error)` — **same edge as abstract 1**, independently stated. This is the pair that forced canonicalization (see above): abstract 1 says "not easy to quantize" / "quantization difficulty", abstract 5 says "large quantization error" — same phenomenon, different phrasing, and without folding them into one canonical ID this recurring signal is invisible.
3. `(quantization_aware_training, FAILS_AT, overfitting)` — the limitation edge. Only triggers when the original fine-tuning pipeline is unavailable — a conditional limitation, not universal, but `FAILS_AT` doesn't currently carry a condition slot. Noted as an open schema question below.
4. `(Quadapter, MITIGATES, overfitting)`
5. `(Quadapter, MITIGATES, activation_outlier)`

---

## Schema decisions this exercise forced

- **`FAILS_AT` needed a condition slot — resolved in extract.py.** oBERT's
  degradation is unconditional; Quadapter's QAT failure is conditional ("when
  the original pipeline isn't available"). The extraction schema in
  `extract.py` gives every triple a nullable `condition` field, populated only
  for `FAILS_AT` edges, so this distinction survives extraction instead of
  being flattened away.
- **Generic background claims are worth keeping**, not just claims about the
  paper's own named method (`pruning REDUCES model_size` in abstract 2). These
  are what let two papers that never cite each other and never share a named
  method still connect through a shared generic-method node.
- **The recurring `CAUSES` edge (abstracts 1 and 5) is the whole thesis in
  miniature**: two papers, same underlying claim, different words, connected
  only because canonicalization pulled the surface forms together. If the
  extractor can't reliably canonicalize, the rest of the pipeline inherits that
  failure silently — this is the first thing to check extraction output
  against.
- **The ring abstract (4) didn't need a single schema change.** Some comfort
  that 7 entity types / 10 relations is enough coverage before scaling to
  11,610 papers — though n=1 ring abstract is a weak sample; worth watching as
  Step 4 runs wider.
