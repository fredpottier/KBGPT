# Tests Phase 2 OSMOSE - Neo4j Relationship Writer

import pytest
from datetime import datetime
from typing import List

from knowbase.relations.neo4j_writer import Neo4jRelationshipWriter
from knowbase.relations.types import (
    TypedRelation,
    RelationMetadata,
    RelationType,
    ExtractionMethod,
    RelationStrength,
    RelationStatus
)
from knowbase.common.clients.neo4j_client import Neo4jClient
import os


@pytest.fixture(scope="module")
def neo4j_client():
    """Fixture Neo4jClient pour tests."""
    client = Neo4jClient(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass"),
        database=os.getenv("NEO4J_DATABASE", "neo4j")
    )
    yield client
    client.close()


@pytest.fixture
def neo4j_writer(neo4j_client):
    """Fixture Neo4jRelationshipWriter."""
    writer = Neo4jRelationshipWriter(
        neo4j_client=neo4j_client,
        tenant_id="test-tenant"
    )
    return writer


@pytest.fixture
def sample_canonical_concepts(neo4j_client):
    """Créer concepts canoniques de test dans Neo4j."""
    # Créer 3 concepts pour tests
    concepts = [
        {
            "concept_id": "test-concept-hana",
            "canonical_name": "SAP HANA",
            "concept_type": "DATABASE",
            "tenant_id": "test-tenant"
        },
        {
            "concept_id": "test-concept-aes256",
            "canonical_name": "AES256",
            "concept_type": "ENCRYPTION_ALGORITHM",
            "tenant_id": "test-tenant"
        },
        {
            "concept_id": "test-concept-s4",
            "canonical_name": "SAP S/4HANA",
            "concept_type": "PRODUCT",
            "tenant_id": "test-tenant"
        }
    ]

    # Insérer dans Neo4j
    for concept in concepts:
        query = """
        MERGE (c:CanonicalConcept {concept_id: $concept_id, tenant_id: $tenant_id})
        SET c.canonical_name = $canonical_name,
            c.concept_type = $concept_type,
            c.created_at = datetime()
        """
        with neo4j_client.driver.session(database=neo4j_client.database) as session:
            session.run(
                query,
                concept_id=concept["concept_id"],
                tenant_id=concept["tenant_id"],
                canonical_name=concept["canonical_name"],
                concept_type=concept["concept_type"]
            )

    yield concepts

    # Cleanup: supprimer concepts de test
    cleanup_query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    DETACH DELETE c
    """
    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        session.run(cleanup_query, tenant_id="test-tenant")


@pytest.fixture
def sample_typed_relation():
    """Fixture relation typée de test."""
    metadata = RelationMetadata(
        confidence=0.92,
        extraction_method=ExtractionMethod.LLM,
        source_doc_id="test-doc-123",
        source_chunk_ids=["chunk-1", "chunk-2"],
        language="EN",
        created_at=datetime.utcnow(),
        strength=RelationStrength.STRONG,
        status=RelationStatus.ACTIVE,
        require_validation=False
    )

    relation = TypedRelation(
        relation_id="test-rel-1",
        source_concept="test-concept-hana",
        target_concept="test-concept-aes256",
        relation_type=RelationType.USES,
        metadata=metadata,
        evidence="HANA database is encrypted at rest using AES256",
        context='{"encryption_scope": "at_rest"}'
    )

    return relation


class TestNeo4jRelationshipWriter:
    """Tests Neo4j Relationship Writer."""

    def test_write_single_relation(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        sample_typed_relation
    ):
        """Test écriture relation simple."""
        stats = neo4j_writer.write_relations(
            relations=[sample_typed_relation],
            document_id="test-doc-123",
            document_name="Test Document"
        )

        # Vérifier stats
        assert stats["total_relations"] == 1
        assert stats["created"] == 1
        assert stats["updated"] == 0
        assert stats["skipped"] == 0
        assert stats["errors"] == 0
        assert RelationType.USES in stats["relations_by_type"]
        assert stats["relations_by_type"][RelationType.USES] == 1

    def test_relation_exists_in_neo4j(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        sample_typed_relation,
        neo4j_client
    ):
        """Test que relation est bien créée dans Neo4j."""
        # Écrire relation
        neo4j_writer.write_relations(
            relations=[sample_typed_relation],
            document_id="test-doc-123",
            document_name="Test Document"
        )

        # Vérifier existence dans Neo4j
        query = """
        MATCH (source:CanonicalConcept {concept_id: $source_id, tenant_id: $tenant_id})
        -[r:USES]->
        (target:CanonicalConcept {concept_id: $target_id, tenant_id: $tenant_id})
        RETURN properties(r) as rel_props
        """

        with neo4j_client.driver.session(database=neo4j_client.database) as session:
            result = session.run(
                query,
                source_id="test-concept-hana",
                target_id="test-concept-aes256",
                tenant_id="test-tenant"
            )
            records = [dict(rec) for rec in result]

        assert len(records) == 1
        rel_props = records[0]["rel_props"]

        # Vérifier metadata
        assert rel_props["confidence"] == 0.92
        assert rel_props["extraction_method"] == "llm"
        assert rel_props["source_doc_id"] == "test-doc-123"
        assert rel_props["language"] == "EN"
        assert rel_props["strength"] == "strong"  # Lowercase (enum value)
        assert rel_props["status"] == "active"  # Lowercase (enum value)
        assert rel_props["evidence"] == "HANA database is encrypted at rest using AES256"

    def test_update_relation_higher_confidence(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        sample_typed_relation
    ):
        """Test update relation si nouvelle confidence > ancienne."""
        # Écrire relation initiale (confidence=0.92)
        stats1 = neo4j_writer.write_relations(
            relations=[sample_typed_relation],
            document_id="test-doc-123",
            document_name="Test Document"
        )

        assert stats1["created"] == 1

        # Créer nouvelle relation même source/target/type, confidence plus haute
        new_metadata = RelationMetadata(
            confidence=0.95,  # Plus haute
            extraction_method=ExtractionMethod.LLM,
            source_doc_id="test-doc-456",
            source_chunk_ids=["chunk-3"],
            language="EN",
            created_at=datetime.utcnow(),
            strength=RelationStrength.STRONG,
            status=RelationStatus.ACTIVE,
            require_validation=False
        )

        new_relation = TypedRelation(
            relation_id="test-rel-2",
            source_concept="test-concept-hana",
            target_concept="test-concept-aes256",
            relation_type=RelationType.USES,
            metadata=new_metadata,
            evidence="Updated evidence"
        )

        # Écrire nouvelle relation
        stats2 = neo4j_writer.write_relations(
            relations=[new_relation],
            document_id="test-doc-456",
            document_name="Test Document 2"
        )

        # Devrait être updated (pas created)
        assert stats2["created"] == 0
        assert stats2["updated"] == 1
        assert stats2["skipped"] == 0

    def test_skip_relation_lower_confidence(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        sample_typed_relation
    ):
        """Test skip relation si nouvelle confidence <= ancienne."""
        # Écrire relation initiale (confidence=0.92)
        stats1 = neo4j_writer.write_relations(
            relations=[sample_typed_relation],
            document_id="test-doc-123",
            document_name="Test Document"
        )

        assert stats1["created"] == 1

        # Créer nouvelle relation avec confidence plus basse
        new_metadata = RelationMetadata(
            confidence=0.80,  # Plus basse
            extraction_method=ExtractionMethod.PATTERN,
            source_doc_id="test-doc-456",
            source_chunk_ids=[],
            language="EN",
            created_at=datetime.utcnow(),
            strength=RelationStrength.MODERATE,
            status=RelationStatus.ACTIVE,
            require_validation=True
        )

        new_relation = TypedRelation(
            relation_id="test-rel-3",
            source_concept="test-concept-hana",
            target_concept="test-concept-aes256",
            relation_type=RelationType.USES,
            metadata=new_metadata
        )

        # Écrire nouvelle relation
        stats2 = neo4j_writer.write_relations(
            relations=[new_relation],
            document_id="test-doc-456",
            document_name="Test Document 2"
        )

        # Devrait être skipped
        assert stats2["created"] == 0
        assert stats2["updated"] == 0
        assert stats2["skipped"] == 1

    def test_write_multiple_relations(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        sample_typed_relation
    ):
        """Test écriture multiple relations."""
        # Créer seconde relation (PART_OF)
        metadata2 = RelationMetadata(
            confidence=0.88,
            extraction_method=ExtractionMethod.LLM,
            source_doc_id="test-doc-123",
            source_chunk_ids=["chunk-5"],
            language="EN",
            created_at=datetime.utcnow(),
            strength=RelationStrength.STRONG,
            status=RelationStatus.ACTIVE,
            require_validation=False
        )

        relation2 = TypedRelation(
            relation_id="test-rel-4",
            source_concept="test-concept-hana",
            target_concept="test-concept-s4",
            relation_type=RelationType.PART_OF,
            metadata=metadata2,
            evidence="HANA is part of S/4HANA"
        )

        # Écrire 2 relations
        stats = neo4j_writer.write_relations(
            relations=[sample_typed_relation, relation2],
            document_id="test-doc-123",
            document_name="Test Document"
        )

        # Vérifier stats
        assert stats["total_relations"] == 2
        assert stats["created"] == 2
        assert stats["errors"] == 0
        assert len(stats["relations_by_type"]) == 2
        assert stats["relations_by_type"][RelationType.USES] == 1
        assert stats["relations_by_type"][RelationType.PART_OF] == 1

    def test_skip_relation_if_concepts_not_exist(
        self,
        neo4j_writer,
        sample_canonical_concepts
    ):
        """Test skip relation si concepts n'existent pas."""
        # Créer relation avec concepts inexistants
        metadata = RelationMetadata(
            confidence=0.90,
            extraction_method=ExtractionMethod.LLM,
            source_doc_id="test-doc-999",
            source_chunk_ids=[],
            language="EN",
            created_at=datetime.utcnow(),
            strength=RelationStrength.MODERATE,
            status=RelationStatus.ACTIVE,
            require_validation=False
        )

        relation = TypedRelation(
            relation_id="test-rel-invalid",
            source_concept="nonexistent-concept-1",
            target_concept="nonexistent-concept-2",
            relation_type=RelationType.USES,
            metadata=metadata
        )

        # Écrire relation
        stats = neo4j_writer.write_relations(
            relations=[relation],
            document_id="test-doc-999",
            document_name="Test Invalid"
        )

        # Devrait être skipped (concepts n'existent pas)
        assert stats["created"] == 0
        assert stats["skipped"] == 1

    def test_delete_relations_by_document(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        sample_typed_relation
    ):
        """Test suppression relations par document."""
        # Écrire 2 relations du même document
        metadata2 = RelationMetadata(
            confidence=0.85,
            extraction_method=ExtractionMethod.LLM,
            source_doc_id="test-doc-123",
            source_chunk_ids=[],
            language="EN",
            created_at=datetime.utcnow(),
            strength=RelationStrength.MODERATE,
            status=RelationStatus.ACTIVE,
            require_validation=False
        )

        relation2 = TypedRelation(
            relation_id="test-rel-5",
            source_concept="test-concept-hana",
            target_concept="test-concept-s4",
            relation_type=RelationType.REQUIRES,
            metadata=metadata2
        )

        neo4j_writer.write_relations(
            relations=[sample_typed_relation, relation2],
            document_id="test-doc-123",
            document_name="Test Document"
        )

        # Supprimer relations du document
        deleted_count = neo4j_writer.delete_relations_by_document("test-doc-123")

        # Devrait avoir supprimé 2 relations
        assert deleted_count == 2

    def test_get_relations_outgoing(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        sample_typed_relation,
        neo4j_client
    ):
        """Test récupération relations sortantes d'un concept."""
        # Écrire relation
        neo4j_writer.write_relations(
            relations=[sample_typed_relation],
            document_id="test-doc-123",
            document_name="Test Document"
        )

        # Récupérer relations sortantes de HANA
        relations = neo4j_writer.get_relations_by_concept(
            concept_id="test-concept-hana",
            direction="outgoing"
        )

        assert len(relations) == 1
        assert relations[0]["relation_type"] == "USES"
        assert relations[0]["target_id"] == "test-concept-aes256"
        assert relations[0]["target_name"] == "AES256"
        assert relations[0]["metadata"]["confidence"] == 0.92

    def test_get_relations_incoming(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        sample_typed_relation
    ):
        """Test récupération relations entrantes d'un concept."""
        # Écrire relation
        neo4j_writer.write_relations(
            relations=[sample_typed_relation],
            document_id="test-doc-123",
            document_name="Test Document"
        )

        # Récupérer relations entrantes de AES256
        relations = neo4j_writer.get_relations_by_concept(
            concept_id="test-concept-aes256",
            direction="incoming"
        )

        assert len(relations) == 1
        assert relations[0]["relation_type"] == "USES"
        assert relations[0]["source_id"] == "test-concept-hana"
        assert relations[0]["source_name"] == "SAP HANA"

    def test_get_relations_both_directions(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        sample_typed_relation
    ):
        """Test récupération relations dans les deux sens."""
        # Créer relation bidirectionnelle (HANA USES AES256, S4 REQUIRES HANA)
        metadata2 = RelationMetadata(
            confidence=0.90,
            extraction_method=ExtractionMethod.LLM,
            source_doc_id="test-doc-123",
            source_chunk_ids=[],
            language="EN",
            created_at=datetime.utcnow(),
            strength=RelationStrength.STRONG,
            status=RelationStatus.ACTIVE,
            require_validation=False
        )

        relation2 = TypedRelation(
            relation_id="test-rel-6",
            source_concept="test-concept-s4",
            target_concept="test-concept-hana",
            relation_type=RelationType.REQUIRES,
            metadata=metadata2,
            evidence="S/4HANA requires HANA"
        )

        neo4j_writer.write_relations(
            relations=[sample_typed_relation, relation2],
            document_id="test-doc-123",
            document_name="Test Document"
        )

        # Récupérer toutes relations de HANA (sortantes + entrantes)
        relations = neo4j_writer.get_relations_by_concept(
            concept_id="test-concept-hana",
            direction="both"
        )

        # HANA devrait avoir 2 relations:
        # - Outgoing: HANA USES AES256
        # - Incoming: S4 REQUIRES HANA
        assert len(relations) == 2

        # Vérifier qu'on a bien les deux directions
        directions = {r["direction"] for r in relations}
        assert "outgoing" in directions
        assert "incoming" in directions


@pytest.mark.integration
class TestNeo4jWriterIntegration:
    """Tests d'intégration Neo4j Writer."""

    def test_full_workflow_extraction_to_persistence(
        self,
        neo4j_writer,
        sample_canonical_concepts,
        neo4j_client
    ):
        """Test workflow complet: extraction → persistence."""
        # Simuler résultat extraction LLM (3 relations)
        relations = []

        for i, (source, target, rel_type) in enumerate([
            ("test-concept-hana", "test-concept-aes256", RelationType.USES),
            ("test-concept-hana", "test-concept-s4", RelationType.PART_OF),
            ("test-concept-s4", "test-concept-hana", RelationType.REQUIRES)
        ]):
            metadata = RelationMetadata(
                confidence=0.85 + (i * 0.05),
                extraction_method=ExtractionMethod.LLM,
                source_doc_id="integration-test-doc",
                source_chunk_ids=[f"chunk-{i}"],
                language="EN",
                created_at=datetime.utcnow(),
                strength=RelationStrength.STRONG,
                status=RelationStatus.ACTIVE,
                require_validation=False
            )

            relation = TypedRelation(
                relation_id=f"integration-rel-{i}",
                source_concept=source,
                target_concept=target,
                relation_type=rel_type,
                metadata=metadata,
                evidence=f"Evidence {i}"
            )

            relations.append(relation)

        # Persister toutes relations
        stats = neo4j_writer.write_relations(
            relations=relations,
            document_id="integration-test-doc",
            document_name="Integration Test Document"
        )

        # Vérifier stats
        assert stats["total_relations"] == 3
        assert stats["created"] == 3
        assert stats["errors"] == 0

        # Vérifier dans Neo4j que toutes relations existent
        query = """
        MATCH (source:CanonicalConcept {tenant_id: $tenant_id})
        -[r]->
        (target:CanonicalConcept {tenant_id: $tenant_id})
        WHERE r.source_doc_id = $doc_id
        RETURN count(r) as relation_count
        """

        with neo4j_client.driver.session(database=neo4j_client.database) as session:
            result = session.run(
                query,
                tenant_id="test-tenant",
                doc_id="integration-test-doc"
            )
            records = [dict(rec) for rec in result]

        assert records[0]["relation_count"] == 3
