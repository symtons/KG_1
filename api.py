"""api.py — Step 8: articulation layer.

FastAPI backend serving the ranked candidates (Step 6), the manual
verification log (Step 7), and live entity/graph lookups against Neo4j
(Step 5) for the React + react-flow frontend in web/.

Read-only. Nothing here writes to Neo4j or re-runs any pipeline step —
this is a viewer over data the earlier steps already produced.

Usage:
    pip install fastapi "uvicorn[standard]"
    uvicorn api:app --reload --port 8000
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase
from pydantic import BaseModel

load_dotenv()

DATA = Path("data")
CANDIDATES_PATH = DATA / "candidates.jsonl"
VERIFICATION_PATH = DATA / "eval_verification.json"

app = FastAPI(title="KG bridge-finder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
)


def load_candidates() -> list[dict]:
    with CANDIDATES_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def load_verification() -> dict:
    return json.loads(VERIFICATION_PATH.read_text(encoding="utf-8"))


CANDIDATES = load_candidates()
CANDIDATE_BY_PAIR = {(c["a"], c["c"]): c for c in CANDIDATES}
RANK_BY_PAIR = {(c["a"], c["c"]): i + 1 for i, c in enumerate(CANDIDATES)}
VERIFICATION = load_verification()

# index verification rows by (method, a, c) for quick lookup
VERIFICATION_BY_PAIR: dict[tuple, dict] = {}
for method, rows in VERIFICATION["methods"].items():
    for row in rows:
        VERIFICATION_BY_PAIR[(method, row["a"], row["c"])] = row


class CandidateSummary(BaseModel):
    rank: int
    a: str
    c: str
    score: float
    fails_at_bridge: bool
    cross_origin: bool
    origin_a: str | None
    origin_c: str | None
    established_a: int
    established_c: int
    n_bridges: int
    verified: dict | None = None


def to_summary(rank: int, c: dict) -> CandidateSummary:
    verified = VERIFICATION_BY_PAIR.get(("system", c["a"], c["c"]))
    return CandidateSummary(
        rank=rank, a=c["a"], c=c["c"], score=c["score"],
        fails_at_bridge=c["fails_at_bridge"], cross_origin=c["cross_origin"],
        origin_a=c["origin_a"], origin_c=c["origin_c"],
        established_a=c["established_a"], established_c=c["established_c"],
        n_bridges=c["n_bridges"],
        verified={"verdict": verified["verdict"], "reason": verified["reason"]} if verified else None,
    )


@app.get("/api/stats")
def stats():
    with driver.session() as session:
        n_papers = session.run("MATCH (p:Paper) RETURN count(p) AS n").single()["n"]
        n_entities = session.run("MATCH (e:Entity) RETURN count(e) AS n").single()["n"]
        n_mentions = session.run("MATCH ()-[m:MENTIONS]->() RETURN count(m) AS n").single()["n"]
        n_cites = session.run("MATCH ()-[c:CITES]->() RETURN count(c) AS n").single()["n"]
    return {
        "papers": n_papers,
        "entities": n_entities,
        "mentions": n_mentions,
        "citations": n_cites,
        "candidates": len(CANDIDATES),
        "precision": VERIFICATION["precision"],
    }


@app.get("/api/candidates")
def list_candidates(limit: int = 50, offset: int = 0):
    page = CANDIDATES[offset:offset + limit]
    return {
        "total": len(CANDIDATES),
        "results": [to_summary(offset + i + 1, c) for i, c in enumerate(page)],
    }


@app.get("/api/candidates/{a}/{c}")
def candidate_detail(a: str, c: str):
    candidate = CANDIDATE_BY_PAIR.get((a, c)) or CANDIDATE_BY_PAIR.get((c, a))
    if candidate is None:
        raise HTTPException(404, f"no candidate ({a}, {c})")

    verification = {
        method: VERIFICATION_BY_PAIR.get((method, candidate["a"], candidate["c"]))
        for method in VERIFICATION["methods"]
    }
    return {**candidate, "verification": verification}


@app.get("/api/graph/bridge")
def bridge_graph(a: str, c: str):
    """react-flow-ready nodes/edges for one candidate's bridge structure,
    built directly from the candidate record (already has up to 10 sampled
    bridges with their relation types — see rank.py)."""
    candidate = CANDIDATE_BY_PAIR.get((a, c)) or CANDIDATE_BY_PAIR.get((c, a))
    if candidate is None:
        raise HTTPException(404, f"no candidate ({a}, {c})")

    a_id, c_id = candidate["a"], candidate["c"]
    bridges = candidate["bridges"]

    nodes = [
        {"id": a_id, "type": "endpoint", "data": {"label": a_id, "role": "a"},
         "position": {"x": 0, "y": max(len(bridges), 1) * 60}},
        {"id": c_id, "type": "endpoint", "data": {"label": c_id, "role": "c"},
         "position": {"x": 600, "y": max(len(bridges), 1) * 60}},
    ]
    edges = []
    for i, b in enumerate(bridges):
        node_id = f"bridge::{b['id']}"
        nodes.append({
            "id": node_id, "type": "bridge",
            "data": {"label": b["id"], "degree": b["degree"]},
            "position": {"x": 300, "y": i * 120},
        })
        edges.append({
            "id": f"{a_id}->{node_id}", "source": a_id, "target": node_id,
            "label": ",".join(b["a_b_relations"]),
            "highlighted": "FAILS_AT" in b["a_b_relations"],
        })
        edges.append({
            "id": f"{node_id}->{c_id}", "source": node_id, "target": c_id,
            "label": ",".join(b["b_c_relations"]),
            "highlighted": "FAILS_AT" in b["b_c_relations"],
        })

    return {"nodes": nodes, "edges": edges, "candidate": candidate}


@app.get("/api/entity/{entity_id}")
def entity_detail(entity_id: str):
    """Explore view for the search feature: type, how well-established the
    entity is pre-cutoff, its strongest relation-graph neighbors, and every
    ranked candidate pair it shows up in. Read-only — MATCH/RETURN only,
    consistent with the rest of this file."""
    with driver.session() as session:
        row = session.run(
            "MATCH (e:Entity {canonical_name: $id}) RETURN e.type AS type", id=entity_id
        ).single()
        if row is None:
            raise HTTPException(404, f"no entity {entity_id}")

        pre_cutoff_mentions = session.run("""
            MATCH (p:Paper)-[:MENTIONS]->(:Entity {canonical_name: $id})
            WHERE p.year <= 2022
            RETURN count(p) AS n
        """, id=entity_id).single()["n"]

        neighbors = session.run("""
            MATCH (e:Entity {canonical_name: $id})-[r]-(other:Entity)
            RETURN other.canonical_name AS neighbor, other.type AS neighbor_type,
                   type(r) AS relation, r.support AS shared_papers,
                   CASE WHEN startNode(r) = e THEN 'out' ELSE 'in' END AS direction
            ORDER BY shared_papers DESC
            LIMIT 15
        """, id=entity_id).data()

    candidate_pairs = [
        to_summary(RANK_BY_PAIR[(c["a"], c["c"])], c)
        for c in CANDIDATES
        if c["a"] == entity_id or c["c"] == entity_id
    ]

    return {
        "canonical_name": entity_id,
        "type": row["type"],
        "pre_cutoff_mentions": pre_cutoff_mentions,
        "neighbors": neighbors,
        "candidates": candidate_pairs,
    }


@app.on_event("shutdown")
def shutdown():
    driver.close()
