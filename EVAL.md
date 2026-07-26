# EVAL.md — evaluation design, committed before the ranker exists

This is written before Step 6 (triangle search + ranking) is implemented, on
purpose. If the matching rule and baselines are written after seeing what the
ranker produces, there's no way to know whether the rule was chosen because
it's right or because it's the one that made the numbers look good. Locking it
now means Step 6 has to hit a pre-committed target, not the other way around.

## What's being measured

The system looks only at the pre-cutoff graph (papers with `year <= 2022`,
per pull.py) and proposes ranked candidate bridges: pairs of concepts `(A, C)`
that are each well-established (both have real degree in the graph — enough
citing/cited/co-mentioning papers to not be noise) but were never directly
connected pre-cutoff, connected only through some intermediate `B`. The claim
under test: did the field actually go on to connect `A` and `C`?

Ground truth comes from papers with `year >= 2023` — held out from the system
entirely until scoring time.

## Matching rule

A candidate pair `(A, C)` counts as a **hit** if at least one post-cutoff paper
satisfies *either*:

1. **Co-mention** — the paper's extracted entities (same Step 4 extractor,
   run on the post-cutoff paper's abstract) include both `A` and `C`, or
2. **Bridge-citation** — the paper cites (or is cited by, per
   `data/citations.jsonl`) a pre-cutoff paper strongly associated with `A`
   *and* a pre-cutoff paper strongly associated with `C`.

Either signal alone is sufficient — this is an OR, not an AND. Co-mention
catches the case where a single post-cutoff paper explicitly synthesizes both
concepts; bridge-citation catches the case where the synthesis happens through
citation structure (a paper draws on both lineages) without ever using both
terms in its abstract.

## No partial credit

Each candidate is scored strictly hit or miss. There is no fractional credit
for "related but not quite" or "half the bridge showed up." If the automated
matching rule produces an ambiguous case — e.g. a co-mention that's clearly
incidental (both terms appear in an unrelated laundry-list of related work)
rather than substantive — that case goes to manual adjudication (below), and
the adjudicator still records a binary hit/miss, not a partial score. Partial
credit is how eval rules quietly drift toward flattering whatever the ranker
happens to produce; binary scoring with a manual check is the guard against
that.

## Manual verification

Automated matching (especially co-mention) will have false positives: two
concepts can appear in the same abstract without the paper actually treating
them as connected. Before reporting any headline number, the top 10 and top 20
ranked candidates from each method (system + all baselines) are read by hand
and confirmed as genuine substantive bridges, not coincidental co-occurrence.
This is the step that makes the reported hit rate defensible instead of "a
metric a critic could dismiss as string-matching noise" — precision@10/20 is
computed only over manually-confirmed hits.

## Baselines

A hit rate on its own is meaningless without something to compare it to. Three
baselines, same candidate pool, same matching rule, same manual verification
step:

| Baseline | What it ranks by | What it tests |
|---|---|---|
| **Random** | Random ordering of eligible non-adjacent pairs | Floor — what hit rate happens by chance given the base rate of post-cutoff connection in this field |
| **Similarity** | Cosine similarity between `A` and `C`'s abstract embeddings, no graph structure at all | Whether "structure over similarity" is a real advantage or just marketing — this is the baseline the whole differentiator claim has to beat |
| **Adamic-Adar** | Standard link-prediction heuristic — common neighbors weighted by inverse log-degree | The standard graph-only baseline; doesn't do the "sweet spot" filtering (both sides independently established, bridge specifically missing) the system's ranker is meant to add on top |

System beats Random → the graph carries signal at all. System beats
Similarity → structure matters, not just semantic closeness. System beats
Adamic-Adar → the sweet-spot ranking logic (not just "many shared neighbors")
is doing real work. Each comparison isolates a different claim; losing to one
baseline but not others is itself a useful, specific result, not just a bad
outcome to hide.

## Metric

Precision@10 and precision@20, per method (system + 3 baselines), computed
after manual verification.

## LLM exclusion from ranking

An LLM is used in exactly one place in this pipeline: Step 4 extraction,
applied uniformly to pre-cutoff and post-cutoff abstracts, and validated
against `hand_labels.md` before being trusted on the full corpus.

An LLM is **never** called inside the ranking/scoring function that orders
candidate bridges in Step 6. The ranker may only use graph topology and
schema-derived structure — degree of `A`, degree of `C`, number and weight of
shared neighbors `B`, absence of a direct pre-cutoff edge between `A` and `C`,
edge types from the schema (e.g. preferring candidates connected through a
`FAILS_AT` edge on one side, since limitations are where bridges hide, per
hand_labels.md).

Reason: any LLM asked to judge "is `(A, C)` a promising bridge" was trained on
data that almost certainly includes post-2022 papers — it may already know
`A` and `C` got connected, and "predict" the connection by recalling it rather
than by reasoning over the pre-cutoff graph. That's future-knowledge leakage,
and it would be invisible in the final numbers — the eval would look like it
validated structural discovery when it actually validated an LLM's memory.
Keeping ranking purely structural is what makes a clean pre-2023/post-2023
split mean anything at all.

## Sequencing

1. Step 4 extraction ships, validated against `hand_labels.md`.
2. Step 5 loads the pre-cutoff graph into Neo4j.
3. Step 6 ranker runs against the pre-cutoff graph only, using purely
   structural signals, and outputs a ranked candidate list. **This file does
   not change after this point.**
4. Step 7 applies the matching rule above against post-cutoff papers, runs the
   three baselines, manually verifies top 10/20 per method, and reports
   precision@10/20. That number — not a demo, not a story — is the headline
   result.
