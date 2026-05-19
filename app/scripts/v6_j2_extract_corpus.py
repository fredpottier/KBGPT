"""V6-J2 — Batch extraction Reference sur les 38 docs du corpus.

Calque architectural de `v6_j1_extract_corpus.py` (V6-J1).

Itère sur tous les /app/data/poc_a/structures/*.json, applique
ReferenceExtractor sur chaque section, persiste dans Neo4j.

Sauvegarde progressive : 1 fichier JSON par doc + 1 manifest agrégé.
Reprise possible (--resume) : skip docs déjà traités via checkpoint files.

Usage :
    docker exec -e TOGETHER_API_KEY= -d knowbase-worker bash -c "\\
      python /app/scripts/v6_j2_extract_corpus.py \\
        --run-tag v6j2_corpus_$(date +%Y%m%d_%H%M%S) \\
        > /tmp/v6_j2_corpus.log 2>&1"

Estimation : 38 docs × ~26 sections × 5s = ~5000s = ~80 min. Coût ~$0.5-1.
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
    ReferenceExtractor,
    ReferencePersister,
    extract_references_for_doc,
    ensure_v6_schema,
)
from knowbase.runtime_v5.structure_loader import (
    load_structure,
    list_available_doc_ids,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-tag", required=True)
    parser.add_argument("--limit-docs", type=int, default=0,
                        help="Limiter aux N premiers docs (0=tous)")
    parser.add_argument("--limit-sections-per-doc", type=int, default=0)
    parser.add_argument("--model", default="")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--reextract", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--section-min-chars", type=int, default=200)
    args = parser.parse_args()

    print(f"=== V6-J2 — batch corpus extraction ===")
    print(f"run_tag: {args.run_tag}")
    print(f"model: {args.model or os.getenv('V6_EXTRACT_MODEL') or 'DS-V3.1 (default)'}")
    print(f"tenant: {args.tenant_id}")
    print(f"resume: {args.resume} | reextract: {args.reextract}")
    print(f"limit_docs: {args.limit_docs or 'all'} | limit_sections: {args.limit_sections_per_doc or 'all'}\n")

    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    run_dir = root / "benchmark/runs/v6_j2_corpus" / args.run_tag
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    print(f"checkpoints: {run_dir}\n")

    manifest: dict = {"run_tag": args.run_tag, "started_at": None, "docs": {}}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not manifest.get("started_at"):
        manifest["started_at"] = datetime.utcnow().isoformat() + "Z"

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    print("Ensuring V6 schema...")
    schema_stats = ensure_v6_schema(driver)
    print(f"  constraints={schema_stats['constraints_applied']} indexes={schema_stats['indexes_applied']} errors={schema_stats['errors']}\n")

    persister = ReferencePersister(driver, tenant_id=args.tenant_id)
    extractor = ReferenceExtractor(model=args.model or None)

    all_doc_ids = list_available_doc_ids()
    if args.limit_docs > 0:
        all_doc_ids = all_doc_ids[: args.limit_docs]
    print(f"Total docs to process: {len(all_doc_ids)}\n")

    t_global = time.time()
    grand_totals = {
        "docs_processed": 0,
        "docs_skipped_resume": 0,
        "sections_total": 0,
        "sections_with_ref": 0,
        "references": 0,
        "llm_errors": 0,
        "parse_errors": 0,
        "validation_errors": 0,
    }

    for d_idx, doc_id in enumerate(all_doc_ids):
        elapsed = time.time() - t_global
        print(f"\n[{d_idx+1:2d}/{len(all_doc_ids)}] {doc_id}  (t+{elapsed:.0f}s)")

        ckpt_path = run_dir / f"{doc_id}.json"
        if args.resume and ckpt_path.exists():
            try:
                prev = json.loads(ckpt_path.read_text(encoding="utf-8"))
                if prev.get("_meta", {}).get("completed"):
                    n_ref = prev["_meta"].get("references_persisted", 0)
                    print(f"  SKIP (resume) — already done: {n_ref} reference(s)")
                    grand_totals["docs_skipped_resume"] += 1
                    continue
            except Exception:
                pass

        struct = load_structure(doc_id)
        if struct is None:
            print(f"  ERROR: structure not found, skipping")
            continue
        sections = list(struct.sections)
        if args.limit_sections_per_doc > 0:
            sections = sections[: args.limit_sections_per_doc]

        if args.reextract:
            n_del = persister.delete_references_for_doc(doc_id)
            if n_del > 0:
                print(f"  purged {n_del} existing reference(s)")

        # Reset stats per-doc
        for k in list(extractor.stats):
            extractor.stats[k] = 0.0 if k == "latency_total_s" else 0
        for k in list(persister.stats):
            persister.stats[k] = 0

        sections_input = [
            {"section_id": s.get("section_id", ""),
             "title": s.get("title", ""),
             "text": s.get("text", "")}
            for s in sections
        ]
        sections_skipped = sum(
            1 for s in sections_input
            if not s["section_id"] or len(s["text"]) < args.section_min_chars
        )

        t_doc = time.time()
        sections_with_ref = 0

        def progress(i, total, sec_id, n):
            nonlocal sections_with_ref
            if n > 0:
                sections_with_ref += 1

        results, ext_stats = extract_references_for_doc(
            doc_id=doc_id,
            sections=sections_input,
            extractor=extractor,
            section_min_chars=args.section_min_chars,
            progress_cb=progress,
        )
        elapsed_doc = time.time() - t_doc

        if results:
            persister.persist_batch(doc_id, results)

        per_stats = {
            "completed": True,
            "elapsed_s": elapsed_doc,
            "sections_total": len(sections_input),
            "sections_skipped": sections_skipped,
            "sections_with_reference": sections_with_ref,
            "references_extracted": len(results),
            "references_persisted": persister.stats["references_persisted"],
            "evidence_links": persister.stats["evidence_links_created"],
            "extractor_stats": dict(ext_stats),
            "persister_stats": dict(persister.stats),
        }

        ckpt_path.write_text(json.dumps({
            "_meta": {**per_stats, "doc_id": doc_id, "model": extractor.model,
                      "ts": datetime.utcnow().isoformat() + "Z"},
            "references": [
                {"section_id": sid, **ref.model_dump(mode="json")}
                for sid, ref in results
            ],
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        grand_totals["docs_processed"] += 1
        grand_totals["sections_total"] += len(sections_input)
        grand_totals["sections_with_ref"] += sections_with_ref
        grand_totals["references"] += len(results)
        grand_totals["llm_errors"] += ext_stats.get("llm_errors", 0)
        grand_totals["parse_errors"] += ext_stats.get("parse_errors", 0)
        grand_totals["validation_errors"] += ext_stats.get("validation_errors", 0)

        manifest["docs"][doc_id] = per_stats
        manifest["totals"] = dict(grand_totals)
        manifest["last_update"] = datetime.utcnow().isoformat() + "Z"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        print(f"  {len(results):3d} reference(s) | "
              f"sections {sections_with_ref}/{len(sections_input)-sections_skipped} | "
              f"{elapsed_doc:.0f}s")

    total_elapsed = time.time() - t_global
    manifest["finished_at"] = datetime.utcnow().isoformat() + "Z"
    manifest["total_elapsed_s"] = total_elapsed
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n{'=' * 60}\nGRAND TOTALS (V6-J2 corpus extraction)\n{'=' * 60}")
    print(f"Total elapsed: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"Docs processed: {grand_totals['docs_processed']}")
    print(f"Docs skipped (resume): {grand_totals['docs_skipped_resume']}")
    print(f"Sections total: {grand_totals['sections_total']}")
    print(f"Sections with reference: {grand_totals['sections_with_ref']}")
    print(f"References extracted: {grand_totals['references']}")
    print(f"Errors: llm={grand_totals['llm_errors']} parse={grand_totals['parse_errors']} "
          f"validation={grand_totals['validation_errors']}")
    print(f"\nManifest: {manifest_path}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
