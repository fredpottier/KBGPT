"""V6-J1 — Script de test : extraction Procedure sur 1 doc complet + persistance Neo4j.

Pipeline :
  1. Charge le doc structure depuis /app/data/poc_a/structures/<doc_id>.json
  2. Ensure V6 schema (constraints + indexes Neo4j) une fois
  3. (Option) Purge les Procedure existantes pour ce doc (--reextract)
  4. Pour chaque section assez longue, appelle ProcedureExtractor (DS-V3.1 ou
     V6_EXTRACT_MODEL override)
  5. Persiste Procedure + ProcedureStep via ProcedurePersister
  6. Persiste aussi le JSON brut des extractions pour audit offline

Usage :
    docker exec knowbase-app python scripts/v6_j1_extract_doc.py \\
        --doc-id 014_SAP_S4HANA_2021_Operations_Guide_819d2c07 [--reextract]
    docker exec knowbase-app python scripts/v6_j1_extract_doc.py \\
        --doc-id <id> --limit 10  # limite à 10 sections pour test rapide
    docker exec knowbase-app python scripts/v6_j1_extract_doc.py \\
        --doc-id <id> --model Qwen/Qwen2.5-72B-Instruct  # bake-off
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

from knowbase.claimfirst.v6 import (
    ProcedureExtractor,
    ProcedurePersister,
    extract_procedures_for_doc,
    ensure_v6_schema,
)
from knowbase.runtime_v5.structure_loader import load_structure


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--doc-id",
        default="014_SAP_S4HANA_2021_Operations_Guide_819d2c07",
        help="Doc id à traiter (présent dans /app/data/poc_a/structures/<id>.json)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limiter aux N premières sections (0 = pas de limite)",
    )
    parser.add_argument(
        "--model", default="",
        help="Override modèle (sinon V6_EXTRACT_MODEL env ou DS-V3.1)",
    )
    parser.add_argument(
        "--tenant-id", default="default",
    )
    parser.add_argument(
        "--reextract", action="store_true",
        help="Purge les Procedure existantes pour ce doc avant ré-extraction",
    )
    parser.add_argument(
        "--section-min-chars", type=int, default=200,
        help="Skip sections plus courtes que ce seuil (default 200)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Extrait seulement (pas de persistance Neo4j)",
    )
    args = parser.parse_args()

    print(f"=== V6-J1 — extraction Procedure pour 1 doc ===")
    print(f"doc_id: {args.doc_id}")
    print(f"model: {args.model or os.getenv('V6_EXTRACT_MODEL') or 'deepseek-ai/DeepSeek-V3.1 (default)'}")
    print(f"tenant: {args.tenant_id}")
    print(f"limit: {args.limit or 'all'}, section_min_chars: {args.section_min_chars}")
    print(f"reextract: {args.reextract} | dry_run: {args.dry_run}\n")

    # 1. Load structure
    struct = load_structure(args.doc_id)
    if struct is None:
        print(f"ERROR: doc {args.doc_id} not found in /app/data/poc_a/structures/")
        return 1
    sections = list(struct.sections)
    if args.limit > 0:
        sections = sections[: args.limit]
    print(f"Sections found: {len(sections)} (n_pages={struct.n_pages})\n")

    # 2. Neo4j driver + schema ensure
    driver = None
    persister = None
    if not args.dry_run:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
        print(f"Neo4j: {neo4j_uri}")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        print("Ensuring V6 schema...")
        schema_stats = ensure_v6_schema(driver)
        print(f"  constraints={schema_stats['constraints_applied']} "
              f"indexes={schema_stats['indexes_applied']} "
              f"errors={schema_stats['errors']}\n")

        persister = ProcedurePersister(driver, tenant_id=args.tenant_id)
        if args.reextract:
            n_deleted = persister.delete_procedures_for_doc(args.doc_id)
            print(f"Purged {n_deleted} existing Procedure(s) for doc.\n")

    # 3. Extract loop
    extractor = ProcedureExtractor(
        model=args.model or None,
        min_steps=2,
    )

    t0 = time.time()
    all_procs: list[dict] = []
    sections_with_proc = 0
    sections_skipped = 0
    sections_failed = 0

    def progress(i: int, total: int, sec_id: str, n: int):
        nonlocal sections_with_proc
        elapsed = int(time.time() - t0)
        prefix = f"[{i:3d}/{total}] t+{elapsed:4d}s"
        if not sec_id:
            print(f"{prefix} skip (no section_id)")
            return
        if n > 0:
            sections_with_proc += 1
            print(f"{prefix} {sec_id} → +{n} procedure(s)")
        # No-op (no print) if 0 — too verbose

    sections_input = [
        {
            "section_id": s.get("section_id", ""),
            "title": s.get("title", ""),
            "text": s.get("text", ""),
        }
        for s in sections
    ]
    sections_skipped = sum(
        1 for s in sections_input
        if not s["section_id"] or len(s["text"]) < args.section_min_chars
    )

    results, stats = extract_procedures_for_doc(
        doc_id=args.doc_id,
        sections=sections_input,
        extractor=extractor,
        section_min_chars=args.section_min_chars,
        progress_cb=progress,
    )

    total_elapsed = time.time() - t0
    print(f"\n=== Extraction done in {total_elapsed:.1f}s ===")
    print(f"Sections processed: {len(sections_input) - sections_skipped} "
          f"(skipped: {sections_skipped})")
    print(f"Sections with at least 1 procedure: {sections_with_proc}")
    print(f"Total procedures extracted: {len(results)}")
    print(f"LLM stats: calls={stats['calls']} llm_errors={stats['llm_errors']} "
          f"parse_errors={stats['parse_errors']} validation_errors={stats['validation_errors']}")
    print(f"Tokens: in={stats['tokens_in']} out={stats['tokens_out']} "
          f"latency_total={stats['latency_total_s']:.1f}s")
    print(f"Procedures filtered (< {extractor.min_steps} steps): "
          f"{stats['procedures_filtered_min_steps']}\n")

    # 4. Persist Neo4j (if not dry-run)
    if not args.dry_run and results:
        print(f"Persisting {len(results)} procedure(s) to Neo4j...")
        persister.persist_batch(args.doc_id, results)
        print(f"  procedures_persisted: {persister.stats['procedures_persisted']}")
        print(f"  steps_persisted: {persister.stats['steps_persisted']}")
        print(f"  evidence_links: {persister.stats['evidence_links_created']}")
        print(f"  doc_links: {persister.stats['doc_links_created']}")
        print(f"  errors: {persister.stats['errors']}\n")

    # 5. Persist JSON raw output (offline audit)
    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = root / f"benchmark/runs/v6_j1_procedures_{args.doc_id}_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "_meta": {
            "ts": ts,
            "doc_id": args.doc_id,
            "model": extractor.model,
            "tenant_id": args.tenant_id,
            "sections_total": len(sections_input),
            "sections_skipped": sections_skipped,
            "sections_with_procedure": sections_with_proc,
            "elapsed_s": total_elapsed,
            "extractor_stats": stats,
            "persister_stats": (persister.stats if persister else None),
        },
        "procedures": [
            {"section_id": sec_id, **proc.model_dump(mode="json")}
            for sec_id, proc in results
        ],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved JSON audit: {out_path}\n")

    # 6. Sample print (3 first procedures)
    if results:
        print("=== Sample (3 first procedures) ===")
        for sec_id, proc in results[:3]:
            print(f"\n[section={sec_id}]")
            print(f"  • {proc.name}")
            print(f"    goal: {proc.goal}")
            if proc.prerequisites:
                print(f"    prereq: {', '.join(proc.prerequisites)}")
            for s in proc.steps:
                note = f"  ({s.notes})" if s.notes else ""
                print(f"    {s.step_number}. {s.action[:140]}{note}")
        print("\n===")

    if driver is not None:
        driver.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
