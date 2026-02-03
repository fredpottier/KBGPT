# tests/claimfirst/test_subject_resolution.py
"""
Tests pour Subject Resolution (INV-8, INV-9, INV-10).

Valide:
- SubjectAnchor avec aliases typés
- DocumentContext avec qualificateurs
- SubjectResolver avec règle DELTA
- ContextExtractor patterns
"""

import pytest
from datetime import datetime

from knowbase.claimfirst.models.subject_anchor import (
    SubjectAnchor,
    AliasSource,
    SUBJECT_BLACKLIST,
    is_valid_subject_name,
)
from knowbase.claimfirst.models.document_context import (
    DocumentContext,
    ResolutionStatus,
    BOOTSTRAP_QUALIFIERS,
    extract_bootstrap_qualifiers,
)
from knowbase.claimfirst.resolution.subject_resolver import (
    SubjectResolver,
    ResolverResult,
)


class TestSubjectAnchor:
    """Tests pour le modèle SubjectAnchor (INV-9)."""

    def test_create_new_subject(self):
        """Test création d'un nouveau SubjectAnchor."""
        anchor = SubjectAnchor.create_new(
            tenant_id="default",
            canonical_name="SAP S/4HANA Cloud Private Edition",
            doc_id="doc_001",
        )

        assert anchor.subject_id.startswith("subject_")
        assert anchor.canonical_name == "SAP S/4HANA Cloud Private Edition"
        assert anchor.tenant_id == "default"
        assert "SAP S/4HANA Cloud Private Edition" in anchor.aliases_explicit
        assert "doc_001" in anchor.source_doc_ids

    def test_strong_aliases(self):
        """Test que strong_aliases n'inclut pas les inferred (CORRECTIF 5)."""
        anchor = SubjectAnchor(
            subject_id="test_1",
            tenant_id="default",
            canonical_name="SAP BTP",
            aliases_explicit=["SAP Business Technology Platform"],
            aliases_inferred=["BTP Cloud"],  # LLM-suggéré
            aliases_learned=["BTP Enterprise"],
        )

        strong = anchor.strong_aliases()

        assert "SAP Business Technology Platform" in strong
        assert "BTP Enterprise" in strong
        assert "BTP Cloud" not in strong  # Inferred = FAIBLE

    def test_add_explicit_alias_promotes_from_inferred(self):
        """Test que add_explicit_alias promeut un alias inféré."""
        anchor = SubjectAnchor(
            subject_id="test_1",
            tenant_id="default",
            canonical_name="SAP BTP",
            aliases_inferred=["BTP Cloud"],
        )

        # Promouvoir vers explicit
        anchor.add_explicit_alias("BTP Cloud")

        assert "BTP Cloud" in anchor.aliases_explicit
        assert "BTP Cloud" not in anchor.aliases_inferred

    def test_qualifier_candidates_vs_validated(self):
        """Test séparation qualifiers_candidates vs qualifiers_validated (PATCH F)."""
        anchor = SubjectAnchor.create_new(
            tenant_id="default",
            canonical_name="Test Product",
        )

        # Ajouter un candidat
        anchor.add_qualifier_candidate("release_quarter", "Q1 2024")

        assert "release_quarter" in anchor.qualifiers_candidates
        assert "release_quarter" not in anchor.qualifiers_validated

        # Promouvoir
        anchor.promote_qualifier("release_quarter")

        assert "release_quarter" in anchor.qualifiers_validated
        assert "release_quarter" not in anchor.qualifiers_candidates

    def test_neo4j_serialization(self):
        """Test sérialisation vers Neo4j."""
        anchor = SubjectAnchor.create_new(
            tenant_id="default",
            canonical_name="SAP S/4HANA",
            domain="SAP",
        )

        props = anchor.to_neo4j_properties()

        assert props["subject_id"] == anchor.subject_id
        assert props["canonical_name"] == "SAP S/4HANA"
        assert props["domain"] == "SAP"
        assert "subject_hash" in props


class TestDocumentContext:
    """Tests pour le modèle DocumentContext (INV-8)."""

    def test_create_for_document(self):
        """Test création d'un DocumentContext."""
        context = DocumentContext.create_for_document(
            doc_id="doc_001",
            tenant_id="default",
            raw_subjects=["RISE with SAP S/4HANA"],
            document_type="Operations Guide",
        )

        assert context.doc_id == "doc_001"
        assert "RISE with SAP S/4HANA" in context.raw_subjects
        assert context.document_type == "Operations Guide"
        assert context.resolution_status == ResolutionStatus.UNRESOLVED

    def test_add_subject(self):
        """Test ajout d'un sujet résolu."""
        context = DocumentContext.create_for_document(
            doc_id="doc_001",
            tenant_id="default",
        )

        context.add_subject(
            subject_id="subject_123",
            status=ResolutionStatus.RESOLVED,
            confidence=1.0,
        )

        assert "subject_123" in context.subject_ids
        assert context.resolution_status == ResolutionStatus.RESOLVED
        assert context.resolution_confidence == 1.0

    def test_set_qualifier(self):
        """Test définition de qualificateurs."""
        context = DocumentContext.create_for_document(
            doc_id="doc_001",
            tenant_id="default",
        )

        # Qualificateur validé
        context.set_qualifier("version", "2023", validated=True)
        # Qualificateur candidat
        context.set_qualifier("release_quarter", "Q1", validated=False)

        assert context.qualifiers["version"] == "2023"
        assert context.qualifier_candidates["release_quarter"] == "Q1"

    def test_scope_description(self):
        """Test génération de la description du scope."""
        context = DocumentContext(
            doc_id="doc_001",
            tenant_id="default",
            raw_subjects=["SAP S/4HANA"],
            qualifiers={"version": "2023", "region": "EU"},
            document_type="Security Guide",
        )

        desc = context.get_scope_description()

        assert "SAP S/4HANA" in desc
        assert "2023" in desc
        assert "EU" in desc


class TestSubjectResolver:
    """Tests pour SubjectResolver (INV-9)."""

    def test_exact_match_on_canonical(self):
        """Test match exact sur canonical_name."""
        resolver = SubjectResolver(tenant_id="default")

        anchor = SubjectAnchor.create_new(
            tenant_id="default",
            canonical_name="SAP BTP",
        )

        result = resolver.resolve(
            raw_subject="SAP BTP",
            existing_anchors=[anchor],
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.confidence == 1.0
        assert result.match_type == "exact"
        assert result.anchor == anchor

    def test_exact_match_on_explicit_alias(self):
        """Test match exact sur alias_explicit."""
        resolver = SubjectResolver(tenant_id="default")

        anchor = SubjectAnchor(
            subject_id="subject_1",
            tenant_id="default",
            canonical_name="SAP Business Technology Platform",
            aliases_explicit=["SAP BTP", "BTP"],
        )

        result = resolver.resolve(
            raw_subject="SAP BTP",
            existing_anchors=[anchor],
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.confidence == 1.0
        assert result.match_type == "exact"

    def test_match_on_learned_alias(self):
        """Test match sur alias_learned avec confiance 0.95."""
        resolver = SubjectResolver(tenant_id="default")

        anchor = SubjectAnchor(
            subject_id="subject_1",
            tenant_id="default",
            canonical_name="SAP BTP",
            aliases_learned=["BTP Enterprise"],
        )

        result = resolver.resolve(
            raw_subject="BTP Enterprise",
            existing_anchors=[anchor],
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.confidence == 0.95  # LEARNED_CONFIDENCE
        assert result.match_type == "learned"

    def test_no_match_on_inferred_alone(self):
        """Test que aliases_inferred ne crée PAS de match automatique."""
        resolver = SubjectResolver(tenant_id="default")

        anchor = SubjectAnchor(
            subject_id="subject_1",
            tenant_id="default",
            canonical_name="SAP BTP",
            aliases_inferred=["BTP Cloud Platform"],  # FAIBLE
        )

        result = resolver.resolve(
            raw_subject="BTP Cloud Platform",
            existing_anchors=[anchor],
            create_if_missing=False,
        )

        # Pas de match exact, pas d'embedding → UNRESOLVED
        assert result.status == ResolutionStatus.UNRESOLVED
        assert result.anchor is None

    def test_create_new_subject_filters_blacklist(self):
        """Test que les termes génériques sont rejetés (CORRECTIF 4)."""
        resolver = SubjectResolver(tenant_id="default")

        # Terme trop générique
        result = resolver.resolve(
            raw_subject="Overview",
            existing_anchors=[],
            create_if_missing=True,
        )

        assert result.status == ResolutionStatus.UNRESOLVED
        assert result.anchor is None
        assert result.match_type == "rejected"

    def test_create_new_subject_valid(self):
        """Test création de sujet valide."""
        resolver = SubjectResolver(tenant_id="default")

        result = resolver.resolve(
            raw_subject="SAP Analytics Cloud",
            existing_anchors=[],
            create_if_missing=True,
        )

        assert result.status == ResolutionStatus.UNRESOLVED  # Nouveau = pas confirmé
        assert result.anchor is not None
        assert result.match_type == "new"
        assert result.anchor.canonical_name == "SAP Analytics Cloud"

    def test_normalization_lowercase(self):
        """Test normalisation case-insensitive."""
        resolver = SubjectResolver(tenant_id="default")

        anchor = SubjectAnchor.create_new(
            tenant_id="default",
            canonical_name="SAP BTP",
        )

        result = resolver.resolve(
            raw_subject="sap btp",  # lowercase
            existing_anchors=[anchor],
        )

        assert result.status == ResolutionStatus.RESOLVED


class TestIsValidSubjectName:
    """Tests pour la fonction is_valid_subject_name (CORRECTIF 4)."""

    def test_rejects_blacklist(self):
        """Test rejet des termes dans la blacklist."""
        for term in ["Overview", "Introduction", "Security", "Guide"]:
            assert not is_valid_subject_name(term)

    def test_rejects_short_terms(self):
        """Test rejet des termes trop courts."""
        assert not is_valid_subject_name("API")
        assert not is_valid_subject_name("DB")

    def test_accepts_valid_subjects(self):
        """Test acceptation des sujets valides."""
        assert is_valid_subject_name("SAP S/4HANA")
        assert is_valid_subject_name("Microsoft Azure")
        assert is_valid_subject_name("GDPR Compliance")


class TestExtractBootstrapQualifiers:
    """Tests pour l'extraction de qualificateurs bootstrap (INV-10)."""

    def test_extracts_version(self):
        """Test extraction du pattern version."""
        text = "This document applies to version 2023.10 of SAP BTP."
        qualifiers = extract_bootstrap_qualifiers(text)

        assert "version" in qualifiers
        assert qualifiers["version"] == "2023.10"

    def test_extracts_region(self):
        """Test extraction du pattern region."""
        text = "Available for EU and APAC regions."
        qualifiers = extract_bootstrap_qualifiers(text)

        assert "region" in qualifiers
        assert qualifiers["region"] in ["EU", "APAC"]

    def test_extracts_edition(self):
        """Test extraction du pattern edition."""
        text = "SAP S/4HANA Enterprise Edition Cloud deployment."
        qualifiers = extract_bootstrap_qualifiers(text)

        assert "edition" in qualifiers
        assert "Enterprise" in qualifiers["edition"]

    def test_extracts_year(self):
        """Test extraction de l'année."""
        text = "Document published in 2024 for the new platform."
        qualifiers = extract_bootstrap_qualifiers(text)

        assert "year" in qualifiers
        assert qualifiers["year"] == "2024"


class TestResolutionStatus:
    """Tests pour ResolutionStatus."""

    def test_enum_values(self):
        """Test que tous les statuts sont définis."""
        assert ResolutionStatus.RESOLVED.value == "resolved"
        assert ResolutionStatus.LOW_CONFIDENCE.value == "low_confidence"
        assert ResolutionStatus.AMBIGUOUS.value == "ambiguous"
        assert ResolutionStatus.UNRESOLVED.value == "unresolved"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
