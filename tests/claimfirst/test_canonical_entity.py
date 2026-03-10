# tests/claimfirst/test_canonical_entity.py
"""Tests du modèle CanonicalEntity."""

import pytest

from knowbase.claimfirst.models.canonical_entity import CanonicalEntity
from knowbase.claimfirst.models.entity import EntityType


class TestCanonicalEntityId:
    """Tests de génération d'ID déterministe."""

    def test_id_deterministic(self):
        """Même input → même ID."""
        id1 = CanonicalEntity.make_id("default", "SAP Fiori")
        id2 = CanonicalEntity.make_id("default", "SAP Fiori")
        assert id1 == id2
        assert id1.startswith("ce_")
        assert len(id1) == 15  # "ce_" + 12 hex chars

    def test_id_case_insensitive(self):
        """L'ID est insensible à la casse."""
        id1 = CanonicalEntity.make_id("default", "SAP Fiori")
        id2 = CanonicalEntity.make_id("default", "sap fiori")
        assert id1 == id2

    def test_id_different_tenant(self):
        """Tenants différents → IDs différents."""
        id1 = CanonicalEntity.make_id("tenant_a", "SAP Fiori")
        id2 = CanonicalEntity.make_id("tenant_b", "SAP Fiori")
        assert id1 != id2

    def test_id_different_name(self):
        """Noms différents → IDs différents."""
        id1 = CanonicalEntity.make_id("default", "SAP Fiori")
        id2 = CanonicalEntity.make_id("default", "SAP BTP")
        assert id1 != id2


class TestNeo4jRoundTrip:
    """Tests de sérialisation Neo4j."""

    def test_to_neo4j_properties(self):
        """to_neo4j_properties retourne les bons champs."""
        ce = CanonicalEntity(
            canonical_entity_id="ce_abc123def456",
            canonical_name="SAP Fiori",
            tenant_id="default",
            entity_type=EntityType.PRODUCT,
            source_entity_ids=["e1", "e2", "e3"],
            doc_count=5,
            total_mention_count=42,
            method="alias_identity",
        )
        props = ce.to_neo4j_properties()
        assert props["canonical_entity_id"] == "ce_abc123def456"
        assert props["canonical_name"] == "SAP Fiori"
        assert props["entity_type"] == "product"
        assert props["source_entity_ids"] == ["e1", "e2", "e3"]
        assert props["doc_count"] == 5
        assert props["total_mention_count"] == 42
        assert props["method"] == "alias_identity"
        assert "created_at" in props

    def test_from_neo4j_record(self):
        """from_neo4j_record reconstruit correctement."""
        record = {
            "canonical_entity_id": "ce_abc123def456",
            "canonical_name": "SAP Fiori",
            "tenant_id": "default",
            "entity_type": "product",
            "source_entity_ids": ["e1", "e2"],
            "doc_count": 3,
            "total_mention_count": 20,
            "method": "prefix_dedup",
            "created_at": "2026-02-20T10:00:00",
        }
        ce = CanonicalEntity.from_neo4j_record(record)
        assert ce.canonical_entity_id == "ce_abc123def456"
        assert ce.canonical_name == "SAP Fiori"
        assert ce.entity_type == EntityType.PRODUCT
        assert ce.source_entity_ids == ["e1", "e2"]

    def test_round_trip(self):
        """to_neo4j → from_neo4j donne un objet équivalent."""
        original = CanonicalEntity(
            canonical_entity_id="ce_test12345678",
            canonical_name="Cloud Connector",
            tenant_id="default",
            entity_type=EntityType.SERVICE,
            source_entity_ids=["e10", "e20"],
            doc_count=2,
            total_mention_count=15,
            method="alias_identity",
        )
        props = original.to_neo4j_properties()
        restored = CanonicalEntity.from_neo4j_record(props)
        assert restored.canonical_entity_id == original.canonical_entity_id
        assert restored.canonical_name == original.canonical_name
        assert restored.entity_type == original.entity_type
        assert restored.source_entity_ids == original.source_entity_ids
        assert restored.doc_count == original.doc_count


class TestMajorityVoteType:
    """Tests du vote majoritaire pour entity_type."""

    def test_clear_majority(self):
        """Un type clairement majoritaire est élu."""
        types = [EntityType.PRODUCT, EntityType.PRODUCT, EntityType.SERVICE]
        result = CanonicalEntity.majority_vote_type(types)
        assert result == EntityType.PRODUCT

    def test_all_same(self):
        """Tous les types identiques → ce type."""
        types = [EntityType.CONCEPT, EntityType.CONCEPT]
        assert CanonicalEntity.majority_vote_type(types) == EntityType.CONCEPT

    def test_ambiguous_50_50_fallback_other(self):
        """50/50 entre deux types → fallback OTHER."""
        types = [EntityType.PRODUCT, EntityType.SERVICE]
        assert CanonicalEntity.majority_vote_type(types) == EntityType.OTHER

    def test_other_ignored_in_vote(self):
        """OTHER ne compte pas dans le vote."""
        types = [EntityType.PRODUCT, EntityType.OTHER, EntityType.OTHER]
        assert CanonicalEntity.majority_vote_type(types) == EntityType.PRODUCT

    def test_all_other(self):
        """Que des OTHER → OTHER."""
        types = [EntityType.OTHER, EntityType.OTHER]
        assert CanonicalEntity.majority_vote_type(types) == EntityType.OTHER

    def test_empty(self):
        """Liste vide → OTHER."""
        assert CanonicalEntity.majority_vote_type([]) == EntityType.OTHER
