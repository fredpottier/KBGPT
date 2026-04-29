#!/usr/bin/env python3
"""
Replay isole de la Phase 8 (persistance Qdrant) depuis le cache extraction.

Cas d'usage: docs deja dans Neo4j (DocumentContext + Claims) mais sans chunks
Qdrant (failure silencieux Phase 8 d'origine — incident 2026-04-27 / cs25_amdt_23/24).

Idempotent: delete_doc + upsert. Re-run = meme resultat.

Utilisation:
    docker compose exec app python scripts/replay_qdrant_phase8.py \
        --doc-id cs25_amdt_23_0869bab2 \
        --tenant-id default

    # Auto-detect orphans (DocumentContext sans qdrant_status=OK):
    docker compose exec app python scripts/replay_qdrant_phase8.py --auto

    # Tester sans persister (dry-run rechunk + count):
    docker compose exec app python scripts/replay_qdrant_phase8.py \
        --doc-id cs25_amdt_23_0869bab2 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

# Bootstrap path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Persistance fichier (incident 2026-04-27) — survit a docker exec interruption / SIGPIPE.
try:
    from knowbase.common.logging import setup_root_file_logging
    os.environ.setdefault("SERVICE_NAME", "replay")
    setup_root_file_logging()
except Exception as _e:
    logging.getLogger(__name__).warning(f"[LOGGING] file logging setup failed: {_e}")

log = logging.getLogger("replay_phase8")


def _get_neo4j_driver():
    from neo4j import GraphDatabase
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, pwd))


def find_cache_for_doc(doc_id: str) -> Optional[Path]:
    """Trouve le cache .v5cache.json correspondant au doc_id (matching par hash prefix)."""
    cache_dir = Path(os.environ.get("KNOWBASE_DATA_DIR", "/data")) / "extraction_cache"
    if not cache_dir.exists():
        cache_dir = Path("data/extraction_cache")
    if not cache_dir.exists():
        return None
    # doc_id format: <stem>_<8charhash>. Le cache est nomme <fullhash>.v5cache.json
    # On charge le mapping en lisant les caches et en comparant document_id
    import json
    for cache_file in cache_dir.glob("*.v5cache.json"):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                # Read first KB only
                head = f.read(2048)
            if doc_id in head or doc_id.rsplit("_", 1)[0] in head:
                # Verify properly
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cache_doc_id = data.get("document_id") or data.get("extraction", {}).get("document_id")
                if cache_doc_id == doc_id:
                    return cache_file
        except Exception:
            continue
    return None


def find_orphans(driver, tenant_id: str) -> List[dict]:
    """Liste les DocumentContext sans qdrant_status=OK."""
    with driver.session() as session:
        rows = session.run(
            """
            MATCH (d:DocumentContext {tenant_id: $tenant_id})
            WHERE coalesce(d.qdrant_status, 'MISSING') <> 'OK'
            RETURN d.doc_id AS doc_id, coalesce(d.qdrant_status, 'MISSING') AS status,
                   coalesce(d.qdrant_chunks_count, 0) AS chunks
            ORDER BY d.doc_id
            """,
            tenant_id=tenant_id,
        ).data()
    return rows


def get_doc_context(driver, doc_id: str, tenant_id: str):
    """Reconstruit un objet doc_context minimal depuis Neo4j (pour applicability_frame)."""
    from types import SimpleNamespace
    with driver.session() as session:
        row = session.run(
            """
            MATCH (d:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
            RETURN d.primary_subject AS primary_subject,
                   d.release_id AS release_id,
                   d.version AS version
            """,
            doc_id=doc_id, tenant_id=tenant_id,
        ).single()
    if not row:
        return None
    af = SimpleNamespace(
        release_id=row.get("release_id"),
        version=row.get("version"),
    )
    ctx = SimpleNamespace(
        primary_subject=row.get("primary_subject") or "",
        applicability_frame=af,
    )
    return ctx


def replay_one(doc_id: str, tenant_id: str, dry_run: bool = False) -> dict:
    """Replay Phase 8 pour un doc_id donne. Retourne stats."""
    log.info(f"=== REPLAY Phase 8: doc_id={doc_id} tenant={tenant_id} ===")

    cache_path = find_cache_for_doc(doc_id)
    if not cache_path:
        log.error(f"No cache file found for doc_id={doc_id}")
        return {"doc_id": doc_id, "status": "NO_CACHE"}
    log.info(f"Cache: {cache_path.name}")

    from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache
    cache_result = load_pass0_from_cache(str(cache_path), tenant_id=tenant_id)
    if not cache_result.success or not cache_result.pass0_result:
        log.error(f"Failed to load cache: {cache_result.error}")
        return {"doc_id": doc_id, "status": "CACHE_LOAD_FAILED", "error": cache_result.error}
    chunks = cache_result.pass0_result.chunks
    log.info(f"Loaded {len(chunks)} TypeAwareChunks from cache")

    if not chunks:
        log.warning(f"Cache contains 0 chunks for {doc_id}")
        return {"doc_id": doc_id, "status": "NO_CHUNKS"}

    driver = _get_neo4j_driver()
    doc_context = get_doc_context(driver, doc_id, tenant_id)
    if not doc_context:
        log.warning(f"No DocumentContext in Neo4j for {doc_id} (will proceed without)")

    if dry_run:
        from knowbase.retrieval.rechunker import rechunk_for_retrieval
        sub_chunks = rechunk_for_retrieval(
            chunks=chunks, tenant_id=tenant_id, doc_id=doc_id,
            target_chars=1500, overlap_chars=200, section_titles={},
        )
        total_chars = sum(len(sc.text) for sc in sub_chunks)
        log.info(
            f"DRY-RUN: rechunked {len(chunks)} → {len(sub_chunks)} sub_chunks, "
            f"total {total_chars} chars (avg {total_chars // max(1, len(sub_chunks))})"
        )
        driver.close()
        return {"doc_id": doc_id, "status": "DRY_RUN", "sub_chunks": len(sub_chunks)}

    # Instanciation legere de l'orchestrator (bypass __init__ lourd) pour appeler les helpers Phase 8.
    # Les attributs requis: neo4j_driver (pour _set_doc_qdrant_status).
    from knowbase.claimfirst.orchestrator import ClaimFirstOrchestrator
    orch = ClaimFirstOrchestrator.__new__(ClaimFirstOrchestrator)
    orch.neo4j_driver = driver
    orch.persist_enabled = True

    # Health check pre-Phase 8
    if not orch._qdrant_health_check():
        log.error("Qdrant health check failed — aborting")
        driver.close()
        return {"doc_id": doc_id, "status": "QDRANT_DOWN"}

    try:
        n = orch._persist_type_aware_chunks_to_qdrant(
            chunks=chunks,
            doc_id=doc_id,
            tenant_id=tenant_id,
            doc_context=doc_context,
        )
        # Persister status OK
        orch._set_doc_qdrant_status(
            doc_id=doc_id, tenant_id=tenant_id, status="OK", chunks_count=n,
        )
        log.info(f"=== REPLAY DONE: {n} points upserted for {doc_id} ===")
        driver.close()
        return {"doc_id": doc_id, "status": "OK", "chunks": n}
    except Exception as e:
        log.error(f"REPLAY FAILED for {doc_id}: {type(e).__name__}: {e}", exc_info=True)
        try:
            orch._set_doc_qdrant_status(
                doc_id=doc_id, tenant_id=tenant_id,
                status=f"FAILED:{type(e).__name__}", error=str(e)[:500],
            )
        except Exception:
            pass
        driver.close()
        return {"doc_id": doc_id, "status": "FAILED", "error": str(e)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--doc-id", help="Doc ID specific (ex: cs25_amdt_23_0869bab2)")
    p.add_argument("--tenant-id", default="default")
    p.add_argument("--auto", action="store_true",
                   help="Auto-detect tous les DocumentContext sans qdrant_status=OK")
    p.add_argument("--dry-run", action="store_true",
                   help="Calcule sub_chunks sans persister")
    args = p.parse_args()

    if args.auto:
        driver = _get_neo4j_driver()
        orphans = find_orphans(driver, args.tenant_id)
        driver.close()
        if not orphans:
            log.info("No orphans found (all DocumentContext have qdrant_status=OK)")
            return
        log.info(f"Found {len(orphans)} orphans:")
        for o in orphans:
            log.info(f"  - {o['doc_id']} (status={o['status']}, chunks={o['chunks']})")

        results = []
        for o in orphans:
            results.append(replay_one(o["doc_id"], args.tenant_id, dry_run=args.dry_run))

        log.info("=" * 60)
        log.info("SUMMARY:")
        for r in results:
            log.info(f"  {r['doc_id']}: {r.get('status')} chunks={r.get('chunks', 0)}")
        return

    if not args.doc_id:
        p.error("--doc-id required (or use --auto)")

    result = replay_one(args.doc_id, args.tenant_id, dry_run=args.dry_run)
    log.info(f"Result: {result}")


if __name__ == "__main__":
    main()
