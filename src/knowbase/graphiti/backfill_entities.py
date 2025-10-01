"""
Backfill Entities - Phase 1 Critère 1.3

Script pour enrichir rétroactivement les chunks Qdrant existants
avec les entities extraites par Graphiti.

Usage:
    python -m knowbase.graphiti.backfill_entities --tenant test_sync --limit 100
"""

import asyncio
import logging
from typing import List, Optional
from qdrant_client.models import Filter, FieldCondition, MatchValue

from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.graphiti.graphiti_client import get_graphiti_client
from knowbase.graphiti.qdrant_sync import get_sync_service

logger = logging.getLogger(__name__)


async def backfill_entities_for_tenant(
    tenant_id: str,
    collection_name: str = "knowbase",
    limit: Optional[int] = None,
    dry_run: bool = False
) -> dict:
    """
    Backfill entities pour tous les chunks d'un tenant

    Args:
        tenant_id: ID tenant à traiter
        collection_name: Collection Qdrant
        limit: Nombre max de chunks à traiter (None = tous)
        dry_run: Si True, simulation sans modification

    Returns:
        Statistiques du backfill
    """
    qdrant_client = get_qdrant_client()
    graphiti_client = get_graphiti_client()
    sync_service = get_sync_service(qdrant_client, graphiti_client)

    stats = {
        "chunks_found": 0,
        "chunks_enriched": 0,
        "episodes_processed": 0,
        "errors": 0
    }

    logger.info(f"🚀 Début backfill entities pour tenant: {tenant_id}")
    if dry_run:
        logger.info("⚠️ MODE DRY-RUN: Aucune modification ne sera appliquée")

    # 1. Récupérer tous les chunks et filtrer ceux avec episode_id
    try:
        # Note: Qdrant ne supporte pas wildcard, donc on récupère tous les chunks
        # et on filtre manuellement ceux qui ont episode_id
        results, _ = qdrant_client.scroll(
            collection_name=collection_name,
            limit=limit or 10000,
            with_payload=True,
            scroll_filter=None  # Pas de filtre, on récupère tout
        )

        # Filtrer chunks avec episode_id
        chunks_with_episode = [
            point for point in results
            if point.payload and point.payload.get("episode_id")
        ]

        stats["chunks_found"] = len(chunks_with_episode)
        logger.info(f"📊 Trouvé {stats['chunks_found']} chunks avec episode_id")

        # 2. Grouper chunks par episode_id
        episodes_map = {}
        for point in chunks_with_episode:
            episode_id = point.payload["episode_id"]
            if episode_id not in episodes_map:
                episodes_map[episode_id] = []
            episodes_map[episode_id].append(str(point.id))

        stats["episodes_processed"] = len(episodes_map)
        logger.info(f"📦 {stats['episodes_processed']} episodes distincts à traiter")

        # 3. Enrichir chunks pour chaque episode
        for episode_id, chunk_ids in episodes_map.items():
            try:
                logger.info(
                    f"  🔄 Episode {episode_id[:8]}... ({len(chunk_ids)} chunks)"
                )

                if not dry_run:
                    # Enrichir chunks avec entities depuis Graphiti
                    enriched = await sync_service.enrich_chunks_with_entities(
                        chunk_ids=chunk_ids,
                        episode_id=episode_id
                    )
                    stats["chunks_enriched"] += enriched
                else:
                    logger.info(f"     [DRY-RUN] Aurait enrichi {len(chunk_ids)} chunks")

            except Exception as e:
                logger.error(f"  ❌ Erreur episode {episode_id}: {e}")
                stats["errors"] += 1

        logger.info("✅ Backfill terminé!")
        logger.info(f"📊 Statistiques:")
        logger.info(f"   - Chunks trouvés: {stats['chunks_found']}")
        logger.info(f"   - Chunks enrichis: {stats['chunks_enriched']}")
        logger.info(f"   - Episodes traités: {stats['episodes_processed']}")
        logger.info(f"   - Erreurs: {stats['errors']}")

        return stats

    except Exception as e:
        logger.error(f"❌ Erreur backfill: {e}", exc_info=True)
        raise


async def main():
    """Point d'entrée CLI"""
    import argparse

    parser = argparse.ArgumentParser(description="Backfill entities Qdrant depuis Graphiti")
    parser.add_argument("--tenant", required=True, help="ID tenant à traiter")
    parser.add_argument("--limit", type=int, help="Limite nombre chunks")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans modification")
    parser.add_argument("--collection", default="knowbase", help="Collection Qdrant")

    args = parser.parse_args()

    # Configuration logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Exécuter backfill
    stats = await backfill_entities_for_tenant(
        tenant_id=args.tenant,
        collection_name=args.collection,
        limit=args.limit,
        dry_run=args.dry_run
    )

    return stats


if __name__ == "__main__":
    asyncio.run(main())
