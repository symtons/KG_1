# EVAL_RESULTS.md — Step 7 results

Applies EVAL.md's matching rule (co-mention OR bridge-citation, no partial
credit) to the four rankings over the same 1,365-pair candidate pool
`rank.py` produced (see `eval.py`'s docstring for the two operational
clarifications this required — EVAL.md itself is unedited). Every hit
below was read by hand against its evidence before counting, per EVAL.md's
manual-verification requirement — the raw automated numbers are not the
result; the table at the bottom is.

## Headline numbers

Manually-verified precision, same 1,365-candidate pool, same matching
rule, same verification standard, top 20 read per method:

| Method | precision@10 | precision@20 | raw automated hits@20 (before manual check) |
|---|---:|---:|---:|
| **System** (structural + FAILS_AT/cross-origin bonuses) | **0.40** (4/10) | **0.45** (9/20) | 15/20 |
| Adamic-Adar (raw, no bonuses) | 0.30 (3/10) | 0.40 (8/20) | 14/20 |
| Random (shuffle, seed 42) | 0.40 (4/10) | 0.40 (8/20) | 13/20 |
| Similarity (local embeddings, no graph) | 0.10 (1/10) | 0.05 (1/20) | 18/20 |

## What this actually shows — three findings, not one

**1. System beats Adamic-Adar, on both cuts.** The FAILS_AT and
cross-origin bonuses (RANKING.md) are doing real, if modest, work — this
is the core "sweet-spot ranking logic adds value beyond generic
common-neighbor weighting" claim, and it holds. Margin is 10 points @10,
5 points @20 — real, but not overwhelming, at n=20.

**2. System barely beats Random, and only at @20.** This is the honest,
slightly humbling result, and it says something specific: *within a pool
already pre-filtered to established, structurally-bridged pairs*, the
extra scoring on top of that filter isn't adding dramatically more signal
than blind luck would at this sample size. Read generously, that's not
"the ranker doesn't work" — it's "the candidate-*generation* filter
(non-hub relation-graph bridging, established-ness, the co-mention
exclusion) is where most of the real work happens, more than the specific
scoring formula on top of it." That's a different, narrower claim than the
one implicitly being tested, and EVAL.md said explicitly that a result
like this — losing to (or barely beating) one baseline but not others — is
"a useful, specific result, not just a bad outcome to hide." This is that
case.

**3. System beats Similarity by a wide margin, and the reason why is the
most interesting finding of this eval.** Before manual verification,
Similarity had the *highest* raw automated hit rate of all four methods
(18/20) — it looked like the best method. After verification, it collapsed
to 1/20. The gap is almost entirely near-synonym pairs: `dnn`↔`transformer`
via `deep_neural_network`, `nlp`↔`nlp_tasks`, `plm`↔`pretrained_language_
model`, `distributed_sgd`↔`sgd`, and similar — pairs that are the *same
underlying concept* under different surface phrasing, which embedding
similarity is maximally sensitive to and which are structurally guaranteed
to look "confirmed" by any co-mention/citation check, because they're
practically never discussed *without* each other. This is exactly what
EVAL.md's manual-verification requirement exists to catch, and it caught
it — a naive automated report would have shown Similarity *beating*
System, which would have been a real, embarrassing, and completely
artifactual result to have missed. This is also the clearest, most direct
evidence for "structure over similarity" as a real differentiator, not
marketing: structure doesn't have this failure mode, because the relation
graph doesn't preferentially connect synonyms the way an embedding space
does.

## Cross-cutting issue: near-synonym contamination

The same root cause — Step 4's controlled vocabulary (`extract.py`) only
pinned ~26 hub terms, so generic ML terminology outside that list had no
canonicalization guarantee — shows up as false positives in System and
Adamic-Adar too (`deep_neural_network`↔`transformer`,
`deep_neural_network`↔`dnn`, `deep_generative_prior`↔`generative_prior`),
just far less severely than in Similarity. This was flagged as a known,
unfixed limitation in `RANKING.md` after Step 6; Step 7's manual pass
confirms it's a real, material effect on precision, concentrated most
heavily in the similarity baseline specifically because embedding
similarity is the method most sensitive to synonymy. An entity-resolution
pass (embedding-based clustering of surface forms, or a broader
controlled vocabulary) would likely raise every method's *true* precision
by removing these before scoring — noted as a natural next improvement,
not fixed here.

## Manual verification log

`[HIT]` / `[miss]` = automated matching rule result. **verdict** = manual
call. Reasoning given only for non-obvious calls; straightforward
confirms/misses are listed without comment. Full evidence (paper titles,
IDs) is in `data/eval_automated.json` — this log is the judgment applied
on top of it.

### System (top 20)

| # | Pair | Auto | Verdict | Why |
|---|---|---|---|---|
| 1 | causal_rate_distortion_function ↔ nonanticipative_rate_distortion_function | miss | — | |
| 2 | deep_neural_network ↔ transformer | HIT | **reject** | synonym — a transformer *is* a DNN |
| 3 | knowledge_distillation ↔ mixed_precision_quantization | HIT | **confirm** | post-cutoff paper explicitly combines both as one method |
| 4 | knowledge_distillation ↔ super_resolution | HIT | **confirm** | KD applied to a vision detail-restoration task |
| 5 | image_compression ↔ natural_images | miss | — | |
| 6 | compressed_sensing ↔ vector_quantizer | HIT | **confirm** (weak) | real co-occurrence in a wireless-compression paper, but the two are already adjacent within signal processing — not a strong "structural hole" |
| 7 | deep_learning ↔ knowledge_distillation | HIT | **reject** | subsumption, not a bridge — KD *is* a deep learning technique |
| 8 | attention_head_pruning ↔ gradient_compression | miss | — | |
| 9 | compressed_sensing ↔ knowledge_distillation | HIT | **reject** | bridge-citation only, no co-mention; thin single-citation evidence, no clear mechanistic link |
| 10 | attention_head_pruning ↔ mixture_of_experts | HIT | **confirm** (strong) | "MoH: Multi-Head Attention as Mixture-of-Head Attention" literally reframes head-pruning/selection as MoE-style routing |
| 11 | efficient_attention ↔ rnn | HIT | **confirm** (strong) | RWKV — a real, well-known paper explicitly reconciling RNN recurrence with Transformer-level efficient attention |
| 12 | deep_neural_network ↔ dnn | HIT | **reject** | literal acronym of the same term |
| 13 | deep_generative_model ↔ generative_model | miss | — | |
| 14 | autoencoder ↔ mixture_of_experts | HIT | **confirm** (weak) | one clearly on-topic paper ("Superposition in Transformers... Building MoE"), one likely-coincidental fraud-detection paper |
| 15 | dimension_reduction ↔ dimensionality_reduction | miss | — | (also a synonym pair — happens to miss automatically) |
| 16 | multi_head_attention ↔ quantization | HIT | **confirm** (strong) | multiple real, specific papers on quantizing multi-head/KV-cache attention |
| 17 | attention_head_pruning ↔ quantization | HIT | **confirm** | real but a fairly standard "combine two compression techniques" pairing |
| 18 | deep_generative_prior ↔ generative_prior | HIT | **reject** | near-synonym |
| 19 | language_modelling ↔ neural_network | HIT | **reject** | subsumption — language models *are* neural networks |
| 20 | active_learning ↔ compressed_sensing | HIT | **confirm** (strong) | direct combination paper: "Active Learning for Conditional Generative Compressed Sensing" |

**Confirmed: 9/20 (4/10 in top 10).**

### Adamic-Adar (top 20)

Rows 1–9 overlap heavily with System (same base score, no bonuses) —
verdicts carried over unchanged. New pairs only:

| # | Pair | Auto | Verdict | Why |
|---|---|---|---|---|
| 10 | dnn ↔ neural_network | HIT | **reject** | near-synonym |
| 12 | pruning ↔ vector_quantizer | HIT | **confirm** | well-evidenced across several unified-compression papers |
| 13 | lossy_compression ↔ vq_vae | HIT | **confirm** (weak) | VQ-VAE is close to definitionally a form of lossy compression — real but not surprising |
| 14 | plm ↔ pretrained_language_model | HIT | **reject** | literal acronym |
| 16 | rate_distortion_theory ↔ vq_vae | HIT | **confirm** (strong) | multiple papers explicitly reformulating VQ-VAE through a rate-distortion / information-theoretic lens |
| (18, 20) | attention_head_pruning↔mixture_of_experts; autoencoder↔mixture_of_experts | HIT | confirm (as in System) | |

**Confirmed: 8/20 (3/10 in top 10).**

### Random (top 20)

| # | Pair | Auto | Verdict | Why |
|---|---|---|---|---|
| 1 | backpropagation ↔ differential_privacy | miss | — | |
| 2 | resource_constrained_device ↔ transformer | HIT | **confirm** | real, substantive, if unsurprising (this pairing is extremely common in efficient-inference literature) |
| 3 | computational_cost ↔ sample_complexity | HIT | **reject** | single thin bridge-citation, no clear link |
| 4 | entropy_coding ↔ lossy_source_coding | HIT | **confirm** | distinct, related info-theory concepts, substantively co-mentioned |
| 5–6 | (misses) | miss | — | |
| 7 | inverse_problems ↔ posterior_sampling | HIT | **confirm** (strong) | multiple real diffusion-model-for-inverse-problems papers |
| 8 | compression ↔ lasso | HIT | **confirm** | LASSO is a standard tool used within compression/CS |
| 9 | channel_capacity ↔ uniform_quantization | miss | — | |
| 10 | gradient_descent ↔ information_theoretic_lower_bound | HIT | **reject** | thin single-citation, no obvious mechanistic link |
| 11 | accuracy_degradation ↔ resource_constrained_environment | HIT | **confirm** (strong) | well-evidenced low-precision/accuracy tradeoff literature |
| 12 | channel_capacity ↔ privacy_utility_tradeoff | miss | — | |
| 13 | classification ↔ random_projection | HIT | **confirm** | standard, substantive dimensionality-reduction-for-classification pairing |
| 14 | image_reconstruction ↔ non_convex_optimization | HIT | **confirm** | well-established real technical pairing in imaging/CS, thin single-citation evidence but domain-standard |
| 15 | error_feedback ↔ variational_autoencoder | miss | — | |
| 16 | generalization_bound ↔ quantization | HIT | **reject** | plausibly coincidental co-mention in ML-theory papers not obviously about quantization |
| 17 | channel_coding ↔ distributed_source_coding | HIT | **confirm** | adjacent classic info-theory subfields, substantively linked |
| 18–20 | (misses) | miss | — | |

**Confirmed: 8/20 (4/10 in top 10).**

### Similarity (top 20)

| # | Pair | Auto | Verdict | Why |
|---|---|---|---|---|
| 1 | lossy_source_coding ↔ source_coding | HIT | **reject** | synonym/subsumption |
| 2 | natural_language_understanding ↔ nlp_tasks | HIT | **reject** | synonym |
| 3 | machine_translation ↔ neural_machine_translation | HIT | **reject** | synonym |
| 4 | distributed_sgd ↔ sgd | HIT | **reject** | subsumption |
| 5 | llm ↔ pretrained_language_model | HIT | **reject** | near-synonym in this corpus's usage |
| 6 | wyner_ziv_coding ↔ wyner_ziv_problem | HIT | **reject** | same named problem, different phrasing |
| 7 | nlp ↔ nlp_tasks | HIT | **reject** | synonym |
| 8 | deep_neural_network ↔ dnn | HIT | **reject** | acronym |
| 9 | distributed_sgd ↔ error_feedback | HIT | **confirm** (strong) | genuinely distinct concepts, well-evidenced in federated-gradient-compression literature — **the only real hit in this list** |
| 10 | inverse_problems ↔ linear_inverse_problem | HIT | **reject** | subsumption |
| 11 | natural_language_understanding ↔ nlp | HIT | **reject** | synonym |
| 12 | error_compensation ↔ error_feedback | HIT | **reject** | synonym |
| 13 | computation_cost ↔ compute_cost | HIT | **reject** | literal synonym |
| 14 | edge_device ↔ mobile_device | HIT | **reject** | heavy overlap/near-synonym in this corpus's usage |
| 15 | computation_cost ↔ computational_overhead | HIT | **reject** | synonym |
| 16 | reconstruction_accuracy ↔ reconstruction_performance | miss | — | (also a synonym pair) |
| 17 | plm ↔ pretrained_language_model | HIT | **reject** | acronym |
| 18 | measurement_complexity ↔ number_of_measurements | HIT | **reject** | near-tautological in CS terminology |
| 19 | convergence ↔ convergence_rate | miss | — | (also near-synonym) |
| 20 | signal_reconstruction ↔ sparse_signal_recovery | miss | — | (also near-synonym) |

**Confirmed: 1/20 (1/10 in top 10).**

## Limitations of this eval run

- **n=20 per method is small.** Precision at this scale has wide
  uncertainty — a single flipped judgment call moves precision@10 by 10
  points. These numbers describe *this* top-20, not a stable long-run
  rate. A larger manual-verification pass (top 50–100) would tighten this
  considerably before treating the System-vs-Random gap as established.
- **Manual verification here was done by one reader (me), not
  independently cross-checked.** Several calls were genuinely borderline
  (marked "weak" above) and a second reader could reasonably flip a few of
  them by a point or two in either direction — unlikely to change the
  overall ranking of methods, given the size of the gaps involved (System
  vs. Similarity in particular is not close).
- **"Same candidate pool" for all four methods** (see `eval.py`'s
  docstring) is a specific, documented reading of an ambiguous EVAL.md
  phrase. A broader Random baseline — drawn from *all* established,
  unconnected pairs, not just the 1,365 that already have a qualifying
  structural bridge — would very likely show a much lower floor, since
  most random concept pairs in this corpus share no bridge at all. That
  would strengthen finding #1 (structure beats nothing) without changing
  findings #2 or #3. Not computed here; flagged as a natural follow-up.
- **Near-synonym contamination is not corrected for** — it's documented
  and its effect on each method is discussed, but the precision numbers
  above are what they are with that contamination still present. A
  cleaned-up rerun after an entity-resolution pass on the corpus would be
  a legitimate next step, not a re-litigation of this eval.
