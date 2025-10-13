"""
🌊 OSMOSE Semantic Intelligence - Infrastructure Setup

Script d'initialisation de l'infrastructure Proto-KG:
- Neo4j: Constraints + Indexes
- Qdrant: Collection knowwhere_proto

Exécution:
    python -m knowbase.semantic.setup_infrastructure
"""

import asyncio
import logging
import os
from neo4j import AsyncGraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    OptimizersConfigDiff,
    HnswConfigDiff
)
from .config import get_semantic_config
from knowbase.common.clients.qdrant_client import get_qdrant_client

logger = logging.getLogger(__name__)


async def setup_neo4j_proto_kg():
    """
    Configure le schéma Neo4j Proto-KG.

    Crée:
    - Constraints d'unicité sur candidate_id
    - Indexes sur tenant_id et status
    """
    config = get_semantic_config()
    neo4j_config = config.neo4j_proto

    logger.info("[OSMOSE] Setup Neo4j Proto-KG Schema...")

    # Connexion Neo4j depuis variables d'environnement
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        async with driver.session() as session:
            # Constraint: CandidateEntity.candidate_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT candidate_entity_id IF NOT EXISTS
                FOR (n:CandidateEntity) REQUIRE n.candidate_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint CandidateEntity.candidate_id créée")

            # Constraint: CandidateRelation.candidate_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT candidate_relation_id IF NOT EXISTS
                FOR (r:CandidateRelation) REQUIRE r.candidate_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint CandidateRelation.candidate_id créée")

            # Index: CandidateEntity.tenant_id
            await session.run("""
                CREATE INDEX candidate_entity_tenant IF NOT EXISTS
                FOR (n:CandidateEntity) ON (n.tenant_id)
            """)
            logger.info("  ✅ Index CandidateEntity.tenant_id créé")

            # Index: CandidateEntity.status
            await session.run("""
                CREATE INDEX candidate_entity_status IF NOT EXISTS
                FOR (n:CandidateEntity) ON (n.status)
            """)
            logger.info("  ✅ Index CandidateEntity.status créé")

            # Index: CandidateRelation.tenant_id
            await session.run("""
                CREATE INDEX candidate_relation_tenant IF NOT EXISTS
                FOR (r:CandidateRelation) ON (r.tenant_id)
            """)
            logger.info("  ✅ Index CandidateRelation.tenant_id créé")

            # Index: CandidateRelation.status
            await session.run("""
                CREATE INDEX candidate_relation_status IF NOT EXISTS
                FOR (r:CandidateRelation) ON (r.status)
            """)
            logger.info("  ✅ Index CandidateRelation.status créé")

        logger.info("[OSMOSE] ✅ Neo4j Proto-KG Schema configuré avec succès")

    except Exception as e:
        logger.error(f"[OSMOSE] ❌ Erreur setup Neo4j: {e}")
        raise
    finally:
        await driver.close()


async def setup_qdrant_proto_collection():
    """
    Configure la collection Qdrant Proto.

    Crée la collection knowwhere_proto avec:
    - Vecteurs 1536 dimensions (OpenAI text-embedding-3-small)
    - Distance Cosine
    - Configuration HNSW optimisée
    """
    config = get_semantic_config()
    qdrant_config = config.qdrant_proto

    logger.info("[OSMOSE] Setup Qdrant Proto Collection...")

    qdrant_client = get_qdrant_client()

    try:
        collection_name = qdrant_config.collection_name

        # Vérifier si la collection existe déjà
        collections = qdrant_client.get_collections()
        exists = any(c.name == collection_name for c in collections.collections)

        if exists:
            logger.info(f"  ⚠️  Collection '{collection_name}' existe déjà, skip création")
            return

        # Créer la collection
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=qdrant_config.vector_size,
                distance=Distance.COSINE
            ),
            hnsw_config=HnswConfigDiff(
                m=16,
                ef_construct=100,
                full_scan_threshold=10000
            ),
            optimizers_config=OptimizersConfigDiff(
                deleted_threshold=0.2,
                vacuum_min_vector_number=1000,
                default_segment_number=2
            )
        )

        logger.info(f"  ✅ Collection '{collection_name}' créée")
        logger.info(f"     - Vector size: {qdrant_config.vector_size}")
        logger.info(f"     - Distance: {qdrant_config.distance}")
        logger.info("[OSMOSE] ✅ Qdrant Proto Collection configurée avec succès")

    except Exception as e:
        logger.error(f"[OSMOSE] ❌ Erreur setup Qdrant: {e}")
        raise


async def setup_all():
    """Configure toute l'infrastructure Proto-KG"""
    logger.info("=" * 60)
    logger.info("🌊 OSMOSE Phase 1 - Infrastructure Setup")
    logger.info("=" * 60)

    try:
        # Setup Neo4j
        await setup_neo4j_proto_kg()
        print()

        # Setup Qdrant
        await setup_qdrant_proto_collection()
        print()

        logger.info("=" * 60)
        logger.info("🎉 Infrastructure Setup terminé avec succès !")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ Échec du setup: {e}")
        raise


if __name__ == "__main__":
    # Configuration logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Exécuter setup
    asyncio.run(setup_all())
