"""rank.py — Step 6: triangle search + ranking (the heart).

Finds structural bridges in the PRE-CUTOFF graph only (papers with
year <= 2022) — pairs of concepts (A, C) that are each independently
well-established but have no direct pre-cutoff connection, linked only
through intermediate concepts B. Ranks them by a purely structural score;
no LLM anywhere in this file (see EVAL.md's LLM-exclusion-from-ranking
rule).

Reads data/papers.jsonl and data/extractions.jsonl directly — NOT the
Neo4j graph load.py built, which caps per-edge paper provenance at 25 for
display purposes. See RANKING.md for why that cap makes Neo4j unsafe as
the source of truth for a pre/post-cutoff split, and for the rest of the
locked design (established-ness threshold, what counts as "already
connected", the Adamic-Adar-style base score, and the two corpus-specific
bonuses: FAILS_AT-anchored bridges and core/ring cross-origin bridges).

Usage:
    python rank.py                 # full run, writes data/candidates.jsonl
    python rank.py --top 30        # print the top N to stdout (default 15)
"""

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path("data")
PAPERS = DATA / "papers.jsonl"
EXTRACTIONS = DATA / "extractions.jsonl"
CANDIDATES = DATA / "candidates.jsonl"

CUTOFF_YEAR = 2022            # system sees year <= CUTOFF_YEAR only
MIN_PAPERS_ESTABLISHED = 5    # entity must be mentioned by >= this many
                               # pre-cutoff papers to be a candidate endpoint
HUB_EXCLUSION_PERCENTILE = 0.99  # exclude the top 1% of bridge-capable nodes
                               # by pre-cutoff degree from serving as a bridge
                               # B — computed from the real distribution each
                               # run, not a guessed absolute constant (a fixed
                               # cutoff picked from full-graph intuition, e.g.
                               # 400, turned out to barely exclude anything
                               # once measured against the much smaller
                               # pre-cutoff subgraph — see RANKING.md)
FAILS_AT_BONUS = 1.5
CROSS_ORIGIN_BONUS = 1.5
TOP_N_OUTPUT = 1000           # how many ranked candidates to write to disk


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def build_precutoff_graph():
    papers = {p["arxiv_id"]: p for p in load_jsonl(PAPERS)}
    extractions = load_jsonl(EXTRACTIONS)

    mentions: dict[str, set] = defaultdict(set)          # entity -> {pre-cutoff arxiv_ids}
    paper_entities: dict[str, set] = {}                  # pre-cutoff arxiv_id -> {entity ids}
    rel_adj: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    entity_origin_counts: dict[str, Counter] = defaultdict(Counter)

    n_precutoff_papers = 0
    for ext in extractions:
        aid = ext["arxiv_id"]
        paper = papers.get(aid)
        if paper is None or paper["year"] is None or paper["year"] > CUTOFF_YEAR:
            continue
        n_precutoff_papers += 1

        entity_ids = {e["id"] for e in ext["entities"]}
        paper_entities[aid] = entity_ids
        for eid in entity_ids:
            mentions[eid].add(aid)
            entity_origin_counts[eid][paper["origin"]] += 1

        for t in ext["triples"]:
            s, r, o = t["subject"], t["relation"], t["object"]
            if s not in entity_ids or o not in entity_ids:
                continue  # dangling triple — same defensive check as load.py
            rel_adj[s][o].add((r, aid))
            rel_adj[o][s].add((r, aid))  # undirected: either side can bridge

    return mentions, paper_entities, rel_adj, entity_origin_counts, n_precutoff_papers


def build_comention_set(paper_entities: dict[str, set]) -> set[tuple]:
    """Every (A, C) pair that co-occurs in some pre-cutoff paper's entity
    list — a strict superset of "has a direct relation edge" (see
    RANKING.md), so this alone defines "already connected" pre-cutoff."""
    comentioned = set()
    for entity_ids in paper_entities.values():
        ids = sorted(entity_ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                comentioned.add((ids[i], ids[j]))
    return comentioned


def dominant_origin(entity_origin_counts: dict[str, Counter], eid: str) -> str | None:
    c = entity_origin_counts.get(eid)
    return c.most_common(1)[0][0] if c else None


def compute_hub_degree_cutoff(rel_adj: dict, percentile: float) -> int:
    """The value at the given percentile of the observed bridge-capable
    (degree >= 2) node degree distribution — self-calibrating instead of a
    guessed absolute constant. See RANKING.md."""
    degrees = sorted(len(neighbors) for neighbors in rel_adj.values() if len(neighbors) >= 2)
    if not degrees:
        return 0
    idx = min(int(len(degrees) * percentile), len(degrees) - 1)
    return degrees[idx]


def rank() -> list[dict]:
    mentions, paper_entities, rel_adj, entity_origin_counts, n_precutoff_papers = build_precutoff_graph()

    established = {e for e, ps in mentions.items() if len(ps) >= MIN_PAPERS_ESTABLISHED}
    print(f"[rank] {n_precutoff_papers} pre-cutoff papers, {len(mentions)} distinct entities "
          f"mentioned, {len(established)} pass the established threshold "
          f"(>= {MIN_PAPERS_ESTABLISHED} papers)")

    comentioned = build_comention_set(paper_entities)
    print(f"[rank] {len(comentioned)} co-mentioned pairs excluded as already-connected")

    max_bridge_degree = compute_hub_degree_cutoff(rel_adj, HUB_EXCLUSION_PERCENTILE)
    print(f"[rank] hub-degree cutoff (p{HUB_EXCLUSION_PERCENTILE * 100:.0f} of the real "
          f"distribution): {max_bridge_degree}")

    bridge_data: dict[tuple, dict] = defaultdict(lambda: {"score": 0.0, "bridges": [], "fails_at": False})
    n_bridges_used = n_bridges_skipped_hub = n_bridges_skipped_small = 0

    for b, neighbors in rel_adj.items():
        deg_b = len(neighbors)
        if deg_b < 2:
            n_bridges_skipped_small += 1
            continue
        if deg_b > max_bridge_degree:
            n_bridges_skipped_hub += 1
            continue
        n_bridges_used += 1
        weight = 1.0 / math.log(1 + deg_b)

        neighbor_list = sorted(neighbors)
        for i in range(len(neighbor_list)):
            a = neighbor_list[i]
            if a not in established:
                continue
            for j in range(i + 1, len(neighbor_list)):
                c = neighbor_list[j]
                if c not in established:
                    continue
                pair = (a, c) if a < c else (c, a)
                if pair in comentioned:
                    continue

                a_b_rels = {r for r, _ in rel_adj[b][a]}
                b_c_rels = {r for r, _ in rel_adj[b][c]}
                fails_at_here = "FAILS_AT" in a_b_rels or "FAILS_AT" in b_c_rels

                entry = bridge_data[pair]
                entry["score"] += weight
                entry["fails_at"] = entry["fails_at"] or fails_at_here
                entry["bridges"].append({
                    "id": b, "degree": deg_b,
                    "a_b_relations": sorted(a_b_rels), "b_c_relations": sorted(b_c_rels),
                })

    print(f"[rank] bridge nodes: {n_bridges_used} used, {n_bridges_skipped_hub} excluded as "
          f"over-generic hubs (degree > {max_bridge_degree}), {n_bridges_skipped_small} had "
          f"< 2 neighbors")
    print(f"[rank] {len(bridge_data)} candidate (A, C) pairs found via >= 1 shared bridge")

    results = []
    for (a, c), entry in bridge_data.items():
        origin_a = dominant_origin(entity_origin_counts, a)
        origin_c = dominant_origin(entity_origin_counts, c)
        cross_origin = origin_a is not None and origin_c is not None and origin_a != origin_c

        final_score = entry["score"]
        if entry["fails_at"]:
            final_score *= FAILS_AT_BONUS
        if cross_origin:
            final_score *= CROSS_ORIGIN_BONUS

        entry["bridges"].sort(key=lambda x: -x["degree"])
        results.append({
            "a": a, "c": c,
            "score": final_score,
            "adamic_adar_raw": entry["score"],
            "fails_at_bridge": entry["fails_at"],
            "cross_origin": cross_origin,
            "origin_a": origin_a, "origin_c": origin_c,
            "established_a": len(mentions[a]), "established_c": len(mentions[c]),
            "n_bridges": len(entry["bridges"]),
            "bridges": entry["bridges"][:10],  # sample for manual audit, not the full set
        })

    results.sort(key=lambda r: -r["score"])
    return results


def print_top(results: list[dict], n: int) -> None:
    print(f"\n{'=' * 70}\ntop {n} candidates:\n{'=' * 70}")
    for i, r in enumerate(results[:n], 1):
        tags = []
        if r["fails_at_bridge"]:
            tags.append("FAILS_AT")
        if r["cross_origin"]:
            tags.append(f"{r['origin_a']}<->{r['origin_c']}")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        print(f"\n{i:3d}. {r['a']}  <-->  {r['c']}   score={r['score']:.3f}{tag_str}")
        print(f"     established: {r['established_a']} / {r['established_c']} papers; "
              f"{r['n_bridges']} bridge(s)")
        for br in r["bridges"][:3]:
            print(f"     via {br['id']} (degree {br['degree']}): "
                  f"{r['a']} -[{','.join(br['a_b_relations'])}]-> "
                  f"{br['id']} -[{','.join(br['b_c_relations'])}]-> {r['c']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15, help="how many candidates to print to stdout")
    args = ap.parse_args()

    results = rank()

    with CANDIDATES.open("w", encoding="utf-8") as f:
        for r in results[:TOP_N_OUTPUT]:
            f.write(json.dumps(r) + "\n")
    print(f"\n[rank] wrote top {min(TOP_N_OUTPUT, len(results))} of {len(results)} "
          f"ranked candidates -> {CANDIDATES}")

    print_top(results, args.top)


if __name__ == "__main__":
    main()
