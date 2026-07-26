"""extract.py — Step 4: LLM extraction.

Extracts a concept graph (typed entities + relation triples) from each
paper's title/abstract, against the schema locked in hand_labels.md.
Two independent modes:

    --validate    run only the 5 hand-labeled papers (sync calls, real
                  money but effectively free) and print predicted triples
                  next to hand_labels.md's gold triples for manual
                  comparison. Run this every time the prompt/schema
                  changes, before trusting the extractor on the full
                  corpus — same principle EVAL.md applies to ranking.
    --submit      submit a Batch (50% cheaper, async, up to 24h) for every
                  paper not yet in data/extractions.jsonl.
    --poll        check / collect the submitted batch. Add --wait to
                  block until it finishes instead of a one-shot check.
    --report      regenerate the sanity report from data/extractions.jsonl.

Everything is cached to disk; safe to kill and re-run (skips work already
done), same discipline as pull.py.

Usage:
    pip install anthropic
    python extract.py --validate
    python extract.py --submit
    python extract.py --poll [--wait]
    python extract.py --report

Requires ANTHROPIC_API_KEY in .env.

Outputs:
    data/raw/extract/<arxiv_id>.json     raw sync API responses (cached)
    data/raw/extract_batch/<batch_id>.jsonl   raw batch results (cached)
    data/extractions.jsonl               one paper per line: entities + triples
    data/extract_batch_id.txt            id of the most recently submitted batch
    data/extract_report.txt              sanity summary
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-5"
MAX_TOKENS = 8192
# "medium": this is bounded categorization + careful reading, not open-ended
# reasoning — tune down from the "high" default to control cost at 11.6k
# papers. Revisit if --validate output looks shallow.
EFFORT = "medium"

# ---------------------------------------------------------------- schema ----
# Mirrors hand_labels.md exactly. If that file's entity/relation tables
# change, this must change with it (and vice versa).

ENTITY_TYPES = ["Method", "ModelFamily", "Task", "Metric", "Resource", "Dataset", "Phenomenon"]
RELATIONS = [
    "APPLIES_TO", "IMPROVES", "DEGRADES", "REDUCES", "CAUSES",
    "MITIGATES", "FAILS_AT", "EXTENDS", "COMBINES_WITH", "APPROXIMATES",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "snake_case canonical identifier, stable across papers "
                                       "(e.g. 'activation_outlier', not 'the outliers in activations')",
                    },
                    "type": {"type": "string", "enum": ENTITY_TYPES},
                    "surface_forms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "exact phrases from the title/abstract that refer to this entity",
                    },
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["key", "value"],
                            "additionalProperties": False,
                        },
                        "description": "precision/format/scope facts about this entity, e.g. "
                                       "{key: precision, value: W8A8}. Never create a separate "
                                       "entity for a bit-width, format, or magnitude.",
                    },
                },
                "required": ["id", "type", "surface_forms", "attributes"],
                "additionalProperties": False,
            },
        },
        "triples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "must match an entity id above"},
                    "relation": {"type": "string", "enum": RELATIONS},
                    "object": {"type": "string", "description": "must match an entity id above"},
                    "magnitude": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "quantified effect size if the text states one, "
                                       "e.g. '1.56x', '<1%'; null otherwise",
                    },
                    "condition": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "FAILS_AT only: the condition under which the failure "
                                       "occurs, e.g. 'when the original fine-tuning pipeline is "
                                       "unavailable'; null for every other relation",
                    },
                },
                "required": ["subject", "relation", "object", "magnitude", "condition"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["entities", "triples"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You extract a structured concept graph from a single paper's title and \
abstract, for a literature-based-discovery system studying efficient LLM inference \
(quantization, pruning, distillation, speculative decoding, KV-cache, mixture-of-experts, \
etc.) and adjacent fields (signal processing, information theory, federated learning, \
compressed sensing).

Extract only what the title/abstract actually states or clearly implies. Do not use \
outside knowledge about the paper, its citations, or its authors' other work.

## Entity types
- Method: a named technique, algorithm, system, or training procedure \
(e.g. "SmoothQuant", "speculative decoding", "quantization-aware training").
- ModelFamily: the model/architecture class a method is applied to \
(e.g. "LLM", "BERT", "GPT-2", "Transformer").
- Task: the downstream problem being solved (e.g. "autoregressive decoding", "channel estimation").
- Metric: a quantity used to evaluate success or cost (e.g. "inference speed", "model size", "task accuracy").
- Resource: a hardware/system constraint the method targets or consumes \
(e.g. "GPU memory", "edge device", "scalar ADC").
- Dataset: a named evaluation dataset or benchmark, only if actually named \
(e.g. "WikiText-2", "GLUE"). Do not invent one.
- Phenomenon: an observed characteristic, side effect, or failure mode — not a method, \
not a metric, a *thing that happens* (e.g. "activation outlier", "quantization error", \
"overfitting", "accuracy-compression trade-off").

## Relations (subject -> object)
- APPLIES_TO: Method -> ModelFamily | Task | Resource. Method is used on/for this target.
- IMPROVES: Method -> Metric. Method makes this metric better.
- DEGRADES: Method -> Metric. Method makes this metric worse (a quantified cost the authors accept).
- REDUCES: Method -> Resource | Metric. Method lowers consumption of a resource or a cost-metric.
- CAUSES: Phenomenon -> Phenomenon. One observed effect produces another.
- MITIGATES: Method -> Phenomenon. Method exists specifically to counteract a phenomenon.
- FAILS_AT: Method -> Task | Phenomenon. First-class limitation edge — the method breaks down \
under a named condition. Put the condition in the triple's `condition` field, not in the entity.
- EXTENDS: Method -> Method. Method is built directly on top of a named prior method.
- COMBINES_WITH: Method -> Method (symmetric). Methods are composed/stacked together.
- APPROXIMATES: Method -> Method | ModelFamily. Method stands in for a more expensive method/model.

## Rules
1. Precision/format values (INT8, W8A8, 4-bit, FP16) and quantified magnitudes (1.56x, 10x, \
<1%) are never separate entities. Precision/format goes in an entity's `attributes`; \
magnitudes go in a triple's `magnitude`.
2. Canonicalize: use a stable snake_case `id` for each entity. If a concept is generic and \
likely to recur across many papers in this corpus (e.g. "quantization", "pruning", \
"accuracy", "inference_speed", "activation_outlier"), use the plain, ubiquitous form as the \
id — not a paper-specific phrasing. This is what lets the same concept merge across \
different papers' extractions. List every phrase from the text that refers to it in \
`surface_forms`.
3. Extract generic background claims the abstract makes (e.g. "pruning is known to decrease \
model size"), not just claims about the paper's own named contribution — generic edges are \
what let two papers connect without sharing a named method.
4. Do not invent entities or triples the text doesn't support. A short or narrow abstract \
should produce a short or narrow extraction — do not pad it.
5. Every `subject` and `object` in `triples` must exactly match an `id` in `entities`.

## Controlled vocabulary
Every extraction is a separate, independent call with no memory of any other paper — so a
hub concept that recurs across hundreds of papers will drift to a different id each time
unless it's pinned here. If a paper touches one of these well-established concepts, use
EXACTLY this id, not a variant or synonym you invent:

{glossary}

This list is deliberately short — it covers only concepts common enough to appear across
many papers in this corpus. For anything else, apply rule 2 above."""

# Hub concepts observed (or expected) to recur across many papers in this corpus —
# drawn from pull.py's query list plus what --validate surfaced empirically (e.g. the
# same activation-outlier/quantization-error pair came back as "quantization_difficulty"
# in one call and "quantization_error" in another before this glossary existed).
# Deliberately short: only pin terms common enough to actually cause cross-paper drift.
CANONICAL_GLOSSARY = {
    "quantization": "quantization",
    "pruning": "pruning",
    "knowledge distillation": "knowledge_distillation",
    "speculative decoding": "speculative_decoding",
    "KV cache": "kv_cache",
    "mixture of experts": "mixture_of_experts",
    "low-rank adaptation / decomposition": "low_rank_adaptation",
    "early exit": "early_exit",
    "efficient attention": "efficient_attention",
    "large language model / LLM": "llm",
    "transformer": "transformer",
    "BERT": "bert",
    "GPT-2": "gpt2",
    "activation outlier": "activation_outlier",
    "quantization error / quantization difficulty": "quantization_error",
    "(task) accuracy": "accuracy",
    "inference speed / latency": "inference_speed",
    "model size": "model_size",
    "memory / GPU memory": "memory",
    "overfitting": "overfitting",
    "vector quantization / vector quantizer": "vector_quantizer",
    "rate-distortion theory": "rate_distortion_theory",
    "compressed sensing": "compressed_sensing",
    "network / model compression": "compression",
    "gradient compression": "gradient_compression",
    "memory bandwidth": "memory_bandwidth",
    "sparse matrix": "sparse_matrix",
}

SYSTEM_PROMPT = SYSTEM_PROMPT.format(
    glossary="\n".join(f"- {surface} -> `{cid}`" for surface, cid in CANONICAL_GLOSSARY.items())
)

DATA = Path("data")
PAPERS = DATA / "papers.jsonl"
EXTRACTIONS = DATA / "extractions.jsonl"
REPORT = DATA / "extract_report.txt"
RAW_SYNC = DATA / "raw" / "extract"
RAW_BATCH = DATA / "raw" / "extract_batch"
BATCH_ID_FILE = DATA / "extract_batch_id.txt"

# ------------------------------------------------------ hand-labeled gold ----
# Copied from hand_labels.md. Keep in sync if that file changes; this is
# what --validate diffs the live extractor against before the real run.

GOLD = {
    "2211.10438": [  # SmoothQuant
        ("SmoothQuant", "APPLIES_TO", "LLM"),
        ("SmoothQuant", "MITIGATES", "activation_outlier"),
        ("activation_outlier", "CAUSES", "quantization_error"),
        ("SmoothQuant", "REDUCES", "memory"),
        ("SmoothQuant", "IMPROVES", "inference_speed"),
    ],
    "2203.07259": [  # The Optimal BERT Surgeon
        ("oBERT", "APPLIES_TO", "BERT"),
        ("oBERT", "EXTENDS", "second_order_pruning"),
        ("oBERT", "REDUCES", "model_size"),
        ("oBERT", "IMPROVES", "inference_speed"),
        ("oBERT", "DEGRADES", "task_accuracy"),
        ("oBERT", "APPLIES_TO", "edge_device"),
        ("pruning", "REDUCES", "model_size"),
    ],
    "2211.17192": [  # Fast Inference from Transformers via Speculative Decoding
        ("speculative_decoding", "APPLIES_TO", "autoregressive_decoding"),
        ("speculative_decoding", "APPLIES_TO", "T5_XXL"),
        ("speculative_decoding", "IMPROVES", "inference_speed"),
        ("draft_model", "APPROXIMATES", "Transformer"),
        ("speculative_decoding", "COMBINES_WITH", "draft_model"),
    ],
    "1908.06845": [  # Deep Task-Based Quantization
        ("deep_task_based_quantization", "APPLIES_TO", "MIMO_channel_estimation"),
        ("deep_task_based_quantization", "APPLIES_TO", "symbol_detection"),
        ("deep_task_based_quantization", "APPROXIMATES", "vector_quantizer"),
        ("deep_task_based_quantization", "REDUCES", "bit_error_rate"),
    ],
    "2211.16912": [  # Quadapter
        ("Quadapter", "APPLIES_TO", "GPT2"),
        ("activation_outlier", "CAUSES", "quantization_error"),
        ("quantization_aware_training", "FAILS_AT", "overfitting"),
        ("Quadapter", "MITIGATES", "overfitting"),
        ("Quadapter", "MITIGATES", "activation_outlier"),
    ],
}


def load_papers() -> dict[str, dict]:
    papers = {}
    with PAPERS.open(encoding="utf-8") as f:
        for line in f:
            p = json.loads(line)
            papers[p["arxiv_id"]] = p
    return papers


def user_prompt(paper: dict) -> str:
    return f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}"


def output_config() -> dict:
    return {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}}


def parse_response_text(resp) -> dict:
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


# ------------------------------------------------------------- validate ----

def extract_sync(client: anthropic.Anthropic, paper: dict):
    """Call the API for one paper (sync), caching the raw response. Returns
    (parsed_dict, usage) — usage is None on a cache hit (no call made)."""
    cache_file = RAW_SYNC / f"{paper['arxiv_id']}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8")), None

    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        output_config=output_config(),
        messages=[{"role": "user", "content": user_prompt(paper)}],
    )
    result = parse_response_text(resp)
    RAW_SYNC.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result, resp.usage


def run_validate() -> None:
    client = anthropic.Anthropic()
    papers = load_papers()

    usages = []
    total_gold = total_shape_matched = 0

    for arxiv_id, gold_triples in GOLD.items():
        paper = papers[arxiv_id]
        print("=" * 70)
        print(f"{arxiv_id}  {paper['title']}")

        result, usage = extract_sync(client, paper)
        if usage:
            usages.append(usage)
            print(f"  [usage] input={usage.input_tokens} "
                  f"cache_write={usage.cache_creation_input_tokens} "
                  f"cache_read={usage.cache_read_input_tokens} "
                  f"output={usage.output_tokens}")

        pred_entities = {e["id"]: e["type"] for e in result["entities"]}
        pred_triples = [(t["subject"], t["relation"], t["object"]) for t in result["triples"]]

        print(f"\n  predicted entities ({len(pred_entities)}):")
        for eid, etype in pred_entities.items():
            print(f"    {etype:12s} {eid}")

        print(f"\n  predicted triples ({len(pred_triples)}):")
        for s, r, o in pred_triples:
            print(f"    ({s}, {r}, {o})")

        print(f"\n  gold triples ({len(gold_triples)}) — ids are hand-picked, won't match "
              f"exactly, compare by eye:")
        for s, r, o in gold_triples:
            print(f"    ({s}, {r}, {o})")

        # Rough signal only, NOT a real metric: does the predicted set contain
        # a triple of the same relation type anywhere in this paper's output?
        # Real scoring is manual — see EVAL.md's stance on why automated
        # matching alone isn't trusted for this project.
        pred_relations = Counter(r for _, r, _ in pred_triples)
        gold_relations = Counter(r for _, r, _ in gold_triples)
        for rel, n in gold_relations.items():
            total_gold += n
            total_shape_matched += min(n, pred_relations.get(rel, 0))

    print("\n" + "=" * 70)
    print(f"relation-type coverage (ROUGH SIGNAL, NOT precision/recall): "
          f"{total_shape_matched}/{total_gold} gold relation instances had a "
          f"same-type predicted triple somewhere in that paper's output.")
    print("Read the printed triples above and judge by hand — same principle "
          "hand_labels.md and EVAL.md both insist on.")

    if usages:
        avg_in = sum(u.input_tokens for u in usages) / len(usages)
        avg_cache_read = sum(u.cache_read_input_tokens for u in usages) / len(usages)
        avg_out = sum(u.output_tokens for u in usages) / len(usages)
        n_papers = 11610  # data/pull_report.txt total
        # Batch API: 50% off both input and output. Cache reads: ~0.1x base
        # input price, then batch's 50% on top. Rough estimate only — ignores
        # cache_creation_input_tokens (paid once, amortized to ~0 at this n).
        in_price, out_price = 5.0, 25.0  # $ per MTok, Opus 5 standard rates
        per_paper = (
            (avg_in * in_price * 0.5 + avg_cache_read * in_price * 0.1 * 0.5 + avg_out * out_price * 0.5)
            / 1_000_000
        )
        print(f"\nobserved avg/call: input={avg_in:.0f} cache_read={avg_cache_read:.0f} "
              f"output={avg_out:.0f} tokens")
        print(f"rough batch-API cost estimate for all {n_papers} papers: "
              f"${per_paper * n_papers:.2f} (${per_paper:.4f}/paper)")


# --------------------------------------------------------------- batch ----

def custom_id_for(arxiv_id: str) -> str:
    """Batch custom_id must match ^[a-zA-Z0-9_-]{1,64}$ — new-style arXiv ids
    contain '.' (e.g. 2211.10438), which isn't allowed. Every id in this
    corpus is either bare digits or a single 'digits.digits' (verified: no
    id contains '-'), so '.' <-> '-' is a safe, unambiguous round-trip."""
    return arxiv_id.replace(".", "-")


def arxiv_id_from(custom_id: str) -> str:
    return custom_id.replace("-", ".")


def already_extracted() -> set[str]:
    if not EXTRACTIONS.exists():
        return set()
    done = set()
    with EXTRACTIONS.open(encoding="utf-8") as f:
        for line in f:
            done.add(json.loads(line)["arxiv_id"])
    return done


def run_submit() -> None:
    client = anthropic.Anthropic()
    papers = load_papers()
    done = already_extracted()
    pending = [p for aid, p in papers.items() if aid not in done]
    print(f"[extract] {len(done)} already extracted, {len(pending)} pending")
    if not pending:
        print("[extract] nothing to submit")
        return

    # Same list object reused for every request so the rendered bytes are
    # identical and the cache actually hits — see batches.md "Batch with
    # Prompt Caching".
    shared_system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

    requests = [
        Request(
            custom_id=custom_id_for(p["arxiv_id"]),
            params=MessageCreateParamsNonStreaming(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=shared_system,
                output_config=output_config(),
                messages=[{"role": "user", "content": user_prompt(p)}],
            ),
        )
        for p in pending
    ]

    # Batch cap is 100,000 requests / 256MB — comfortably above our pending
    # count, so one batch covers everything.
    batch = client.messages.batches.create(requests=requests)
    print(f"[extract] submitted batch {batch.id} ({len(requests)} requests)")
    BATCH_ID_FILE.write_text(batch.id, encoding="utf-8")
    print(f"[extract] batch id saved to {BATCH_ID_FILE}")
    print("[extract] check status any time with: python extract.py --poll")
    print("[extract] or block until done with:   python extract.py --poll --wait")


def run_poll(wait: bool) -> None:
    if not BATCH_ID_FILE.exists():
        print(f"no batch id at {BATCH_ID_FILE} — run --submit first")
        return

    client = anthropic.Anthropic()
    batch_id = BATCH_ID_FILE.read_text(encoding="utf-8").strip()

    batch = client.messages.batches.retrieve(batch_id)
    while True:
        print(f"[extract] batch {batch_id}: {batch.processing_status} "
              f"({batch.request_counts.succeeded} ok, "
              f"{batch.request_counts.errored} errored, "
              f"{batch.request_counts.processing} processing)")
        if batch.processing_status == "ended" or not wait:
            break
        time.sleep(60)
        batch = client.messages.batches.retrieve(batch_id)

    if batch.processing_status != "ended":
        print("[extract] not finished yet; re-run --poll later")
        return

    RAW_BATCH.mkdir(parents=True, exist_ok=True)
    raw_file = RAW_BATCH / f"{batch_id}.jsonl"
    n_ok = n_err = 0
    with EXTRACTIONS.open("a", encoding="utf-8") as out, raw_file.open("w", encoding="utf-8") as raw:
        for result in client.messages.batches.results(batch_id):
            raw.write(result.model_dump_json() + "\n")
            if result.result.type != "succeeded":
                n_err += 1
                print(f"  !! {result.custom_id}: {result.result.type}")
                continue
            parsed = parse_response_text(result.result.message)
            out.write(json.dumps({"arxiv_id": arxiv_id_from(result.custom_id), **parsed}) + "\n")
            n_ok += 1

    print(f"[extract] collected {n_ok} extractions, {n_err} errors -> {EXTRACTIONS}")


# ------------------------------------------------------------------ report ----

def write_report() -> None:
    if not EXTRACTIONS.exists():
        print(f"no {EXTRACTIONS} yet")
        return

    rows = [json.loads(l) for l in EXTRACTIONS.read_text(encoding="utf-8").splitlines()]
    lines = [f"papers extracted: {len(rows)}"]

    entity_types = Counter()
    relations = Counter()
    n_entities = n_triples = 0
    for r in rows:
        n_entities += len(r["entities"])
        n_triples += len(r["triples"])
        entity_types.update(e["type"] for e in r["entities"])
        relations.update(t["relation"] for t in r["triples"])

    lines.append(f"total entities: {n_entities}  (avg {n_entities / max(len(rows), 1):.1f}/paper)")
    lines.append(f"total triples:  {n_triples}  (avg {n_triples / max(len(rows), 1):.1f}/paper)")
    lines.append("\nentities by type:")
    for t, n in entity_types.most_common():
        lines.append(f"  {n:6d}  {t}")
    lines.append("\ntriples by relation:")
    for rel, n in relations.most_common():
        lines.append(f"  {n:6d}  {rel}")

    text = "\n".join(lines)
    REPORT.write_text(text, encoding="utf-8")
    print("\n" + "=" * 70 + "\n" + text + "\n" + "=" * 70)
    print(f"\nreport saved to {REPORT}")


# -------------------------------------------------------------------- main ----

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true",
                    help="run only the 5 hand-labeled papers, diff against hand_labels.md")
    ap.add_argument("--submit", action="store_true",
                    help="submit a batch for all not-yet-extracted papers")
    ap.add_argument("--poll", action="store_true",
                    help="check / collect the submitted batch")
    ap.add_argument("--wait", action="store_true",
                    help="with --poll, block until the batch finishes (checks every 60s)")
    ap.add_argument("--report", action="store_true",
                    help="regenerate the sanity report")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)

    if args.validate:
        run_validate()
    elif args.submit:
        run_submit()
    elif args.poll:
        run_poll(wait=args.wait)
    elif args.report:
        write_report()
    else:
        print("specify one of --validate, --submit, --poll, --report")


if __name__ == "__main__":
    main()
