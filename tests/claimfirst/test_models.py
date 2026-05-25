# tests/claimfirst/test_models.py
"""
Tests for Claim-First models.

Tests:
- Claim model with validation
- Entity model with stoplist
- Facet model with domain hierarchy
- Passage model with DocItem conversion
- ClaimCluster and ClaimRelation
"""

import json

import pytest
from datetime import datetime

from knowbase.claimfirst.models.claim import (
    Claim,
    ClaimType,
    ClaimScope,
    ClaimQualifier,
    QualifierType,
)
from knowbase.claimfirst.models.entity import (
    Entity,
    EntityType,
    ENTITY_STOPLIST,
    is_valid_entity_name,
)
from knowbase.claimfirst.models.facet import (
    Facet,
    FacetKind,
    get_predefined_facets,
)
from knowbase.claimfirst.models.passage import Passage
from knowbase.claimfirst.models.result import (
    ClaimFirstResult,
    ClaimCluster,
    ClaimRelation,
    RelationType,
)


class TestClaim:
    """Tests for Claim model."""

    def test_claim_creation_valid(self):
        """Test creating a valid claim."""
        claim = Claim(
            claim_id="claim_001",
            tenant_id="default",
            doc_id="doc_001",
            text="TLS 1.2 or higher is required for all connections.",
            claim_type=ClaimType.PRESCRIPTIVE,
            verbatim_quote="TLS 1.2 or higher is required for all connections.",
            passage_id="default:doc_001:item_001",
            unit_ids=["default:doc_001:item_001#U1"],
            confidence=0.95,
        )

        assert claim.claim_id == "claim_001"
        assert claim.claim_type == ClaimType.PRESCRIPTIVE
        assert claim.confidence == 0.95
        assert len(claim.unit_ids) == 1

    def test_claim_requires_verbatim_quote(self):
        """Test that verbatim_quote is required."""
        with pytest.raises(ValueError, match="verbatim_quote"):
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="Some claim text here.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="",  # Empty not allowed
                passage_id="default:doc_001:item_001",
            )

    def test_claim_text_max_length(self):
        """Test that claim text has max length (500 chars)."""
        long_text = "x" * 600
        with pytest.raises(ValueError, match="too long"):
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text=long_text,
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="Some quote.",
                passage_id="default:doc_001:item_001",
            )

    def test_claim_fingerprint_deterministic(self):
        """Test that fingerprint is deterministic."""
        claim1 = Claim(
            claim_id="claim_001",
            tenant_id="default",
            doc_id="doc_001",
            text="TLS 1.2 is required.",
            claim_type=ClaimType.PRESCRIPTIVE,
            verbatim_quote="TLS 1.2 is required.",
            passage_id="default:doc_001:item_001",
        )
        claim2 = Claim(
            claim_id="claim_002",  # Different ID
            tenant_id="default",
            doc_id="doc_001",
            text="TLS 1.2 is required.",  # Same text
            claim_type=ClaimType.PRESCRIPTIVE,
            verbatim_quote="TLS 1.2 is required.",
            passage_id="default:doc_001:item_002",
        )

        # Same fingerprint because same semantic content
        assert claim1.compute_fingerprint() == claim2.compute_fingerprint()

    def test_claim_scope(self):
        """Test ClaimScope."""
        scope = ClaimScope(
            version="2023.10",
            region="EU",
            edition="Enterprise",
            conditions=["requires_license"],
        )

        assert scope.version == "2023.10"
        assert "EU" in scope.to_scope_key()
        assert "Enterprise" in scope.to_scope_key()

    def test_claim_to_neo4j_properties(self):
        """Test Neo4j property conversion."""
        claim = Claim(
            claim_id="claim_001",
            tenant_id="default",
            doc_id="doc_001",
            text="Test claim text.",
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Test claim text.",
            passage_id="default:doc_001:item_001",
            scope=ClaimScope(version="2023.10"),
        )

        props = claim.to_neo4j_properties()

        assert props["claim_id"] == "claim_001"
        assert props["claim_type"] == "FACTUAL"
        assert props["scope_version"] == "2023.10"
        assert "fingerprint" in props

    def test_claim_types(self):
        """Test all claim types exist."""
        types = [
            ClaimType.FACTUAL,
            ClaimType.PRESCRIPTIVE,
            ClaimType.DEFINITIONAL,
            ClaimType.CONDITIONAL,
            ClaimType.PERMISSIVE,
            ClaimType.PROCEDURAL,
        ]
        assert len(types) == 6


class TestPhaseBClaimEnrichment:
    """Phase B (25/05/2026) — qualifiers structurés + rôle procédural.

    Cf ADR_PHASE_B_HYPER_RELATIONAL_CLAIMS §3.1-3.3. Domain-agnostic :
    les types de qualifiers et procedures sont universels (testés ici sur
    des exemples SAP, médical et juridique).
    """

    def _base_claim_kwargs(self, **overrides):
        kwargs = dict(
            claim_id="claim_pb_001",
            tenant_id="default",
            doc_id="doc_001",
            text="MFA is enforced for all administrative access.",
            claim_type=ClaimType.PRESCRIPTIVE,
            verbatim_quote="MFA is enforced for all administrative access.",
            passage_id="default:doc_001:item_001",
        )
        kwargs.update(overrides)
        return kwargs

    def test_qualifier_types_universal(self):
        """Les 5 types de qualifiers existent (domain-agnostic)."""
        types = [
            QualifierType.TEMPORAL,
            QualifierType.SPATIAL,
            QualifierType.VERSION,
            QualifierType.CONDITION,
            QualifierType.SCOPE_LIMIT,
        ]
        assert len(types) == 5
        assert QualifierType.TEMPORAL.value == "temporal"
        assert QualifierType.SCOPE_LIMIT.value == "scope_limit"

    def test_qualifier_creation_and_confidence_bounds(self):
        """ClaimQualifier valide + confidence borné [0,1]."""
        q = ClaimQualifier(
            qualifier_type=QualifierType.TEMPORAL,
            value="depuis 2024",
            confidence=0.9,
        )
        assert q.qualifier_type == QualifierType.TEMPORAL
        assert q.value == "depuis 2024"
        assert q.confidence == 0.9

        # confidence défaut = 1.0
        q2 = ClaimQualifier(qualifier_type=QualifierType.CONDITION, value="si MFA activé")
        assert q2.confidence == 1.0

        # hors borne → rejet
        with pytest.raises(ValueError):
            ClaimQualifier(
                qualifier_type=QualifierType.VERSION, value="S/4HANA 2023", confidence=1.5
            )

    def test_qualifiers_default_empty(self):
        """Rétrocompat : un claim sans qualifiers a une liste vide + pas de clé Neo4j."""
        claim = Claim(**self._base_claim_kwargs())
        assert claim.qualifiers == []
        assert claim.procedure_role is None
        assert claim.procedure_id is None
        assert claim.step_index is None

        props = claim.to_neo4j_properties()
        # Pas de pollution du payload Neo4j si vide
        assert "qualifiers_json" not in props
        assert "procedure_role" not in props
        assert "procedure_id" not in props
        assert "step_index" not in props

    def test_qualifiers_to_neo4j_properties(self):
        """qualifiers + champs procéduraux sérialisés dans le payload Neo4j."""
        claim = Claim(**self._base_claim_kwargs(
            claim_type=ClaimType.PROCEDURAL,
            qualifiers=[
                ClaimQualifier(qualifier_type=QualifierType.CONDITION, value="pour clients RISE", confidence=0.8),
                ClaimQualifier(qualifier_type=QualifierType.VERSION, value="S/4HANA 2023"),
            ],
            procedure_role="STEP",
            procedure_id="proc_abc",
            step_index=2,
        ))

        props = claim.to_neo4j_properties()
        assert "qualifiers_json" in props
        assert props["procedure_role"] == "STEP"
        assert props["procedure_id"] == "proc_abc"
        assert props["step_index"] == 2

        parsed = json.loads(props["qualifiers_json"])
        assert len(parsed) == 2
        assert parsed[0]["qualifier_type"] == "condition"
        assert parsed[0]["value"] == "pour clients RISE"

    def test_round_trip_neo4j(self):
        """Round-trip to_neo4j_properties → from_neo4j_record préserve Phase B."""
        original = Claim(**self._base_claim_kwargs(
            text="La posologie est réduite chez l'adulte de plus de 65 ans.",
            verbatim_quote="La posologie est réduite chez l'adulte de plus de 65 ans.",
            claim_type=ClaimType.CONDITIONAL,
            qualifiers=[
                ClaimQualifier(qualifier_type=QualifierType.CONDITION, value="adulte >65 ans", confidence=0.95),
                ClaimQualifier(qualifier_type=QualifierType.SCOPE_LIMIT, value="hors insuffisance rénale"),
            ],
            procedure_role="OUTCOME",
            procedure_id="proc_xyz",
            step_index=5,
        ))

        props = original.to_neo4j_properties()
        # Neo4j renvoie created_at en ISO string ; on simule le record
        record = dict(props)
        restored = Claim.from_neo4j_record(record)

        assert len(restored.qualifiers) == 2
        assert restored.qualifiers[0].qualifier_type == QualifierType.CONDITION
        assert restored.qualifiers[0].value == "adulte >65 ans"
        assert restored.qualifiers[0].confidence == 0.95
        assert restored.qualifiers[1].qualifier_type == QualifierType.SCOPE_LIMIT
        assert restored.procedure_role == "OUTCOME"
        assert restored.procedure_id == "proc_xyz"
        assert restored.step_index == 5

    def test_round_trip_no_qualifiers(self):
        """Round-trip d'un claim legacy (sans Phase B) reste valide."""
        original = Claim(**self._base_claim_kwargs())
        record = dict(original.to_neo4j_properties())
        restored = Claim.from_neo4j_record(record)
        assert restored.qualifiers == []
        assert restored.procedure_role is None
        assert restored.step_index is None

    def test_from_neo4j_record_corrupt_qualifiers_json(self):
        """JSON qualifiers corrompu → liste vide (fail-safe, pas d'exception)."""
        original = Claim(**self._base_claim_kwargs())
        record = dict(original.to_neo4j_properties())
        record["qualifiers_json"] = "{ not valid json"
        restored = Claim.from_neo4j_record(record)
        assert restored.qualifiers == []


class TestEntity:
    """Tests for Entity model."""

    def test_entity_creation(self):
        """Test creating a valid entity."""
        entity = Entity(
            entity_id="entity_001",
            tenant_id="default",
            name="SAP BTP",
            entity_type=EntityType.PRODUCT,
        )

        assert entity.name == "SAP BTP"
        assert entity.entity_type == EntityType.PRODUCT
        assert entity.normalized_name == "sap btp"

    def test_entity_normalization(self):
        """Test name normalization."""
        assert Entity.normalize("SAP BTP") == "sap btp"
        # Le point est supprimé, seuls alphanumériques, espaces et tirets sont conservés
        assert Entity.normalize("  TLS 1.2  ") == "tls 12"
        assert Entity.normalize("TLS-1.3") == "tls-13"
        assert Entity.normalize("GDPR") == "gdpr"

    def test_entity_matches(self):
        """Test entity matching in text."""
        entity = Entity(
            entity_id="entity_001",
            tenant_id="default",
            name="SAP BTP",
            entity_type=EntityType.PRODUCT,
        )

        assert entity.matches("SAP BTP is a platform")
        assert entity.matches("sap btp provides...")
        assert not entity.matches("SAP S/4HANA")

    def test_entity_stoplist(self):
        """Test stoplist filtering."""
        assert "system" in ENTITY_STOPLIST
        assert "information" in ENTITY_STOPLIST
        assert "data" in ENTITY_STOPLIST

        assert not is_valid_entity_name("System")
        assert not is_valid_entity_name("data")
        assert is_valid_entity_name("SAP BTP")
        assert is_valid_entity_name("TLS")

    def test_entity_types(self):
        """Test all entity types exist."""
        types = [
            EntityType.PRODUCT,
            EntityType.SERVICE,
            EntityType.FEATURE,
            EntityType.ACTOR,
            EntityType.CONCEPT,
            EntityType.LEGAL_TERM,
            EntityType.STANDARD,
            EntityType.OTHER,
        ]
        assert len(types) == 8


class TestFacet:
    """Tests for Facet model."""

    def test_facet_creation(self):
        """Test creating a facet."""
        facet = Facet(
            facet_id="facet_security_encryption",
            tenant_id="default",
            facet_name="Security / Encryption",
            facet_kind=FacetKind.CAPABILITY,
            domain="security.encryption",
            canonical_question="What encryption is used?",
        )

        assert facet.domain == "security.encryption"
        assert facet.domain_root == "security"
        assert facet.domain_parts == ["security", "encryption"]

    def test_facet_create_from_domain(self):
        """Test factory method."""
        facet = Facet.create_from_domain(
            domain="compliance.gdpr",
            kind=FacetKind.DOMAIN,
            tenant_id="default",
            canonical_question="Is GDPR compliant?",
        )

        assert facet.facet_id == "facet_compliance_gdpr_domain"
        assert facet.facet_name == "Compliance / Gdpr"
        assert facet.parent_domain == "compliance"

    def test_facet_matches_domain(self):
        """Test domain matching."""
        facet = Facet(
            facet_id="facet_security_encryption",
            tenant_id="default",
            facet_name="Security / Encryption",
            facet_kind=FacetKind.CAPABILITY,
            domain="security.encryption",
        )

        assert facet.matches_domain("security.encryption")
        assert facet.matches_domain("security")  # Parent matches
        assert not facet.matches_domain("compliance")

    def test_predefined_facets(self):
        """Test predefined facets."""
        facets = get_predefined_facets("default")

        assert len(facets) > 0
        domains = [f.domain for f in facets]
        assert "security" in domains
        assert "compliance" in domains
        assert "operations" in domains

    def test_facet_kinds(self):
        """Test all facet kinds exist."""
        kinds = [
            FacetKind.DOMAIN,
            FacetKind.RISK,
            FacetKind.OBLIGATION,
            FacetKind.LIMITATION,
            FacetKind.CAPABILITY,
            FacetKind.PROCEDURE,
        ]
        assert len(kinds) == 6


class TestPassage:
    """Tests for Passage model."""

    def test_passage_creation(self):
        """Test creating a passage."""
        passage = Passage(
            passage_id="default:doc_001:item_001",
            tenant_id="default",
            doc_id="doc_001",
            text="This is the passage text.",
            page_no=1,
            char_start=0,
            char_end=25,
        )

        assert passage.char_length == 25
        assert passage.unit_count == 0

    def test_passage_contains_unit_span(self):
        """Test unit span containment check."""
        passage = Passage(
            passage_id="default:doc_001:item_001",
            tenant_id="default",
            doc_id="doc_001",
            text="This is the passage text.",
            char_start=100,
            char_end=200,
        )

        # Unit inside passage
        assert passage.contains_unit_span(110, 150)
        assert passage.contains_unit_span(100, 200)  # Exact match

        # Unit outside passage
        assert not passage.contains_unit_span(50, 100)
        assert not passage.contains_unit_span(200, 250)
        assert not passage.contains_unit_span(90, 150)  # Partial overlap

    def test_passage_from_docitem(self):
        """Test creating passage from mock DocItem."""
        class MockDocItem:
            item_id = "item_001"
            doc_id = "doc_001"
            text = "Sample text content."
            page_no = 5
            charspan_start = 100
            charspan_end = 120
            section_id = "section_001"
            item_type = "paragraph"
            reading_order_index = 10

        docitem = MockDocItem()
        passage = Passage.from_docitem(docitem, tenant_id="default")

        assert passage.passage_id == "default:doc_001:item_001"
        assert passage.page_no == 5
        assert passage.char_start == 100
        assert passage.char_end == 120

    def test_passage_from_docitem_none_charspan(self):
        """Test passage creation with None charspan values."""
        class MockDocItem:
            item_id = "item_001"
            doc_id = "doc_001"
            text = "Sample text."
            page_no = 1
            charspan_start = None
            charspan_end = None
            section_id = None
            item_type = "paragraph"
            reading_order_index = None

        docitem = MockDocItem()
        passage = Passage.from_docitem(docitem, tenant_id="default")

        assert passage.char_start == 0
        assert passage.char_end == len("Sample text.")


class TestClaimCluster:
    """Tests for ClaimCluster model."""

    def test_cluster_creation(self):
        """Test creating a cluster."""
        cluster = ClaimCluster(
            cluster_id="cluster_001",
            tenant_id="default",
            canonical_label="TLS requirement",
            claim_ids=["claim_001", "claim_002"],
            doc_ids=["doc_001", "doc_002"],
        )

        assert cluster.claim_count == 2
        assert cluster.doc_count == 2

    def test_cluster_add_claim(self):
        """Test adding claim to cluster."""
        cluster = ClaimCluster(
            cluster_id="cluster_001",
            tenant_id="default",
            canonical_label="Test cluster",
        )

        claim = Claim(
            claim_id="claim_001",
            tenant_id="default",
            doc_id="doc_001",
            text="Test claim.",
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Test claim.",
            passage_id="p1",
            confidence=0.9,
        )

        cluster.add_claim(claim)

        assert "claim_001" in cluster.claim_ids
        assert "doc_001" in cluster.doc_ids
        assert cluster.claim_count == 1


class TestClaimRelation:
    """Tests for ClaimRelation model."""

    def test_relation_creation(self):
        """Test creating a relation."""
        relation = ClaimRelation(
            source_claim_id="claim_001",
            target_claim_id="claim_002",
            relation_type=RelationType.CONTRADICTS,
            confidence=0.85,
            basis="Negation detected",
        )

        assert relation.relation_type == RelationType.CONTRADICTS
        assert relation.confidence == 0.85

    def test_relation_types(self):
        """Test all relation types exist."""
        types = [
            RelationType.CONTRADICTS,
            RelationType.REFINES,
            RelationType.QUALIFIES,
        ]
        assert len(types) == 3


class TestClaimFirstResult:
    """Tests for ClaimFirstResult model."""

    def test_result_creation(self):
        """Test creating a result."""
        result = ClaimFirstResult(
            tenant_id="default",
            doc_id="doc_001",
        )

        assert result.claim_count == 0
        assert result.entity_count == 0
        assert result.passage_count == 0

    def test_result_with_data(self):
        """Test result with actual data."""
        claim = Claim(
            claim_id="claim_001",
            tenant_id="default",
            doc_id="doc_001",
            text="Test claim.",
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Test claim.",
            passage_id="p1",
        )

        passage = Passage(
            passage_id="p1",
            tenant_id="default",
            doc_id="doc_001",
            text="Test passage.",
        )

        entity = Entity(
            entity_id="e1",
            tenant_id="default",
            name="Test Entity",
            entity_type=EntityType.CONCEPT,
        )

        result = ClaimFirstResult(
            tenant_id="default",
            doc_id="doc_001",
            claims=[claim],
            passages=[passage],
            entities=[entity],
            claim_passage_links=[("claim_001", "p1")],
            claim_entity_links=[("claim_001", "e1")],
        )

        assert result.claim_count == 1
        assert result.passage_count == 1
        assert result.entity_count == 1
        assert result.get_claim("claim_001") == claim
        assert result.get_passage("p1") == passage

    def test_result_summary(self):
        """Test result summary."""
        result = ClaimFirstResult(
            tenant_id="default",
            doc_id="doc_001",
            processing_time_ms=1500,
            llm_calls=10,
        )

        summary = result.to_summary()

        assert summary["doc_id"] == "doc_001"
        assert summary["processing"]["time_ms"] == 1500
        assert summary["processing"]["llm_calls"] == 10
