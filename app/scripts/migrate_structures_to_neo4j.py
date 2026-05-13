"""V5 DSG — Migration des structures JSON vers Neo4j multi-tenant.

ADR V1.5 §3b — Sprint S1.3.

Lit data/poc_a/structures/*.json (structures Docling page-fallback POC-A
+ SAP) et les persiste dans Neo4j sous labels V5* avec composite keys
(tenant_id, doc_id) / (tenant_id, section_id).

Usage :
    docker exec knowbase-app python scripts/migrate_structures_to_neo4j.py \\
        --tenant-id default \\
        --source-dir data/poc_a/structures \\
        --dry-run

Options :
    --tenant-id   (default: "default")
    --source-dir  (default: "data/poc_a/structures")
    --dry-run     (par défaut False — preview comptes uniquement)
    --purge-first (par défaut False — purge le tenant V5 avant migration)
    --doc-pattern (default: "*.json" — glob filter, ex: "003_*.json")

Idempotent : MERGE sur composite keys, peut être relancé sans dupliquer.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from knowbase.runtime_v5.neo4j_dsg import get_v5_dsg

logger = logging.getLogger("v5_migrate")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def migrate_document(dsg, tenant_id: str, doc_json: dict, dry_run: bool = False) -> dict:
    """Migre 1 document JSON → Neo4j V5 DSG.

    Returns:
        {"doc_id", "n_sections_input", "n_sections_upserted", "n_parent_links", "duration_s"}
    """
    t0 = time.time()
    doc_id = doc_json["doc_id"]
    doc_name = doc_json.get("doc_name", doc_id)
    n_pages = doc_json.get("n_pages", 0)
    sections = doc_json.get("sections", []) or []
    extractor = doc_json.get("extractor_version", "docling-page-fallback")

    stats = {
        "doc_id": doc_id,
        "n_sections_input": len(sections),
        "n_sections_upserted": 0,
        "n_parent_links": 0,
        "duration_s": 0.0,
        "errors": [],
    }

    if dry_run:
        logger.info(f"[DRY-RUN] {doc_id}: {len(sections)} sections, {n_pages} pages")
        stats["duration_s"] = time.time() - t0
        return stats

    # 1. Upsert Document
    try:
        dsg.upsert_document(
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_name=doc_name,
            n_pages=n_pages,
            extractor_version=extractor,
            active_status="active",
        )
    except Exception as e:
        stats["errors"].append(f"doc_upsert: {e}")
        logger.error(f"[{doc_id}] doc_upsert failed: {e}")
        stats["duration_s"] = time.time() - t0
        return stats

    # 2. Upsert chaque section
    parent_links_pending: list[tuple[str, str, int]] = []  # (parent_id, child_id, order)
    for idx, sec in enumerate(sections):
        try:
            dsg.upsert_section(tenant_id=tenant_id, doc_id=doc_id, section=sec)
            stats["n_sections_upserted"] += 1
            # Si parent_id défini, prépare la liaison HAS_CHILD
            parent_id = sec.get("parent_id")
            if parent_id:
                parent_links_pending.append((parent_id, sec["section_id"], idx))
        except Exception as e:
            stats["errors"].append(f"section[{idx}]: {e}")
            logger.error(f"[{doc_id}] section[{idx}] upsert failed: {e}")

    # 3. Liens HAS_CHILD (après que toutes les sections existent)
    for parent_id, child_id, order in parent_links_pending:
        try:
            dsg.link_section_parent(
                tenant_id=tenant_id,
                section_id=child_id,
                parent_section_id=parent_id,
                order=order,
            )
            stats["n_parent_links"] += 1
        except Exception as e:
            stats["errors"].append(f"parent_link {parent_id}→{child_id}: {e}")
            logger.warning(f"[{doc_id}] parent_link failed: {e}")

    stats["duration_s"] = round(time.time() - t0, 3)
    return stats


def main():
    parser = argparse.ArgumentParser(description="V5 DSG : migration JSON → Neo4j")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--source-dir", default="data/poc_a/structures")
    parser.add_argument("--doc-pattern", default="*.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--purge-first", action="store_true",
                        help="Purge le tenant V5 DSG AVANT migration")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limite N premiers fichiers (0 = tous)")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    if not source_dir.is_absolute():
        # Résoudre depuis /app dans le container
        source_dir = Path("/app") / source_dir
    if not source_dir.exists():
        logger.error(f"Source dir not found: {source_dir}")
        return 1

    files = sorted(source_dir.glob(args.doc_pattern))
    if args.limit > 0:
        files = files[: args.limit]

    logger.info(f"Found {len(files)} structure files in {source_dir}")
    logger.info(f"Tenant: {args.tenant_id} | Dry-run: {args.dry_run} | Purge-first: {args.purge_first}")

    dsg = get_v5_dsg()

    # 1. Setup schema (idempotent)
    logger.info("Ensuring schema...")
    sch = dsg.setup_schema()
    logger.info(f"Schema: {sch['applied']}/{sch['total']} applied, {len(sch['errors'])} errors")
    if sch["errors"]:
        for err in sch["errors"]:
            logger.warning(f"  - {err}")

    # 2. Purge tenant (optionnel)
    if args.purge_first and not args.dry_run:
        logger.warning(f"Purging tenant '{args.tenant_id}' before migration...")
        purge_res = dsg.tenant_purge(args.tenant_id, confirm=True)
        logger.info(f"Purge: {purge_res['before']} -> {purge_res['after']}")

    # 3. Migration
    total_stats = {
        "n_docs": 0,
        "n_docs_with_errors": 0,
        "n_sections_input": 0,
        "n_sections_upserted": 0,
        "n_parent_links": 0,
        "duration_s": 0.0,
    }
    per_doc = []
    t_global = time.time()

    for f in files:
        try:
            doc_json = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"[{f.name}] parse failed: {e}")
            total_stats["n_docs_with_errors"] += 1
            continue

        stats = migrate_document(dsg, args.tenant_id, doc_json, dry_run=args.dry_run)
        per_doc.append(stats)
        total_stats["n_docs"] += 1
        total_stats["n_sections_input"] += stats["n_sections_input"]
        total_stats["n_sections_upserted"] += stats["n_sections_upserted"]
        total_stats["n_parent_links"] += stats["n_parent_links"]
        if stats["errors"]:
            total_stats["n_docs_with_errors"] += 1
        logger.info(
            f"  {stats['doc_id']}: {stats['n_sections_upserted']}/{stats['n_sections_input']} sections, "
            f"{stats['n_parent_links']} parent links, {stats['duration_s']}s "
            f"{'(errors: ' + str(len(stats['errors'])) + ')' if stats['errors'] else ''}"
        )

    total_stats["duration_s"] = round(time.time() - t_global, 2)

    # 4. Stats finales tenant
    if not args.dry_run:
        final_stats = dsg.tenant_stats(args.tenant_id)
        logger.info(f"Tenant '{args.tenant_id}' post-migration: {final_stats}")
        total_stats["tenant_neo4j_counts"] = final_stats

    # 5. Récap TenantQueryGuard
    guard_stats = dsg.guard.stats()
    logger.info(f"TenantQueryGuard stats: {guard_stats}")
    total_stats["guard_stats"] = guard_stats

    logger.info("=" * 70)
    logger.info(f"MIGRATION COMPLETE")
    logger.info(f"  Docs: {total_stats['n_docs']} ({total_stats['n_docs_with_errors']} with errors)")
    logger.info(f"  Sections: {total_stats['n_sections_upserted']}/{total_stats['n_sections_input']}")
    logger.info(f"  Parent links: {total_stats['n_parent_links']}")
    logger.info(f"  Duration: {total_stats['duration_s']}s")
    logger.info("=" * 70)

    return 0 if total_stats["n_docs_with_errors"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
