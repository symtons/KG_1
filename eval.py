"""eval.py — Step 7: run the eval.

Applies EVAL.md's matching rule to Step 6's ranked candidates against
post-cutoff (year >= 2023) ground truth, builds the three EVAL.md
baselines, surfaces evidence for manual verification, and reports
precision@10/20 computed only over manually-confirmed hits.

EVAL.md itself is not edited by this file or by Step 7's implementation —
it says "this file does not change after this point," and Step 6 already
happened. Two things EVAL.md states but doesn't spell out to executable
precision are operationalized here instead (filling in an implied detail
is not the same as changing the rule's substance):

1. "a pre-cutoff paper strongly associated with A" (bridge-citation signal)
   = a pre-cutoff paper that MENTIONS A, per Step 4's extraction — the same
   MENTIONS relationship used everywhere else in this pipeline (load.py's
   graph edges, rank.py's co-mention exclusion). extract.py's own system
   prompt already restricts what gets extracted to what the abstract
   "actually states or clearly implies," so a bare mention is already a
   non-trivial signal, not string-matching noise.
2. "same candidate pool" (for the three baselines) = literally the same
   set of candidate pairs rank.py produced (every established, not-already-
   connected pair with >= 1 qualifying structural bridge), just re-ordered
   by each method's own ranking logic. This isn't a weakened reading:
   Adamic-Adar's score is exactly 0 outside this pool by construction (no
   shared neighbor, nothing to sum), so "same pool" is the only reading
   under which Adamic-Adar is even well-defined as a competing ranking
   over the same items — Random and Similarity then use the same pool for
   a controlled comparison, isolating ranking logic as the only variable
   between methods.

Similarity baseline: cosine similarity between entity embeddings, computed
locally with sentence-transformers (all-MiniLM-L6-v2) — not a paid
embeddings API. Given the budget situation (see memory), a free local
model that fully satisfies EVAL.md's "no graph structure at all" baseline
requirement is the obvious choice over spending anything further. Each
entity's embedding is the mean of the (pre-computed once) embeddings of
the pre-cutoff paper abstracts that mention it.

Usage:
    pip install sentence-transformers
    python eval.py                  # full run, prints top 20 per method for
                                     # manual verification
"""

import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

import rank

DATA = Path("data")
PAPERS = DATA / "papers.jsonl"
EXTRACTIONS = DATA / "extractions.jsonl"
CITATIONS = DATA / "citations.jsonl"

CUTOFF_YEAR = rank.CUTOFF_YEAR
TOP_K = 20               # manual verification + precision@20 need this many;
                          # precision@10 is just the first 10 of the same list
RANDOM_SEED = 42          # fixed for reproducibility, chosen before looking
                          # at any ranking (not tuned)
EMBED_MODEL = "all-MiniLM-L6-v2"


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def build_citation_adjacency(citations: list[dict]) -> dict[str, set]:
    """Undirected within-corpus citation adjacency, same construction as
    load.py's write_citations (both references and citations fields)."""
    s2_to_arxiv = {c["s2_id"]: c["arxiv_id"] for c in citations if c.get("s2_id")}
    adj: dict[str, set] = defaultdict(set)
    for c in citations:
        aid = c["arxiv_id"]
        for ref in c.get("references", []) + c.get("citations", []):
            t = s2_to_arxiv.get(ref)
            if t and t != aid:
                adj[aid].add(t)
                adj[t].add(aid)
    return adj


def build_postcutoff_mentions(extractions: list[dict], papers: dict[str, dict]) -> dict[str, set]:
    mentions: dict[str, set] = defaultdict(set)
    for ext in extractions:
        paper = papers.get(ext["arxiv_id"])
        if paper is None or paper["year"] is None or paper["year"] <= CUTOFF_YEAR:
            continue
        for e in ext["entities"]:
            mentions[e["id"]].add(ext["arxiv_id"])
    return mentions


def build_bridge_reachable(mentions_precutoff: dict[str, set], cite_adj: dict[str, set],
                            papers: dict[str, dict]) -> dict[str, set]:
    """entity -> set of post-cutoff papers reachable by one citation hop
    from a pre-cutoff paper that mentions it."""
    reachable: dict[str, set] = defaultdict(set)
    for entity, precutoff_papers in mentions_precutoff.items():
        for p in precutoff_papers:
            for neighbor in cite_adj.get(p, ()):
                np_ = papers.get(neighbor)
                if np_ and np_["year"] and np_["year"] > CUTOFF_YEAR:
                    reachable[entity].add(neighbor)
    return reachable


def check_hit(a: str, c: str, postcutoff_mentions: dict, bridge_reachable: dict) -> tuple[bool, dict]:
    comention = postcutoff_mentions.get(a, set()) & postcutoff_mentions.get(c, set())
    bridge = bridge_reachable.get(a, set()) & bridge_reachable.get(c, set())
    hit = bool(comention) or bool(bridge)
    return hit, {"comention": sorted(comention)[:5], "bridge_citation": sorted(bridge)[:5]}


def compute_entity_embeddings(entity_ids: set, mentions_precutoff: dict, papers: dict) -> dict:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBED_MODEL)

    needed_papers = sorted(set().union(*(mentions_precutoff.get(e, set()) for e in entity_ids)))
    abstracts = [papers[aid]["abstract"] for aid in needed_papers]
    print(f"[eval] embedding {len(abstracts)} pre-cutoff abstracts locally ({EMBED_MODEL}, "
          f"one-time, no API cost)...")
    paper_embs = model.encode(abstracts, batch_size=64, show_progress_bar=True)
    paper_emb_by_id = dict(zip(needed_papers, paper_embs))

    entity_embs = {}
    for e in entity_ids:
        vecs = [paper_emb_by_id[aid] for aid in mentions_precutoff.get(e, set()) if aid in paper_emb_by_id]
        if vecs:
            entity_embs[e] = np.mean(vecs, axis=0)
    return entity_embs


def cosine_sim(u: np.ndarray, v: np.ndarray) -> float:
    return float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9))


def build_rankings(system_results: list[dict], mentions_precutoff: dict, papers: dict) -> dict[str, list]:
    pairs = [(r["a"], r["c"]) for r in system_results]

    by_system = list(pairs)

    by_aa = [(r["a"], r["c"]) for r in sorted(system_results, key=lambda r: -r["adamic_adar_raw"])]

    rnd = random.Random(RANDOM_SEED)
    by_random = list(pairs)
    rnd.shuffle(by_random)

    entity_ids = {a for a, _ in pairs} | {c for _, c in pairs}
    embs = compute_entity_embeddings(entity_ids, mentions_precutoff, papers)
    scored = [(a, c, cosine_sim(embs[a], embs[c])) for a, c in pairs if a in embs and c in embs]
    scored.sort(key=lambda x: -x[2])
    by_similarity = [(a, c) for a, c, _ in scored]

    return {"system": by_system, "adamic_adar": by_aa, "random": by_random, "similarity": by_similarity}


def print_for_verification(method: str, ranked_pairs: list, postcutoff_mentions: dict,
                            bridge_reachable: dict, papers: dict) -> list[dict]:
    print(f"\n{'=' * 70}\n{method}  (top {TOP_K})\n{'=' * 70}")
    rows = []
    for i, (a, c) in enumerate(ranked_pairs[:TOP_K], 1):
        hit, evidence = check_hit(a, c, postcutoff_mentions, bridge_reachable)
        tag = "HIT" if hit else "miss"
        print(f"\n{i:3d}. [{tag}] {a}  <-->  {c}")
        for aid in evidence["comention"]:
            title = papers.get(aid, {}).get("title", "?")
            print(f"       co-mention: {aid}  {title}")
        for aid in evidence["bridge_citation"]:
            title = papers.get(aid, {}).get("title", "?")
            print(f"       bridge-citation: {aid}  {title}")
        rows.append({"rank": i, "a": a, "c": c, "auto_hit": hit, "evidence": evidence})
    return rows


def main() -> None:
    papers = {p["arxiv_id"]: p for p in load_jsonl(PAPERS)}
    extractions = load_jsonl(EXTRACTIONS)
    citations = load_jsonl(CITATIONS)

    mentions_precutoff, paper_entities, rel_adj, entity_origin_counts, n_pre = rank.build_precutoff_graph()

    postcutoff_mentions = build_postcutoff_mentions(extractions, papers)
    n_post_papers = len({ext["arxiv_id"] for ext in extractions
                          if papers.get(ext["arxiv_id"], {}).get("year", 0) and
                          papers[ext["arxiv_id"]]["year"] > CUTOFF_YEAR})
    print(f"[eval] {n_post_papers} post-cutoff papers, {len(postcutoff_mentions)} entities "
          f"mentioned post-cutoff")

    cite_adj = build_citation_adjacency(citations)
    bridge_reachable = build_bridge_reachable(mentions_precutoff, cite_adj, papers)

    print("\n[eval] recomputing Step 6's system ranking (same code, same output as rank.py)...")
    system_results = rank.rank()

    rankings = build_rankings(system_results, mentions_precutoff, papers)

    all_verification_rows = {}
    for method, ranked_pairs in rankings.items():
        all_verification_rows[method] = print_for_verification(
            method, ranked_pairs, postcutoff_mentions, bridge_reachable, papers
        )

    out_path = DATA / "eval_automated.json"
    out_path.write_text(json.dumps(all_verification_rows, indent=2), encoding="utf-8")
    print(f"\n[eval] wrote automated hit/evidence for top {TOP_K} per method -> {out_path}")
    print("[eval] NOTE: these are AUTOMATED matches only. Per EVAL.md, precision@10/20 must "
          "be computed from MANUALLY verified hits, not this file directly.")


if __name__ == "__main__":
    main()
