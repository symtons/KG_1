"""Smoke test: verify Python can reach the Neo4j container.

Usage:
    pip install neo4j python-dotenv
    python db.py

Expected output: connected
"""

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()  # reads .env in the current folder

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
)

try:
    with driver.session() as session:
        result = session.run("RETURN 'connected' AS status")
        print(result.single()["status"])

        # Bonus check: confirm the schema constraints exist
        constraints = list(session.run("SHOW CONSTRAINTS"))
        print(f"constraints found: {len(constraints)}")
        for c in constraints:
            print(f"  - {c['name']}")
finally:
    driver.close()