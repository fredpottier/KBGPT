"""
🌊 OSMOSE Semantic Intelligence V2.1 - Infrastructure Setup

Script d'initialisation de l'infrastructure Proto-KG V2.1:
- Neo4j: Constraints + Indexes (Concepts, pas narratives)
- Qdrant: Collection concepts_proto (multilingual-e5-large 1024D)

Exécution:
    python -m knowbase.semantic.setup_infrastructure

Phase 1 V2.1 - Semaine 1
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
    Configure le schéma Neo4j Proto-KG V2.1.

    Architecture V2.1 (Concept-First):
    - Document → Topic → Concept → CanonicalConcept
    - CandidateEntity / CandidateRelation (staging)

    Crée:
    - Constraints unicité sur IDs
    - Indexes sur concept_name, canonical_name, concept_type, language
    """
    config = get_semantic_config()
    neo4j_config = config.neo4j_proto

    logger.info("[OSMOSE] Setup Neo4j Proto-KG Schema V2.1...")

    # Connexion Neo4j depuis variables d'environnement
    neo4j_uri = neo4j_config.uri
    neo4j_user = neo4j_config.user
    neo4j_password = neo4j_config.password

    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        async with driver.session(database=neo4j_config.database) as session:
            # ===================================
            # CONSTRAINTS UNICITÉ
            # ===================================

            # Document.document_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT document_id_unique IF NOT EXISTS
                FOR (d:Document) REQUIRE d.document_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint Document.document_id créée")

            # Topic.topic_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT topic_id_unique IF NOT EXISTS
                FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint Topic.topic_id créée")

            # Concept.concept_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT concept_id_unique IF NOT EXISTS
                FOR (c:Concept) REQUIRE c.concept_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint Concept.concept_id créée")

            # CanonicalConcept.canonical_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT canonical_concept_id_unique IF NOT EXISTS
                FOR (cc:CanonicalConcept) REQUIRE cc.canonical_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint CanonicalConcept.canonical_id créée")

            # CandidateEntity.candidate_id UNIQUE (staging)
            await session.run("""
                CREATE CONSTRAINT candidate_entity_id IF NOT EXISTS
                FOR (e:CandidateEntity) REQUIRE e.candidate_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint CandidateEntity.candidate_id créée")

            # CandidateRelation.candidate_id UNIQUE (staging)
            await session.run("""
                CREATE CONSTRAINT candidate_relation_id IF NOT EXISTS
                FOR (r:CandidateRelation) REQUIRE r.candidate_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint CandidateRelation.candidate_id créée")

            # ===================================
            # INDEXES RECHERCHE
            # ===================================

            # Concept.name (recherche par nom)
            await session.run("""
                CREATE INDEX concept_name_idx IF NOT EXISTS
                FOR (c:Concept) ON (c.name)
            """)
            logger.info("  ✅ Index Concept.name créé")

            # Concept.type (filtrage par type)
            await session.run("""
                CREATE INDEX concept_type_idx IF NOT EXISTS
                FOR (c:Concept) ON (c.type)
            """)
            logger.info("  ✅ Index Concept.type créé")

            # Concept.language (filtrage par langue)
            await session.run("""
                CREATE INDEX concept_language_idx IF NOT EXISTS
                FOR (c:Concept) ON (c.language)
            """)
            logger.info("  ✅ Index Concept.language créé")

            # CanonicalConcept.canonical_name (recherche canonique)
            await session.run("""
                CREATE INDEX canonical_name_idx IF NOT EXISTS
                FOR (cc:CanonicalConcept) ON (cc.canonical_name)
            """)
            logger.info("  ✅ Index CanonicalConcept.canonical_name créé")

            # CanonicalConcept.type (filtrage par type)
            await session.run("""
                CREATE INDEX canonical_type_idx IF NOT EXISTS
                FOR (cc:CanonicalConcept) ON (cc.type)
            """)
            logger.info("  ✅ Index CanonicalConcept.type créé")

            # CandidateEntity.tenant_id (multi-tenancy)
            await session.run("""
                CREATE INDEX candidate_entity_tenant IF NOT EXISTS
                FOR (e:CandidateEntity) ON (e.tenant_id)
            """)
            logger.info("  ✅ Index CandidateEntity.tenant_id créé")

            # CandidateEntity.status (gatekeeper workflow)
            await session.run("""
                CREATE INDEX candidate_entity_status IF NOT EXISTS
                FOR (e:CandidateEntity) ON (e.status)
            """)
            logger.info("  ✅ Index CandidateEntity.status créé")

            # CandidateRelation.tenant_id (multi-tenancy)
            await session.run("""
                CREATE INDEX candidate_relation_tenant IF NOT EXISTS
                FOR (r:CandidateRelation) ON (r.tenant_id)
            """)
            logger.info("  ✅ Index CandidateRelation.tenant_id créé")

            # CandidateRelation.status (gatekeeper workflow)
            await session.run("""
                CREATE INDEX candidate_relation_status IF NOT EXISTS
                FOR (r:CandidateRelation) ON (r.status)
            """)
            logger.info("  ✅ Index CandidateRelation.status créé")

            # ===================================
            # PHASE 2.8 - RawAssertion Schema
            # ===================================

            # RawAssertion.raw_assertion_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT raw_assertion_id_unique IF NOT EXISTS
                FOR (ra:RawAssertion) REQUIRE ra.raw_assertion_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint RawAssertion.raw_assertion_id créée")

            # RawAssertion.raw_fingerprint UNIQUE (dedup)
            await session.run("""
                CREATE CONSTRAINT raw_assertion_fingerprint_unique IF NOT EXISTS
                FOR (ra:RawAssertion) REQUIRE ra.raw_fingerprint IS UNIQUE
            """)
            logger.info("  ✅ Constraint RawAssertion.raw_fingerprint créée")

            # RawAssertion.tenant_id (multi-tenancy)
            await session.run("""
                CREATE INDEX raw_assertion_tenant_idx IF NOT EXISTS
                FOR (ra:RawAssertion) ON (ra.tenant_id)
            """)
            logger.info("  ✅ Index RawAssertion.tenant_id créé")

            # RawAssertion.source_doc_id (filtrage par doc)
            await session.run("""
                CREATE INDEX raw_assertion_doc_idx IF NOT EXISTS
                FOR (ra:RawAssertion) ON (ra.source_doc_id)
            """)
            logger.info("  ✅ Index RawAssertion.source_doc_id créé")

            # RawAssertion.relation_type (filtrage par type Phase 2.10)
            await session.run("""
                CREATE INDEX raw_assertion_type_idx IF NOT EXISTS
                FOR (ra:RawAssertion) ON (ra.relation_type)
            """)
            logger.info("  ✅ Index RawAssertion.relation_type créé")

            # ===================================
            # PHASE 2.8 - CanonicalRelation Schema
            # ===================================

            # CanonicalRelation.canonical_relation_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT canonical_relation_id_unique IF NOT EXISTS
                FOR (cr:CanonicalRelation) REQUIRE cr.canonical_relation_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint CanonicalRelation.canonical_relation_id créée")

            # CanonicalRelation.tenant_id (multi-tenancy)
            await session.run("""
                CREATE INDEX canonical_relation_tenant_idx IF NOT EXISTS
                FOR (cr:CanonicalRelation) ON (cr.tenant_id)
            """)
            logger.info("  ✅ Index CanonicalRelation.tenant_id créé")

            # CanonicalRelation.relation_type (filtrage)
            await session.run("""
                CREATE INDEX canonical_relation_type_idx IF NOT EXISTS
                FOR (cr:CanonicalRelation) ON (cr.relation_type)
            """)
            logger.info("  ✅ Index CanonicalRelation.relation_type créé")

            # CanonicalRelation.maturity (filtrage VALIDATED/CANDIDATE)
            await session.run("""
                CREATE INDEX canonical_relation_maturity_idx IF NOT EXISTS
                FOR (cr:CanonicalRelation) ON (cr.maturity)
            """)
            logger.info("  ✅ Index CanonicalRelation.maturity créé")

            # ===================================
            # PHASE 2.11 - RawClaim Schema
            # ===================================

            # RawClaim.raw_claim_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT raw_claim_id_unique IF NOT EXISTS
                FOR (rc:RawClaim) REQUIRE rc.raw_claim_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint RawClaim.raw_claim_id créée")

            # RawClaim.raw_fingerprint UNIQUE (dedup)
            await session.run("""
                CREATE CONSTRAINT raw_claim_fingerprint_unique IF NOT EXISTS
                FOR (rc:RawClaim) REQUIRE rc.raw_fingerprint IS UNIQUE
            """)
            logger.info("  ✅ Constraint RawClaim.raw_fingerprint créée")

            # RawClaim.tenant_id (multi-tenancy)
            await session.run("""
                CREATE INDEX raw_claim_tenant_idx IF NOT EXISTS
                FOR (rc:RawClaim) ON (rc.tenant_id)
            """)
            logger.info("  ✅ Index RawClaim.tenant_id créé")

            # RawClaim.subject_concept_id (jointure concepts)
            await session.run("""
                CREATE INDEX raw_claim_subject_idx IF NOT EXISTS
                FOR (rc:RawClaim) ON (rc.subject_concept_id)
            """)
            logger.info("  ✅ Index RawClaim.subject_concept_id créé")

            # RawClaim.claim_type (filtrage par type de claim)
            await session.run("""
                CREATE INDEX raw_claim_type_idx IF NOT EXISTS
                FOR (rc:RawClaim) ON (rc.claim_type)
            """)
            logger.info("  ✅ Index RawClaim.claim_type créé")

            # RawClaim.source_doc_id (filtrage par doc)
            await session.run("""
                CREATE INDEX raw_claim_doc_idx IF NOT EXISTS
                FOR (rc:RawClaim) ON (rc.source_doc_id)
            """)
            logger.info("  ✅ Index RawClaim.source_doc_id créé")

            # ===================================
            # PHASE 2.11 - CanonicalClaim Schema
            # ===================================

            # CanonicalClaim.canonical_claim_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT canonical_claim_id_unique IF NOT EXISTS
                FOR (cc:CanonicalClaim) REQUIRE cc.canonical_claim_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint CanonicalClaim.canonical_claim_id créée")

            # CanonicalClaim.tenant_id (multi-tenancy)
            await session.run("""
                CREATE INDEX canonical_claim_tenant_idx IF NOT EXISTS
                FOR (cc:CanonicalClaim) ON (cc.tenant_id)
            """)
            logger.info("  ✅ Index CanonicalClaim.tenant_id créé")

            # CanonicalClaim.subject_concept_id (jointure concepts)
            await session.run("""
                CREATE INDEX canonical_claim_subject_idx IF NOT EXISTS
                FOR (cc:CanonicalClaim) ON (cc.subject_concept_id)
            """)
            logger.info("  ✅ Index CanonicalClaim.subject_concept_id créé")

            # CanonicalClaim.claim_type (filtrage par type)
            await session.run("""
                CREATE INDEX canonical_claim_type_idx IF NOT EXISTS
                FOR (cc:CanonicalClaim) ON (cc.claim_type)
            """)
            logger.info("  ✅ Index CanonicalClaim.claim_type créé")

            # CanonicalClaim.maturity (filtrage VALIDATED/CANDIDATE/CONFLICTING)
            await session.run("""
                CREATE INDEX canonical_claim_maturity_idx IF NOT EXISTS
                FOR (cc:CanonicalClaim) ON (cc.maturity)
            """)
            logger.info("  ✅ Index CanonicalClaim.maturity créé")

        logger.info("[OSMOSE] ✅ Neo4j Proto-KG Schema V2.1 configuré avec succès")
        logger.info("  📊 Labels: Document, Topic, Concept, CanonicalConcept, CandidateEntity, CandidateRelation")
        logger.info("  📊 Labels Phase 2: RawAssertion, CanonicalRelation, RawClaim, CanonicalClaim")
        logger.info("  🔍 Total: 14 constraints + 26 indexes")

    except Exception as e:
        logger.error(f"[OSMOSE] ❌ Erreur setup Neo4j: {e}")
        raise
    finally:
        await driver.close()


async def setup_qdrant_proto_collection():
    """
    Configure la collection Qdrant Proto V2.1.

    Crée la collection concepts_proto avec:
    - Vecteurs 1024 dimensions (multilingual-e5-large)
    - Distance Cosine (cross-lingual similarity)
    - Configuration HNSW optimisée
    - on_disk_payload pour économie RAM
    """
    config = get_semantic_config()
    qdrant_config = config.qdrant_proto

    logger.info("[OSMOSE] Setup Qdrant Proto Collection V2.1...")

    qdrant_client = get_qdrant_client()

    try:
        collection_name = qdrant_config.collection_name

        # Vérifier si la collection existe déjà
        collections = qdrant_client.get_collections()
        exists = any(c.name == collection_name for c in collections.collections)

        if exists:
            logger.info(f"  ⚠️  Collection '{collection_name}' existe déjà, skip création")
            return

        # Créer la collection concepts_proto
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=qdrant_config.vector_size,  # 1024 (multilingual-e5-large)
                distance=Distance.COSINE,
                on_disk=False  # Vecteurs en RAM pour performance
            ),
            hnsw_config=HnswConfigDiff(
                m=qdrant_config.hnsw_config["m"],               # 16
                ef_construct=qdrant_config.hnsw_config["ef_construct"],  # 100
                full_scan_threshold=10000
            ),
            optimizers_config=OptimizersConfigDiff(
                deleted_threshold=0.2,
                vacuum_min_vector_number=1000,
                default_segment_number=2,
                indexing_threshold=qdrant_config.optimization["indexing_threshold"]  # 10000
            ),
            on_disk_payload=qdrant_config.on_disk_payload  # Payload sur disque (économie RAM)
        )

        logger.info(f"  ✅ Collection '{collection_name}' créée")
        logger.info(f"     - Model: multilingual-e5-large")
        logger.info(f"     - Vector size: {qdrant_config.vector_size}D")
        logger.info(f"     - Distance: {qdrant_config.distance}")
        logger.info(f"     - HNSW m={qdrant_config.hnsw_config['m']}, ef_construct={qdrant_config.hnsw_config['ef_construct']}")
        logger.info(f"     - on_disk_payload: {qdrant_config.on_disk_payload}")
        logger.info("[OSMOSE] ✅ Qdrant Proto Collection V2.1 configurée avec succès")

    except Exception as e:
        logger.error(f"[OSMOSE] ❌ Erreur setup Qdrant: {e}")
        raise


async def setup_all():
    """Configure toute l'infrastructure Proto-KG V2.1"""
    logger.info("=" * 70)
    logger.info("🌊 OSMOSE Phase 1 V2.1 - Infrastructure Setup")
    logger.info("   Concept-First, Language-Agnostic Architecture")
    logger.info("=" * 70)

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
