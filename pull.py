"""pull.py — Step 3: build the corpus.

Pulls titles/abstracts from arXiv for a core + ring query set, dedupes,
then fetches citation edges from Semantic Scholar. Everything is cached
to disk; the script is safe to kill and re-run (it skips work already done).

Usage:
    pip install requests python-dotenv
    python pull.py            # runs both passes + report
    python pull.py --report   # just re-print the sanity report

Outputs:
    data/raw/arxiv/<query_slug>/<page>.xml   raw API responses (cached)
    data/raw/s2/<batch_index>.json           raw citation responses (cached)
    data/papers.jsonl                        one paper per line, deduped
    data/citations.jsonl                     paper_id -> citations/references
    data/pull_report.txt                     sanity summary

Optional .env keys:
    S2_API_KEY=...    # Semantic Scholar key, if/when approved (faster rate limit)
"""

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------- queries ----

# origin "core": tight efficient-LLM-inference scope (method terms + LLM anchor)
# origin "ring": adjacent literatures sharing bridge concepts (deliberately wide)
QUERIES = [
    # ---- core ----
    ("core", 'all:"quantization" AND all:"large language model"'),
    ("core", 'all:"quantization" AND all:"LLM"'),
    ("core", 'all:"quantization" AND all:"transformer" AND cat:cs.CL'),
    ("core", 'all:"pruning" AND all:"large language model"'),
    ("core", 'all:"pruning" AND all:"transformer" AND cat:cs.CL'),
    ("core", 'all:"knowledge distillation" AND all:"language model"'),
    ("core", 'all:"speculative decoding"'),
    ("core", 'all:"KV cache"'),
    ("core", 'all:"efficient inference" AND all:"transformer"'),
    ("core", 'all:"efficient attention"'),
    ("core", 'all:"early exit" AND all:"transformer"'),
    ("core", 'all:"mixture of experts" AND all:"inference"'),
    ("core", 'all:"low-rank" AND all:"large language model"'),
    # ---- ring ----
    ("ring", 'all:"vector quantization" AND cat:cs.LG'),
    ("ring", 'all:"dithered quantization"'),
    ("ring", 'all:"rate-distortion" AND cat:cs.IT'),
    ("ring", 'all:"compressed sensing" AND cat:cs.LG'),
    ("ring", 'all:"network compression" AND cat:cs.LG'),
    ("ring", 'all:"gradient compression"'),
    ("ring", 'all:"accuracy degradation" AND cat:cs.LG'),
    ("ring", 'all:"outlier" AND all:"activation" AND cat:cs.LG'),
    ("ring", 'all:"memory bandwidth" AND cat:cs.AR'),
    ("ring", 'all:"sparse matrix" AND all:"neural network"'),
]

MAX_RESULTS_PER_QUERY = 2000     # hard cap per query; tighten if a query is too broad
PAGE_SIZE = 200                  # arXiv max per request
ARXIV_SLEEP = 3.0                # seconds between arXiv requests (their ToS)
ARXIV_URL = "http://export.arxiv.org/api/query"

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "title,year,citations.paperId,references.paperId,externalIds"
S2_BATCH_SIZE = 500
S2_SLEEP_NO_KEY = 1.1            # unauthenticated: ~1 req/sec
S2_SLEEP_WITH_KEY = 1.1

DATA = Path("data")
RAW_ARXIV = DATA / "raw" / "arxiv"
RAW_S2 = DATA / "raw" / "s2"
PAPERS = DATA / "papers.jsonl"
CITATIONS = DATA / "citations.jsonl"
REPORT = DATA / "pull_report.txt"

NS = {"a": "http://www.w3.org/2005/Atom"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:80]


# ------------------------------------------------------------ arXiv pass ----

def fetch_arxiv_page(query: str, start: int) -> str:
    """Fetch one page of arXiv results; returns raw XML text."""
    resp = requests.get(
        ARXIV_URL,
        params={
            "search_query": query,
            "start": start,
            "max_results": PAGE_SIZE,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.text


def parse_entries(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        raw_id = e.find("a:id", NS).text  # e.g. http://arxiv.org/abs/2410.05265v1
        arxiv_id = raw_id.rsplit("/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)  # strip version
        title = (e.find("a:title", NS).text or "").strip()
        abstract = (e.find("a:summary", NS).text or "").strip()
        published = e.find("a:published", NS).text or ""
        cats = [c.attrib.get("term", "") for c in e.findall(
            "{http://www.w3.org/2005/Atom}category")]
        out.append({
            "arxiv_id": arxiv_id,
            "title": re.sub(r"\s+", " ", title),
            "abstract": re.sub(r"\s+", " ", abstract),
            "year": int(published[:4]) if published[:4].isdigit() else None,
            "categories": cats,
        })
    return out


def run_arxiv_pass() -> dict[str, dict]:
    """Iterate all queries with caching; return papers keyed by arxiv_id."""
    papers: dict[str, dict] = {}
    for origin, query in QUERIES:
        qdir = RAW_ARXIV / slug(query)
        qdir.mkdir(parents=True, exist_ok=True)
        start = 0
        while start < MAX_RESULTS_PER_QUERY:
            page_file = qdir / f"{start:06d}.xml"
            if page_file.exists():
                xml_text = page_file.read_text(encoding="utf-8")
            else:
                print(f"[arxiv] {origin} :: {query!r} :: start={start}")
                try:
                    xml_text = fetch_arxiv_page(query, start)
                except requests.RequestException as exc:
                    print(f"  !! request failed ({exc}); retrying in 30s")
                    time.sleep(30)
                    continue
                page_file.write_text(xml_text, encoding="utf-8")
                time.sleep(ARXIV_SLEEP)

            entries = parse_entries(xml_text)
            if not entries:
                break  # past the end of results for this query
            for p in entries:
                pid = p["arxiv_id"]
                if pid in papers:
                    papers[pid]["matched_queries"].append(query)
                    # core wins over ring if matched by both
                    if origin == "core":
                        papers[pid]["origin"] = "core"
                else:
                    papers[pid] = {**p, "origin": origin,
                                   "matched_queries": [query]}
            start += PAGE_SIZE
    return papers


# ------------------------------------------------- Semantic Scholar pass ----

def run_s2_pass(paper_ids: list[str]) -> None:
    """Fetch citations/references for all papers in batches, cached per batch."""
    RAW_S2.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("S2_API_KEY", "").strip()
    headers = {"x-api-key": api_key} if api_key else {}
    sleep = S2_SLEEP_WITH_KEY if api_key else S2_SLEEP_NO_KEY
    if not api_key:
        print("[s2] no S2_API_KEY in .env — using unauthenticated 1 req/sec "
              "(fine, just slow; safe to leave running)")

    with CITATIONS.open("w", encoding="utf-8") as out:
        for i in range(0, len(paper_ids), S2_BATCH_SIZE):
            batch_file = RAW_S2 / f"batch_{i // S2_BATCH_SIZE:04d}.json"
            batch_ids = [f"ARXIV:{pid}" for pid in paper_ids[i:i + S2_BATCH_SIZE]]

            if batch_file.exists():
                results = json.loads(batch_file.read_text(encoding="utf-8"))
            else:
                print(f"[s2] batch {i // S2_BATCH_SIZE} "
                      f"({i}/{len(paper_ids)} papers)")
                while True:
                    resp = requests.post(
                        S2_BATCH_URL,
                        params={"fields": S2_FIELDS},
                        json={"ids": batch_ids},
                        headers=headers,
                        timeout=120,
                    )
                    if resp.status_code == 429:
                        print("  .. rate limited; sleeping 60s")
                        time.sleep(60)
                        continue
                    resp.raise_for_status()
                    break
                results = resp.json()
                batch_file.write_text(json.dumps(results), encoding="utf-8")
                time.sleep(sleep)

            for pid, rec in zip(paper_ids[i:i + S2_BATCH_SIZE], results):
                if rec is None:
                    continue  # S2 doesn't know this paper
                out.write(json.dumps({
                    "arxiv_id": pid,
                    "s2_id": rec.get("paperId"),
                    "citations": [c["paperId"] for c in rec.get("citations") or []
                                  if c.get("paperId")],
                    "references": [r["paperId"] for r in rec.get("references") or []
                                   if r.get("paperId")],
                }) + "\n")


# ------------------------------------------------------------------ report ----

def write_report() -> None:
    papers = [json.loads(l) for l in PAPERS.read_text(encoding="utf-8").splitlines()]
    lines = []
    lines.append(f"total papers: {len(papers)}")

    by_origin = Counter(p["origin"] for p in papers)
    lines.append(f"by origin: {dict(by_origin)}")

    years = Counter(p["year"] for p in papers if p["year"])
    lines.append("\nyear histogram:")
    for y in sorted(years):
        lines.append(f"  {y}: {'#' * min(years[y] // 20 + 1, 60)} {years[y]}")

    pre = sum(c for y, c in years.items() if y <= 2022)
    post = sum(c for y, c in years.items() if y >= 2023)
    lines.append(f"\npre-cutoff (<=2022): {pre}   post-cutoff (>=2023): {post}")

    empty_abs = sum(1 for p in papers if len(p["abstract"]) < 100)
    lines.append(f"papers with missing/short abstract: {empty_abs}")

    per_query = defaultdict(int)
    for p in papers:
        for q in p["matched_queries"]:
            per_query[q] += 1
    lines.append("\npapers per query (overlapping):")
    for q, n in sorted(per_query.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {n:6d}  {q}")

    if CITATIONS.exists():
        cits = [json.loads(l) for l in
                CITATIONS.read_text(encoding="utf-8").splitlines()]
        with_edges = sum(1 for c in cits if c["citations"] or c["references"])
        lines.append(f"\npapers with S2 citation data: {len(cits)} "
                     f"({with_edges} with >=1 edge)")

    text = "\n".join(lines)
    REPORT.write_text(text, encoding="utf-8")
    print("\n" + "=" * 70 + "\n" + text + "\n" + "=" * 70)
    print(f"\nreport saved to {REPORT}")


# -------------------------------------------------------------------- main ----

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true",
                    help="only regenerate the sanity report")
    ap.add_argument("--skip-s2", action="store_true",
                    help="skip the Semantic Scholar citation pass")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)

    if args.report:
        write_report()
        return

    papers = run_arxiv_pass()
    print(f"\n[arxiv] done: {len(papers)} unique papers")

    with PAPERS.open("w", encoding="utf-8") as f:
        for p in papers.values():
            f.write(json.dumps(p) + "\n")
    print(f"[arxiv] wrote {PAPERS}")

    if not args.skip_s2:
        run_s2_pass(sorted(papers.keys()))
        print(f"[s2] wrote {CITATIONS}")

    write_report()


if __name__ == "__main__":
    main()