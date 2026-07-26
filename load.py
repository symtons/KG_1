"""load.py — Step 5: load the corpus into Neo4j.

Reads data/papers.jsonl, data/extractions.jsonl, data/citations.jsonl and
writes one graph:

    (:Paper {id, title, year, origin, categories})
    (:Entity {canonical_name, type, observed_types, type_conflict, surface_forms})
        type in the 7 hand_labels.md entity types
    (:Paper)-[:MENTIONS {attributes}]->(:Entity)
    (:Entity)-[:<RELATION> {support, papers, magnitudes, conditions}]->(:Entity)
        RELATION in the 10 hand_labels.md relations (APPLIES_TO, IMPROVES, ...)
    (:Paper)-[:CITES]->(:Paper)   within-corpus citation edges only

Label/property names (:Paper.id, :Entity.canonical_name, :Entity.type) match
the constraints already set up in Neo4j from earlier infra work — this
script doesn't rename or replace that schema, it fills it in.

All aggregation (entity surface forms/type, edge support/provenance) happens
in Python before any Cypher runs, so every write is a plain MERGE + SET
(never an increment) — safe to re-run from scratch any time. Unlike
pull.py / extract.py this step costs nothing and runs against a local DB,
so there's no need for incremental resumability against a paid API; a full
reload is fast enough to just do a full reload.

Usage:
    pip install neo4j python-dotenv
    python load.py            # full load (idempotent, safe to re-run)
    python load.py --wipe     # delete all existing nodes/edges first, then load
    python load.py --report   # just re-print the sanity report (reads live from Neo4j)

Requires NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in .env (see db.py).
"""

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from extract import RELATIONS

load_dotenv()

DATA = Path("data")
PAPERS = DATA / "papers.jsonl"
EXTRACTIONS = DATA / "extractions.jsonl"
CITATIONS = DATA / "citations.jsonl"
REPORT = DATA / "load_report.txt"

BATCH_SIZE = 1000
MAX_PROVENANCE_SAMPLE = 25  # cap the "example papers" list stored on hub edges


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def chunks(rows: list, n: int):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


# --------------------------------------------------------------- aggregate ----

def aggregate():
    """Do all the collapsing (surface forms, type votes, edge support/
    provenance) in Python first, so the Neo4j writes are simple idempotent
    MERGEs with no incremental state."""
    papers = load_jsonl(PAPERS)
    extractions = load_jsonl(EXTRACTIONS)
    citations = load_jsonl(CITATIONS)

    entity_types: dict[str, Counter] = defaultdict(Counter)
    entity_surface_forms: dict[str, set] = defaultdict(set)
    mentions = []  # (arxiv_id, entity_id, attributes: list[str])
    triple_agg: dict[tuple, dict] = defaultdict(
        lambda: {"support": 0, "papers": [], "magnitudes": set(), "conditions": set()}
    )

    skipped_dangling_triples = 0

    for ext in extractions:
        aid = ext["arxiv_id"]
        seen_this_paper: set[str] = set()

        for e in ext["entities"]:
            eid = e["id"]
            entity_types[eid][e["type"]] += 1
            entity_surface_forms[eid].update(e.get("surface_forms", []))
            if eid not in seen_this_paper:
                attrs = [f'{a["key"]}={a["value"]}' for a in e.get("attributes", [])]
                mentions.append((aid, eid, attrs))
                seen_this_paper.add(eid)

        for t in ext["triples"]:
            s, r, o = t["subject"], t["relation"], t["object"]
            # Defensive: the extraction schema requires subject/object to be
            # entity ids from the same paper's own entities list, but don't
            # trust that blindly across 11.6k independent LLM calls.
            if s not in seen_this_paper or o not in seen_this_paper:
                skipped_dangling_triples += 1
                continue
            agg = triple_agg[(s, r, o)]
            agg["support"] += 1
            if len(agg["papers"]) < MAX_PROVENANCE_SAMPLE:
                agg["papers"].append(aid)
            if t.get("magnitude"):
                agg["magnitudes"].add(t["magnitude"])
            if t.get("condition"):
                agg["conditions"].add(t["condition"])

    entities_final = {}
    type_conflicts = 0
    for eid, counter in entity_types.items():
        top_type = counter.most_common(1)[0][0]
        conflict = len(counter) > 1
        type_conflicts += conflict
        entities_final[eid] = {
            "canonical_name": eid,
            "type": top_type,
            "observed_types": sorted(counter),
            "type_conflict": conflict,
            "surface_forms": sorted(entity_surface_forms[eid]),
        }

    print(f"[load] aggregated {len(entities_final)} unique entities from "
          f"{sum(len(e['entities']) for e in extractions)} raw mentions")
    print(f"[load] aggregated {len(triple_agg)} unique triples from "
          f"{sum(len(e['triples']) for e in extractions)} raw triples "
          f"({skipped_dangling_triples} dangling triples skipped)")
    print(f"[load] {type_conflicts} entities had conflicting types across papers")

    return papers, entities_final, mentions, triple_agg, citations


# -------------------------------------------------------------------- write ----

def run_write(session, query: str, **params):
    def _work(tx):
        return tx.run(query, **params).consume()
    return session.execute_write(_work)


def ensure_constraints(session) -> None:
    # Matches what's already on the DB from earlier setup; IF NOT EXISTS
    # makes this safe to run against either the existing DB or a fresh one.
    run_write(session, "CREATE CONSTRAINT paper_id IF NOT EXISTS "
                        "FOR (p:Paper) REQUIRE p.id IS UNIQUE")
    run_write(session, "CREATE CONSTRAINT entity_name IF NOT EXISTS "
                        "FOR (e:Entity) REQUIRE e.canonical_name IS UNIQUE")
    run_write(session, "CREATE INDEX entity_type IF NOT EXISTS "
                        "FOR (e:Entity) ON (e.type)")
    run_write(session, "CREATE INDEX paper_year IF NOT EXISTS "
                        "FOR (p:Paper) ON (p.year)")


def wipe(session) -> None:
    print("[load] wiping existing graph...")
    while True:
        result = session.execute_write(
            lambda tx: tx.run(
                "MATCH (n) WITH n LIMIT 20000 DETACH DELETE n RETURN count(n) AS n"
            ).single()
        )
        if result["n"] == 0:
            break
    print("[load] wipe done")


def write_papers(session, papers: list[dict]) -> None:
    rows = [{"id": p["arxiv_id"], "title": p["title"], "year": p["year"],
             "origin": p["origin"], "categories": p["categories"]} for p in papers]
    for i, batch in enumerate(chunks(rows, BATCH_SIZE)):
        run_write(session, """
            UNWIND $rows AS row
            MERGE (p:Paper {id: row.id})
            SET p.title = row.title, p.year = row.year,
                p.origin = row.origin, p.categories = row.categories
        """, rows=batch)
        print(f"[load] papers {min((i + 1) * BATCH_SIZE, len(rows))}/{len(rows)}")


def write_entities(session, entities_final: dict) -> None:
    rows = list(entities_final.values())
    for i, batch in enumerate(chunks(rows, BATCH_SIZE)):
        run_write(session, """
            UNWIND $rows AS row
            MERGE (e:Entity {canonical_name: row.canonical_name})
            SET e.type = row.type, e.observed_types = row.observed_types,
                e.type_conflict = row.type_conflict, e.surface_forms = row.surface_forms
        """, rows=batch)
        print(f"[load] entities {min((i + 1) * BATCH_SIZE, len(rows))}/{len(rows)}")


def write_mentions(session, mentions: list[tuple]) -> None:
    rows = [{"paper": aid, "entity": eid, "attributes": attrs} for aid, eid, attrs in mentions]
    for i, batch in enumerate(chunks(rows, BATCH_SIZE * 2)):
        run_write(session, """
            UNWIND $rows AS row
            MATCH (p:Paper {id: row.paper})
            MATCH (e:Entity {canonical_name: row.entity})
            MERGE (p)-[m:MENTIONS]->(e)
            SET m.attributes = row.attributes
        """, rows=batch)
        print(f"[load] mentions {min((i + 1) * BATCH_SIZE * 2, len(rows))}/{len(rows)}")


def write_triples(session, triple_agg: dict) -> None:
    relations = set(RELATIONS)
    by_relation: dict[str, list] = defaultdict(list)
    for (s, r, o), agg in triple_agg.items():
        assert r in relations, f"unknown relation {r!r} — extract.py schema drifted from load.py"
        by_relation[r].append({
            "s": s, "o": o, "support": agg["support"], "papers": agg["papers"],
            "magnitudes": sorted(agg["magnitudes"]), "conditions": sorted(agg["conditions"]),
        })

    for rel, rows in by_relation.items():
        for i, batch in enumerate(chunks(rows, BATCH_SIZE)):
            # Relationship type can't be parameterized in Cypher; safe here
            # because `rel` is asserted above to be one of the 10 known
            # relation names, not arbitrary/untrusted input.
            run_write(session, f"""
                UNWIND $rows AS row
                MATCH (s:Entity {{canonical_name: row.s}})
                MATCH (o:Entity {{canonical_name: row.o}})
                MERGE (s)-[r:{rel}]->(o)
                SET r.support = row.support, r.papers = row.papers,
                    r.magnitudes = row.magnitudes, r.conditions = row.conditions
            """, rows=batch)
        print(f"[load] {rel}: {len(rows)} unique triples")


def write_citations(session, citations: list[dict]) -> int:
    s2_to_arxiv = {c["s2_id"]: c["arxiv_id"] for c in citations if c.get("s2_id")}

    edges: set[tuple] = set()
    for c in citations:
        aid = c["arxiv_id"]
        for ref in c.get("references", []):
            target = s2_to_arxiv.get(ref)
            if target and target != aid:
                edges.add((aid, target))          # aid cites target
        for cit in c.get("citations", []):
            citer = s2_to_arxiv.get(cit)
            if citer and citer != aid:
                edges.add((citer, aid))            # citer cites aid

    rows = [{"a": a, "b": b} for a, b in edges]
    for i, batch in enumerate(chunks(rows, BATCH_SIZE * 2)):
        run_write(session, """
            UNWIND $rows AS row
            MATCH (a:Paper {id: row.a})
            MATCH (b:Paper {id: row.b})
            MERGE (a)-[:CITES]->(b)
        """, rows=batch)
        print(f"[load] citations {min((i + 1) * BATCH_SIZE * 2, len(rows))}/{len(rows)}")
    return len(edges)


def run_load() -> None:
    papers, entities_final, mentions, triple_agg, citations = aggregate()

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    )
    try:
        with driver.session() as session:
            ensure_constraints(session)
            write_papers(session, papers)
            write_entities(session, entities_final)
            write_mentions(session, mentions)
            write_triples(session, triple_agg)
            n_citation_edges = write_citations(session, citations)
            print(f"[load] {n_citation_edges} within-corpus citation edges")
    finally:
        driver.close()

    write_report()


# ------------------------------------------------------------------ report ----

def write_report() -> None:
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    )
    lines = []
    try:
        with driver.session() as session:
            n_papers = session.run("MATCH (p:Paper) RETURN count(p) AS n").single()["n"]
            n_entities = session.run("MATCH (e:Entity) RETURN count(e) AS n").single()["n"]
            n_mentions = session.run("MATCH ()-[m:MENTIONS]->() RETURN count(m) AS n").single()["n"]
            n_cites = session.run("MATCH ()-[c:CITES]->() RETURN count(c) AS n").single()["n"]
            n_conflicts = session.run(
                "MATCH (e:Entity {type_conflict: true}) RETURN count(e) AS n"
            ).single()["n"]

            lines.append(f"papers: {n_papers}")
            lines.append(f"entities: {n_entities}  (type_conflict: {n_conflicts})")
            lines.append(f"MENTIONS edges: {n_mentions}")
            lines.append(f"CITES edges (within corpus): {n_cites}")

            lines.append("\nentities by type:")
            for r in session.run(
                "MATCH (e:Entity) RETURN e.type AS type, count(*) AS n ORDER BY n DESC"
            ):
                lines.append(f"  {r['n']:6d}  {r['type']}")

            lines.append("\nrelation edges:")
            total_rel_edges = 0
            for rel in RELATIONS:
                n = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS n").single()["n"]
                total_rel_edges += n
                lines.append(f"  {n:6d}  {rel}")
            lines.append(f"  {total_rel_edges:6d}  TOTAL")

            lines.append("\ntop 15 entities by total degree (sanity check — hub concepts "
                         "should dominate):")
            for r in session.run("""
                MATCH (e:Entity)
                RETURN e.canonical_name AS name, e.type AS type,
                       COUNT { (e)--() } AS degree
                ORDER BY degree DESC LIMIT 15
            """):
                lines.append(f"  {r['degree']:6d}  {r['type']:12s} {r['name']}")

    finally:
        driver.close()

    text = "\n".join(lines)
    REPORT.write_text(text, encoding="utf-8")
    print("\n" + "=" * 70 + "\n" + text + "\n" + "=" * 70)
    print(f"\nreport saved to {REPORT}")


# -------------------------------------------------------------------- main ----

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wipe", action="store_true",
                     help="delete all existing nodes/relationships before loading")
    ap.add_argument("--report", action="store_true",
                     help="just re-print the sanity report from the live DB")
    args = ap.parse_args()

    if args.report:
        write_report()
        return

    if args.wipe:
        driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
        )
        try:
            with driver.session() as session:
                wipe(session)
        finally:
            driver.close()

    run_load()


if __name__ == "__main__":
    main()
