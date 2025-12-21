#!/usr/bin/env python3
"""
🌊 OSMOSE Phase 2.7 - Index Concepts dans Qdrant

Script pour indexer tous les CanonicalConcepts de Neo4j dans Qdrant
pour le matching sémantique multilingue (Palier 2).

Usage:
    docker exec knowbase-app python scripts/index_concepts_qdrant.py
    docker exec knowbase-app python scripts/index_concepts_qdrant.py --recreate
"""

import argparse
import logging
import sys
import time
from typing import List, Dict, Any
import uuid

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def get_neo4j_client():
    """Récupère le client Neo4j."""
    from knowbase.neo4j_custom.client import get_neo4j_client
    return get_neo4j_client()


def get_qdrant_client():
    """Récupère le client Qdrant."""
    from qdrant_client import QdrantClient
    from knowbase.config.settings import get_settings

    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url)


def get_embedder():
    """Récupère l'embedder multilingue."""
    from knowbase.semantic.config import get_semantic_config
    from knowbase.semantic.utils.embeddings import get_embedder

    config = get_semantic_config()
    return get_embedder(config)


def fetch_concepts_from_neo4j(tenant_id: str = "default") -> List[Dict[str, Any]]:
    """Récupère tous les concepts de Neo4j."""
    logger.info(f"[OSMOSE] Fetching concepts from Neo4j (tenant: {tenant_id})...")

    neo4j = get_neo4j_client()

    cypher = """
    MATCH (c:CanonicalConcept)
    WHERE c.tenant_id = $tenant_id
    RETURN
        c.concept_id AS id,
        c.canonical_name AS name,
        c.concept_type AS type,
        coalesce(c.summary, '') AS summary,
        coalesce(c.unified_definition, '') AS definition,
        coalesce(c.quality_score, 0.5) AS quality,
        coalesce(size(c.chunk_ids), 0) AS popularity
    """

    results = neo4j.execute_query(cypher, {"tenant_id": tenant_id})

    concepts = []
    for record in results:
        concepts.append({
            "id": record.get("id"),
            "name": record.get("name", ""),
            "type": record.get("type", "UNKNOWN"),
            "summary": record.get("summary", ""),
            "definition": record.get("definition", ""),
            "quality": record.get("quality", 0.5),
            "popularity": record.get("popularity", 0),
            "tenant_id": tenant_id
        })

    logger.info(f"[OSMOSE] Found {len(concepts)} concepts in Neo4j")
    return concepts


def create_embed_text(concept: Dict[str, Any]) -> str:
    """Crée le texte à embedder pour un concept."""
    # Format: "Name. Type: TYPE. Summary"
    parts = [concept["name"]]

    if concept["type"]:
        parts.append(f"Type: {concept['type']}")

    if concept["summary"]:
        # Limiter le summary à ~400 chars
        summary = concept["summary"][:400]
        parts.append(summary)

    return ". ".join(parts)


def create_collection(qdrant, collection_name: str, vector_size: int = 1024, recreate: bool = False):
    """Crée la collection Qdrant si elle n'existe pas."""
    from qdrant_client.models import Distance, VectorParams

    collections = qdrant.get_collections().collections
    exists = any(c.name == collection_name for c in collections)

    if exists and recreate:
        logger.info(f"[OSMOSE] Deleting existing collection: {collection_name}")
        qdrant.delete_collection(collection_name)
        exists = False

    if not exists:
        logger.info(f"[OSMOSE] Creating collection: {collection_name} ({vector_size}D)")
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE
            )
        )
    else:
        logger.info(f"[OSMOSE] Collection {collection_name} already exists")


def index_concepts(
    concepts: List[Dict[str, Any]],
    embedder,
    qdrant,
    collection_name: str,
    batch_size: int = 100
):
    """Indexe les concepts dans Qdrant."""
    from qdrant_client.models import PointStruct

    logger.info(f"[OSMOSE] Indexing {len(concepts)} concepts (batch_size={batch_size})...")

    total_indexed = 0
    start_time = time.time()

    for i in range(0, len(concepts), batch_size):
        batch = concepts[i:i + batch_size]

        # Créer les textes à embedder
        texts = [create_embed_text(c) for c in batch]

        # Générer les embeddings (avec préfixe "passage" pour e5)
        embeddings = embedder.encode(texts, prefix_type="passage")

        # Créer les points Qdrant
        points = []
        for j, concept in enumerate(batch):
            # Générer un UUID déterministe basé sur concept_id
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, concept["id"] or concept["name"]))

            points.append(PointStruct(
                id=point_id,
                vector=embeddings[j].tolist(),
                payload={
                    "concept_id": concept["id"],
                    "canonical_name": concept["name"],
                    "concept_type": concept["type"],
                    "quality_score": concept["quality"],
                    "popularity": concept["popularity"],
                    "tenant_id": concept["tenant_id"]
                }
            ))

        # Upsert dans Qdrant
        qdrant.upsert(collection_name=collection_name, points=points)

        total_indexed += len(batch)
        elapsed = time.time() - start_time
        rate = total_indexed / elapsed if elapsed > 0 else 0

        logger.info(f"[OSMOSE] Indexed {total_indexed}/{len(concepts)} concepts ({rate:.1f}/s)")

    elapsed = time.time() - start_time
    logger.info(f"[OSMOSE] ✅ Indexing complete: {total_indexed} concepts in {elapsed:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Index concepts into Qdrant")
    parser.add_argument("--tenant", default="default", help="Tenant ID")
    parser.add_argument("--collection", default="knowwhere_concepts", help="Qdrant collection name")
    parser.add_argument("--recreate", action="store_true", help="Recreate collection from scratch")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for indexing")

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("🌊 OSMOSE Phase 2.7 - Concept Indexing (Palier 2)")
    logger.info("=" * 60)

    try:
        # 1. Récupérer les concepts de Neo4j
        concepts = fetch_concepts_from_neo4j(args.tenant)

        if not concepts:
            logger.warning("[OSMOSE] No concepts found, exiting")
            return

        # 2. Initialiser l'embedder
        logger.info("[OSMOSE] Initializing embedder...")
        embedder = get_embedder()

        # 3. Initialiser Qdrant et créer collection
        logger.info("[OSMOSE] Connecting to Qdrant...")
        qdrant = get_qdrant_client()
        create_collection(qdrant, args.collection, vector_size=1024, recreate=args.recreate)

        # 4. Indexer les concepts
        index_concepts(
            concepts=concepts,
            embedder=embedder,
            qdrant=qdrant,
            collection_name=args.collection,
            batch_size=args.batch_size
        )

        # 5. Vérifier
        info = qdrant.get_collection(args.collection)
        logger.info(f"[OSMOSE] Collection {args.collection}: {info.points_count} points")

        logger.info("=" * 60)
        logger.info("✅ INDEXING COMPLETE")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"[OSMOSE] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
