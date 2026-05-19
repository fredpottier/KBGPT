"""V6-J1 — Batch extraction Procedure sur les 38 docs du corpus SAP.

Itère sur tous les /app/data/poc_a/structures/*.json, applique
ProcedureExtractor sur chaque section, persiste dans Neo4j.

Sauvegarde progressive : 1 fichier JSON par doc + 1 manifest agrégé.
Reprise possible (skip docs déjà traités via --resume) : on cherche
les fichiers de checkpoint sous benchmark/runs/v6_j1_corpus/<run_tag>/.

Usage :
    docker exec knowbase-app python scripts/v6_j1_extract_corpus.py \\
        --run-tag corpus_2026_05_15 [--limit-docs N] [--resume] [--reextract]

Estimation : 38 docs × ~30 sections × 36s = ~38000s = ~10h. Coût ~$5-10
en DS-V3.1 via DeepInfra (charte open-source serverless).
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
from knowbase.runtime_v5.structure_loader import (
    load_structure,
    list_available_doc_ids,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-tag", required=True,
        help="Tag pour le run (sert de dossier de checkpoint).",
    )
    parser.add_argument(
        "--limit-docs", type=int, default=0,
        help="Limiter aux N premiers docs (0 = tous les 38)",
    )
    parser.add_argument(
        "--limit-sections-per-doc", type=int, default=0,
        help="Limiter aux N premières sections par doc (0 = toutes)",
    )
    parser.add_argument(
        "--model", default="",
        help="Override modèle (sinon V6_EXTRACT_MODEL ou DS-V3.1)",
    )
    parser.add_argument(
        "--tenant-id", default="default",
    )
    parser.add_argument(
        "--reextract", action="store_true",
        help="Purge Procedure existantes pour chaque doc avant traitement",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip les docs ayant déjà un checkpoint dans run-tag",
    )
    parser.add_argument(
        "--section-min-chars", type=int, default=200,
    )
    args = parser.parse_args()

    # ── Setup ────────────────────────────────────────────────────────────────
    print(f"=== V6-J1 — batch corpus extraction ===")
    print(f"run_tag: {args.run_tag}")
    print(f"model: {args.model or os.getenv('V6_EXTRACT_MODEL') or 'DS-V3.1 (default)'}")
    print(f"tenant: {args.tenant_id}")
    print(f"resume: {args.resume} | reextract: {args.reextract}")
    print(f"limit_docs: {args.limit_docs or 'all'} | limit_sections: {args.limit_sections_per_doc or 'all'}\n")

    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    run_dir = root / "benchmark/runs/v6_j1_corpus" / args.run_tag
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    print(f"checkpoints: {run_dir}\n")

    # Charge manifest si existant
    manifest: dict = {"run_tag": args.run_tag, "started_at": None, "docs": {}}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not manifest.get("started_at"):
        manifest["started_at"] = datetime.utcnow().isoformat() + "Z"

    # Neo4j driver
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    print("Ensuring V6 schema...")
    schema_stats = ensure_v6_schema(driver)
    print(f"  constraints={schema_stats['constraints_applied']} indexes={schema_stats['indexes_applied']} errors={schema_stats['errors']}\n")

    persister = ProcedurePersister(driver, tenant_id=args.tenant_id)
    extractor = ProcedureExtractor(model=args.model or None, min_steps=2)

    # ── Liste des docs ───────────────────────────────────────────────────────
    all_doc_ids = list_available_doc_ids()
    if args.limit_docs > 0:
        all_doc_ids = all_doc_ids[: args.limit_docs]
    print(f"Total docs to process: {len(all_doc_ids)}\n")

    # ── Loop docs ────────────────────────────────────────────────────────────
    t_global = time.time()
    grand_totals = {
        "docs_processed": 0,
        "docs_skipped_resume": 0,
        "sections_total": 0,
        "sections_with_proc": 0,
        "procedures": 0,
        "steps": 0,
        "llm_errors": 0,
        "parse_errors": 0,
        "validation_errors": 0,
    }

    for d_idx, doc_id in enumerate(all_doc_ids):
        elapsed = time.time() - t_global
        print(f"\n[{d_idx+1:2d}/{len(all_doc_ids)}] {doc_id}  (t+{elapsed:.0f}s)")

        # Resume : skip si checkpoint déjà valide
        ckpt_path = run_dir / f"{doc_id}.json"
        if args.resume and ckpt_path.exists():
            try:
                prev = json.loads(ckpt_path.read_text(encoding="utf-8"))
                if prev.get("_meta", {}).get("completed"):
                    n_proc = prev["_meta"].get("procedures_persisted", 0)
                    print(f"  SKIP (resume) — already done: {n_proc} procedure(s)")
                    grand_totals["docs_skipped_resume"] += 1
                    continue
            except Exception:
                pass

        # Charge structure
        struct = load_structure(doc_id)
        if struct is None:
            print(f"  ERROR: structure not found, skipping")
            continue
        sections = list(struct.sections)
        if args.limit_sections_per_doc > 0:
            sections = sections[: args.limit_sections_per_doc]

        # Purge si demandé
        if args.reextract:
            n_del = persister.delete_procedures_for_doc(doc_id)
            if n_del > 0:
                print(f"  purged {n_del} existing procedure(s)")

        # Reset stats per-doc
        extractor.stats = {k: 0 for k in extractor.stats}
        extractor.stats["latency_total_s"] = 0.0
        persister.stats = {k: 0 for k in persister.stats}

        # Extract
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

        t_doc = time.time()
        sections_with_proc = 0

        def progress(i: int, total: int, sec_id: str, n: int):
            nonlocal sections_with_proc
            if n > 0:
                sections_with_proc += 1

        results, ext_stats = extract_procedures_for_doc(
            doc_id=doc_id,
            sections=sections_input,
            extractor=extractor,
            section_min_chars=args.section_min_chars,
            progress_cb=progress,
        )
        elapsed_doc = time.time() - t_doc

        # Persist
        if results:
            persister.persist_batch(doc_id, results)

        # Stats per-doc
        per_stats = {
            "completed": True,
            "elapsed_s": elapsed_doc,
            "sections_total": len(sections_input),
            "sections_skipped": sections_skipped,
            "sections_with_procedure": sections_with_proc,
            "procedures_extracted": len(results),
            "procedures_persisted": persister.stats["procedures_persisted"],
            "steps_persisted": persister.stats["steps_persisted"],
            "evidence_links": persister.stats["evidence_links_created"],
            "extractor_stats": dict(ext_stats),
            "persister_stats": dict(persister.stats),
        }

        # Checkpoint
        ckpt_path.write_text(json.dumps({
            "_meta": {**per_stats, "doc_id": doc_id, "model": extractor.model,
                      "ts": datetime.utcnow().isoformat() + "Z"},
            "procedures": [
                {"section_id": sid, **proc.model_dump(mode="json")}
                for sid, proc in results
            ],
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        # Update grand totals
        grand_totals["docs_processed"] += 1
        grand_totals["sections_total"] += len(sections_input)
        grand_totals["sections_with_proc"] += sections_with_proc
        grand_totals["procedures"] += len(results)
        grand_totals["steps"] += persister.stats["steps_persisted"]
        grand_totals["llm_errors"] += ext_stats.get("llm_errors", 0)
        grand_totals["parse_errors"] += ext_stats.get("parse_errors", 0)
        grand_totals["validation_errors"] += ext_stats.get("validation_errors", 0)

        # Update manifest (live)
        manifest["docs"][doc_id] = per_stats
        manifest["totals"] = dict(grand_totals)
        manifest["last_update"] = datetime.utcnow().isoformat() + "Z"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        print(f"  {len(results):3d} procedure(s) | "
              f"{persister.stats['steps_persisted']:3d} steps | "
              f"sections {sections_with_proc}/{len(sections_input)-sections_skipped} | "
              f"{elapsed_doc:.0f}s")

    # ── Summary ──────────────────────────────────────────────────────────────
    total_elapsed = time.time() - t_global
    manifest["finished_at"] = datetime.utcnow().isoformat() + "Z"
    manifest["total_elapsed_s"] = total_elapsed
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n{'=' * 60}\nGRAND TOTALS (V6-J1 corpus extraction)\n{'=' * 60}")
    print(f"Total elapsed: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"Docs processed: {grand_totals['docs_processed']}")
    print(f"Docs skipped (resume): {grand_totals['docs_skipped_resume']}")
    print(f"Sections total: {grand_totals['sections_total']}")
    print(f"Sections with procedure: {grand_totals['sections_with_proc']}")
    print(f"Procedures extracted: {grand_totals['procedures']}")
    print(f"Steps persisted: {grand_totals['steps']}")
    print(f"Errors: llm={grand_totals['llm_errors']} parse={grand_totals['parse_errors']} "
          f"validation={grand_totals['validation_errors']}")
    print(f"\nManifest: {manifest_path}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
