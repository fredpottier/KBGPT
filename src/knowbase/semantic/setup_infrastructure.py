"""
🌊 OSMOSE Semantic Intelligence V2.2 - Infrastructure Setup

Script d'initialisation de l'infrastructure Proto-KG V2.2:
- Neo4j: Constraints + Indexes (18 constraints, 46 indexes)
- Qdrant: Collection concepts_proto (multilingual-e5-large 1024D)

Labels Neo4j:
- Core: Document, Topic, Concept, CanonicalConcept, CandidateEntity, CandidateRelation
- Phase 2: RawAssertion, CanonicalRelation, RawClaim, CanonicalClaim
- Scope Layer: DocumentContext, SectionContext, DocItem
- Normative (Pass 2c): NormativeRule, SpecFact
- Semantic (ADR Discursive): SemanticRelation, EvidenceBundle

Exécution:
    python -m knowbase.semantic.setup_infrastructure

V2.2 - 2026-01-22: Ajout NormativeRule, SpecFact, SemanticRelation, EvidenceBundle
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

            # ============================================
            # SCOPE LAYER INDEXES (ADR_SCOPE_VS_ASSERTION_SEPARATION)
            # ============================================
            logger.info("  📊 Création indexes Scope Layer...")

            # DocumentContext.topic (filtrage par sujet principal)
            await session.run("""
                CREATE INDEX document_context_topic_idx IF NOT EXISTS
                FOR (dc:DocumentContext) ON (dc.topic)
            """)
            logger.info("  ✅ Index DocumentContext.topic créé")

            # SectionContext.scope_description (filtrage par portée section)
            await session.run("""
                CREATE INDEX section_context_scope_idx IF NOT EXISTS
                FOR (sc:SectionContext) ON (sc.scope_description)
            """)
            logger.info("  ✅ Index SectionContext.scope_description créé")

            # DocItem.mentioned_concepts (recherche par concepts mentionnés)
            # Note: Neo4j supporte les indexes sur listes pour recherche IN
            await session.run("""
                CREATE INDEX docitem_mentioned_concepts_idx IF NOT EXISTS
                FOR (di:DocItem) ON (di.mentioned_concepts)
            """)
            logger.info("  ✅ Index DocItem.mentioned_concepts créé")

            # ============================================
            # NORMATIVE RULE & SPEC FACT (ADR_NORMATIVE_RULES_SPEC_FACTS)
            # Pass 2c - Assertions non-traversables mais indexables
            # ============================================
            logger.info("  📊 Création schema NormativeRule & SpecFact...")

            # NormativeRule.rule_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT normative_rule_id_unique IF NOT EXISTS
                FOR (n:NormativeRule) REQUIRE n.rule_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint NormativeRule.rule_id créée")

            # SpecFact.fact_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT spec_fact_id_unique IF NOT EXISTS
                FOR (f:SpecFact) REQUIRE f.fact_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint SpecFact.fact_id créée")

            # NormativeRule.dedup_key + tenant_id (déduplication)
            await session.run("""
                CREATE INDEX normative_rule_dedup_idx IF NOT EXISTS
                FOR (n:NormativeRule) ON (n.dedup_key, n.tenant_id)
            """)
            logger.info("  ✅ Index NormativeRule.dedup_key créé")

            # SpecFact.dedup_key + tenant_id (déduplication)
            await session.run("""
                CREATE INDEX spec_fact_dedup_idx IF NOT EXISTS
                FOR (f:SpecFact) ON (f.dedup_key, f.tenant_id)
            """)
            logger.info("  ✅ Index SpecFact.dedup_key créé")

            # NormativeRule.source_doc_id + tenant_id (filtrage par document)
            await session.run("""
                CREATE INDEX normative_rule_doc_idx IF NOT EXISTS
                FOR (n:NormativeRule) ON (n.source_doc_id, n.tenant_id)
            """)
            logger.info("  ✅ Index NormativeRule.source_doc_id créé")

            # SpecFact.source_doc_id + tenant_id (filtrage par document)
            await session.run("""
                CREATE INDEX spec_fact_doc_idx IF NOT EXISTS
                FOR (f:SpecFact) ON (f.source_doc_id, f.tenant_id)
            """)
            logger.info("  ✅ Index SpecFact.source_doc_id créé")

            # NormativeRule.modality + tenant_id (filtrage par modalité MUST/SHOULD/MAY)
            await session.run("""
                CREATE INDEX normative_rule_modality_idx IF NOT EXISTS
                FOR (n:NormativeRule) ON (n.modality, n.tenant_id)
            """)
            logger.info("  ✅ Index NormativeRule.modality créé")

            # SpecFact.attribute_name + tenant_id (recherche par attribut)
            await session.run("""
                CREATE INDEX spec_fact_attribute_idx IF NOT EXISTS
                FOR (f:SpecFact) ON (f.attribute_name, f.tenant_id)
            """)
            logger.info("  ✅ Index SpecFact.attribute_name créé")

            # ============================================
            # SEMANTIC RELATION & EVIDENCE BUNDLE (ADR_DISCURSIVE_RELATIONS)
            # Relations prouvées avec bundles d'évidence
            # ============================================
            logger.info("  📊 Création schema SemanticRelation & EvidenceBundle...")

            # EvidenceBundle.bundle_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT evidence_bundle_id_unique IF NOT EXISTS
                FOR (eb:EvidenceBundle) REQUIRE eb.bundle_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint EvidenceBundle.bundle_id créée")

            # SemanticRelation.semantic_relation_id UNIQUE
            await session.run("""
                CREATE CONSTRAINT semantic_relation_id_unique IF NOT EXISTS
                FOR (sr:SemanticRelation) REQUIRE sr.semantic_relation_id IS UNIQUE
            """)
            logger.info("  ✅ Constraint SemanticRelation.semantic_relation_id créée")

            # EvidenceBundle.tenant_id + status (workflow filtrage)
            await session.run("""
                CREATE INDEX evidence_bundle_tenant_status_idx IF NOT EXISTS
                FOR (eb:EvidenceBundle) ON (eb.tenant_id, eb.status)
            """)
            logger.info("  ✅ Index EvidenceBundle.tenant_id+status créé")

            # EvidenceBundle.tenant_id + source_doc_id (filtrage par document)
            await session.run("""
                CREATE INDEX evidence_bundle_tenant_doc_idx IF NOT EXISTS
                FOR (eb:EvidenceBundle) ON (eb.tenant_id, eb.source_doc_id)
            """)
            logger.info("  ✅ Index EvidenceBundle.source_doc_id créé")

            # EvidenceBundle.confidence (tri par qualité)
            await session.run("""
                CREATE INDEX evidence_bundle_confidence_idx IF NOT EXISTS
                FOR (eb:EvidenceBundle) ON (eb.confidence)
            """)
            logger.info("  ✅ Index EvidenceBundle.confidence créé")

            # SemanticRelation.tenant_id + relation_type (filtrage par type)
            await session.run("""
                CREATE INDEX semantic_relation_tenant_type_idx IF NOT EXISTS
                FOR (sr:SemanticRelation) ON (sr.tenant_id, sr.relation_type)
            """)
            logger.info("  ✅ Index SemanticRelation.relation_type créé")

            # SemanticRelation.source_bundle_id (jointure avec EvidenceBundle)
            await session.run("""
                CREATE INDEX semantic_relation_bundle_idx IF NOT EXISTS
                FOR (sr:SemanticRelation) ON (sr.source_bundle_id)
            """)
            logger.info("  ✅ Index SemanticRelation.source_bundle_id créé")

            # SemanticRelation.defensibility_tier (filtrage STRICT/EXTENDED/HEURISTIC)
            await session.run("""
                CREATE INDEX semantic_relation_tier_idx IF NOT EXISTS
                FOR (sr:SemanticRelation) ON (sr.defensibility_tier, sr.tenant_id)
            """)
            logger.info("  ✅ Index SemanticRelation.defensibility_tier créé")

            # SemanticRelation.semantic_grade (filtrage par qualité A/B/C/D)
            await session.run("""
                CREATE INDEX semantic_relation_grade_idx IF NOT EXISTS
                FOR (sr:SemanticRelation) ON (sr.semantic_grade, sr.tenant_id)
            """)
            logger.info("  ✅ Index SemanticRelation.semantic_grade créé")

        logger.info("[OSMOSE] ✅ Neo4j Proto-KG Schema V2.2 configuré avec succès")
        logger.info("  📊 Labels Core: Document, Topic, Concept, CanonicalConcept, CandidateEntity, CandidateRelation")
        logger.info("  📊 Labels Phase 2: RawAssertion, CanonicalRelation, RawClaim, CanonicalClaim")
        logger.info("  📊 Labels Scope Layer: DocumentContext, SectionContext, DocItem")
        logger.info("  📊 Labels Normative: NormativeRule, SpecFact")
        logger.info("  📊 Labels Semantic: SemanticRelation, EvidenceBundle")
        logger.info("  🔍 Total: 18 constraints + 46 indexes")

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
