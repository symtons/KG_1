# RANKING.md — Step 6 design

Locks the structural ranking design `rank.py` implements. Not
pre-registered as strictly as EVAL.md (the ranking formula and the eval's
matching rule are separable — EVAL.md doesn't care which specific formula
Step 6 uses, only that it's purely structural), but written down honestly
before looking at results, including the design's real limitations, rather
than left implicit in code nobody has to defend.

## Source of truth: raw extraction files, not the Neo4j graph

`rank.py` reads `data/papers.jsonl` and `data/extractions.jsonl` directly —
**not** the graph `load.py` built. `load.py` caps each relation edge's
stored paper-provenance sample at 25 (`MAX_PROVENANCE_SAMPLE`), which is
fine for display/audit purposes but wrong for anything that needs to know
precisely whether a specific triple has pre-cutoff support: a triple with
200 supporting papers might have its one pre-2023 supporter fall outside
the retained sample of 25, silently misclassifying a real pre-cutoff edge
as post-cutoff-only. Since `extractions.jsonl` records every (paper,
triple) assertion with no cap, building the pre-cutoff graph directly from
that file avoids the problem entirely instead of working around it.

## Time split

Pre-cutoff = papers with `year <= 2022`, matching `pull.py` and EVAL.md
exactly. Only pre-cutoff papers' entities and triples are used to build
the graph `rank.py` searches — that's the system's entire view of the
world, by construction.

## What counts as "already connected" (excluded from candidacy)

`A` and `C` are excluded as a candidate pair if they co-occur in the
entity list of *any single* pre-cutoff paper — not just if a direct
relation triple exists between them. This is deliberately broader than "no
relation edge," and it's the correct check, not an overcautious one: every
relation triple is extracted from one paper's own entity list (a triple's
subject and object always come from that paper's own extraction — see
`load.py`'s dangling-triple filter), so any paper asserting a direct A-C
relation edge *necessarily* also co-mentions A and C. Co-mention is a
strict superset of "has a direct relation edge." Using it as the exclusion
criterion also keeps "already connected" (pre-cutoff) and "counts as a
hit" (post-cutoff, per EVAL.md's matching rule) defined the same way —
otherwise the eval could credit the system for "discovering" a connection
that a pre-cutoff paper had already made.

## "Established" — the noise filter

An entity must be mentioned by at least **5** distinct pre-cutoff papers
to qualify as a candidate bridge endpoint (A or C). Below that, it's more
likely a one-off extraction artifact (a typo, an overly specific
paper-only phrasing that didn't canonicalize) than a real recurring
concept worth bridging. 5 is a judgment call, not a validated threshold —
flagged here so it's easy to revisit if Step 7's results look off.

## The bridge node B, and why hub nodes are excluded

B is a shared neighbor of A and C in the **relation graph** specifically
(one of the 10 `hand_labels.md` relation types) — not the looser
co-mention graph. A relation edge (`APPLIES_TO`, `CAUSES`, `FAILS_AT`, ...)
is a real asserted claim; co-mention can be coincidental (two concepts
both mentioned in a survey-style abstract without being substantively
linked).

B is excluded from serving as a bridge if its own pre-cutoff degree is at
or above the **99th percentile** of the observed bridge-capable-node
degree distribution, recomputed from the real data on every run rather
than hardcoded. A "bridge" through a concept like `accuracy` or `llm` —
the highest-degree nodes in the graph — carries no discriminating signal:
at that degree, practically everything in the corpus already relates to
it, so sharing that neighbor says nothing specific about A and C. This is
a substantive modeling choice, not just a performance guard (though it
helps there too).

The threshold is percentile-based, not an absolute constant, because the
first version of this file picked a fixed cutoff (400) from intuition
about the *full* graph's hub degrees (nodes like `accuracy` sit near
12,000 there). Once actually measured against the much smaller pre-cutoff
subgraph the ranker runs on, that number was badly miscalibrated: the real
distribution has a median bridge-node degree of 2, a 99th percentile
around 24, and then a small number of true mega-hubs reaching into the
hundreds — so a fixed cutoff of 400 excluded only the top 3 nodes instead
of the intended "generic hub" tier. This was caught by looking at the
actual degree distribution before trusting the ranker's output, not by
tuning against how any specific candidate ranked — see the discussion of
that distinction below.

## Scoring

Base score is a standard Adamic-Adar sum over qualifying shared bridges B:

```
Σ_B  1 / log(1 + degree(B))
```

Rarer, more specific bridges contribute more than high-degree ones — same
intuition as the hub exclusion above, just continuous instead of a hard
cutoff.

Two multiplicative bonuses on top, both grounded in this project's own
stated design bets rather than generic graph-theory tuning:

- **FAILS_AT bonus (×1.5)** — applied if either the A–B or B–C edge is a
  `FAILS_AT` relation. Directly implements `hand_labels.md`'s central
  hypothesis: limitation edges are where bridges hide, because a
  limitation documented in one field is often already solved in another.
- **Cross-origin bonus (×1.5)** — applied if A and C's dominant paper
  origin (`core` vs. `ring`, majority vote over the pre-cutoff papers that
  mention each) differ. Directly implements the corpus design's own bet
  from Step 0 / `pull.py`: "quantization" spans communities, and the ring
  pull existed specifically to catch bridge material a core-only corpus
  would have missed.

Both bonus values (1.5×) are round, deliberately unoptimized numbers —
EVAL.md's matching rule didn't exist as ground truth to tune against when
this was written, and it stays that way.

## Why this isn't just "Adamic-Adar with extra steps"

Adamic-Adar is one of the three EVAL.md baselines this ranker's output has
to beat, so it can't just be a relabeled copy of it. The two bonuses above
are the actual claim under test: that limitation edges and cross-community
structure carry real bridging signal beyond generic common-neighbor
weighting. If Step 7 shows this ranker doesn't beat plain Adamic-Adar,
that's a legitimate, informative result about this specific hypothesis —
not a reason to retune the bonuses after the fact to force a win.

## Known limitations (open, not hidden)

- The established-ness threshold (5 papers) is a round-number judgment
  call, not validated against anything. The hub cutoff is at least
  data-derived (99th percentile of the real degree distribution) rather
  than a guessed constant, but *which* percentile (99th, not 95th or 90th)
  is still a judgment call.
- The FAILS_AT and cross-origin bonuses are equal-weighted and untuned by
  design (see above) — they may not be equally informative in practice.
- A bridge B is only usable if it has a pre-cutoff relation edge to *both*
  A and C. If a real bridge concept only ever shows up via co-mention (no
  specific asserted relation) in this corpus, this ranker won't surface
  it — a relation-graph-only search has strictly less reach than a
  co-mention-graph search, traded deliberately for higher precision per
  hand_labels.md's reasoning above.
- **Observed in the actual output, not just theoretical:** a handful of
  top-1000 candidates are near-synonym pairs that should have canonicalized
  to one entity in Step 4 but didn't — `dnn` / `deep_neural_network` /
  `neural_network` are three separate nodes, so pairs like
  `deep_neural_network <-> dnn` show up scored as "bridges" when they're
  really the same concept split across IDs. The Step 4 controlled
  vocabulary only pinned ~26 hub terms (the ones that were actually
  observed drifting during validation); generic ML terminology outside
  that list had no such guarantee and some of it duplicated as predicted.
  This isn't fixed here — it's flagged for Step 7's manual verification
  pass to catch and exclude, same as any other candidate that turns out on
  inspection not to be a real bridge.
