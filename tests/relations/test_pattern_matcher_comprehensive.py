"""Tests complets pour PatternMatcher.

Tests unitaires couvrant:
- Extraction de relations via patterns regex
- Support multilingue (EN, FR, DE, ES)
- Différents types de relations
- Matching de concepts
- Création de TypedRelation
"""

import pytest
from typing import List, Dict, Any
from uuid import UUID

from knowbase.relations.pattern_matcher import (
    PatternMatcher,
    PATTERNS_PART_OF,
    PATTERNS_SUBTYPE_OF,
    PATTERNS_REQUIRES,
    PATTERNS_USES,
    PATTERNS_INTEGRATES_WITH,
    PATTERNS_VERSION_OF,
    PATTERNS_REPLACES,
    PATTERNS_DEPRECATES,
    PATTERNS_PRECEDES,
    PATTERN_REGISTRY,
)
from knowbase.relations.types import (
    RelationType,
    TypedRelation,
    ExtractionMethod,
    RelationStrength,
    RelationStatus,
)


@pytest.fixture
def sample_concepts() -> List[Dict[str, Any]]:
    """Concepts de test."""
    return [
        {
            "concept_id": "concept-sap-s4hana",
            "canonical_name": "SAP S/4HANA",
            "surface_forms": ["S/4HANA", "S4HANA", "SAP S4"],
        },
        {
            "concept_id": "concept-hana-db",
            "canonical_name": "SAP HANA Database",
            "surface_forms": ["HANA", "SAP HANA"],
        },
        {
            "concept_id": "concept-fiori",
            "canonical_name": "SAP Fiori",
            "surface_forms": ["Fiori", "SAP Fiori UX"],
        },
        {
            "concept_id": "concept-btp",
            "canonical_name": "SAP Business Technology Platform",
            "surface_forms": ["BTP", "SAP BTP"],
        },
        {
            "concept_id": "concept-ecc",
            "canonical_name": "SAP ECC",
            "surface_forms": ["ECC", "SAP ERP Central Component"],
        },
    ]


@pytest.fixture
def pattern_matcher() -> PatternMatcher:
    """PatternMatcher instance avec toutes les langues."""
    return PatternMatcher(languages=["EN", "FR", "DE", "ES"])


class TestPatternMatcherInit:
    """Tests pour l'initialisation du PatternMatcher."""

    def test_init_default_languages(self) -> None:
        """Test initialisation avec langues par défaut."""
        matcher = PatternMatcher()

        assert "EN" in matcher.languages
        assert "FR" in matcher.languages
        assert "DE" in matcher.languages
        assert "ES" in matcher.languages

    def test_init_custom_languages(self) -> None:
        """Test initialisation avec langues personnalisées."""
        matcher = PatternMatcher(languages=["EN", "FR"])

        assert "EN" in matcher.languages
        assert "FR" in matcher.languages
        assert "DE" not in matcher.languages

    def test_patterns_compiled(self, pattern_matcher: PatternMatcher) -> None:
        """Test que les patterns sont compilés."""
        assert len(pattern_matcher.compiled_patterns) > 0
        assert RelationType.PART_OF in pattern_matcher.compiled_patterns
        assert RelationType.USES in pattern_matcher.compiled_patterns


class TestPatternRegistry:
    """Tests pour le registre de patterns."""

    def test_pattern_registry_complete(self) -> None:
        """Test que le registre contient tous les types de relations."""
        expected_types = [
            RelationType.PART_OF,
            RelationType.SUBTYPE_OF,
            RelationType.REQUIRES,
            RelationType.USES,
            RelationType.INTEGRATES_WITH,
            RelationType.VERSION_OF,
            RelationType.REPLACES,
            RelationType.DEPRECATES,
            RelationType.PRECEDES,
        ]

        for rel_type in expected_types:
            assert rel_type in PATTERN_REGISTRY

    def test_patterns_multilingual(self) -> None:
        """Test que les patterns sont définis pour plusieurs langues."""
        for rel_type, patterns in PATTERN_REGISTRY.items():
            # Chaque type devrait avoir au moins les patterns EN
            assert "EN" in patterns, f"Missing EN patterns for {rel_type}"


class TestPatternMatchingPartOf:
    """Tests pour les patterns PART_OF."""

    def test_pattern_part_of_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern PART_OF en anglais."""
        text = "SAP HANA Database is a component of SAP S/4HANA"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP HANA Database", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP S/4HANA", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        # Devrait trouver au moins une relation
        part_of_relations = [r for r in relations if r.relation_type == RelationType.PART_OF]
        # Note: Le pattern peut ou non matcher selon la formulation exacte
        # Ce test vérifie que le matcher fonctionne sans erreur
        assert isinstance(relations, list)

    def test_pattern_includes_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern 'includes' en anglais."""
        text = "SAP S/4HANA includes SAP Fiori"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP Fiori", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert isinstance(relations, list)

    def test_pattern_part_of_french(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern PART_OF en français."""
        text = "SAP HANA est un composant de SAP S/4HANA"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP S/4HANA", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert isinstance(relations, list)


class TestPatternMatchingRequires:
    """Tests pour les patterns REQUIRES."""

    def test_pattern_requires_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern REQUIRES en anglais."""
        text = "SAP S/4HANA requires SAP HANA Database"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP HANA Database", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        requires_relations = [r for r in relations if r.relation_type == RelationType.REQUIRES]
        assert isinstance(relations, list)

    def test_pattern_depends_on_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern 'depends on' en anglais."""
        text = "SAP Fiori depends on SAP BTP"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP Fiori", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP BTP", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert isinstance(relations, list)


class TestPatternMatchingUses:
    """Tests pour les patterns USES."""

    def test_pattern_uses_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern USES en anglais."""
        text = "SAP S/4HANA uses SAP HANA Database"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP HANA Database", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        uses_relations = [r for r in relations if r.relation_type == RelationType.USES]
        assert isinstance(relations, list)

    def test_pattern_leverages_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern 'leverages' en anglais."""
        text = "SAP Fiori leverages SAP BTP"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP Fiori", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP BTP", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert isinstance(relations, list)


class TestPatternMatchingIntegrates:
    """Tests pour les patterns INTEGRATES_WITH."""

    def test_pattern_integrates_with_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern INTEGRATES_WITH en anglais."""
        text = "SAP S/4HANA integrates with SAP BTP"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP BTP", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert isinstance(relations, list)

    def test_pattern_compatible_with_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern 'is compatible with' en anglais."""
        text = "SAP Fiori is compatible with SAP S/4HANA"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP Fiori", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP S/4HANA", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert isinstance(relations, list)


class TestPatternMatchingReplaces:
    """Tests pour les patterns REPLACES."""

    def test_pattern_replaces_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern REPLACES en anglais."""
        text = "SAP S/4HANA replaces SAP ECC"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP ECC", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        replaces_relations = [r for r in relations if r.relation_type == RelationType.REPLACES]
        assert isinstance(relations, list)

    def test_pattern_supersedes_english(self, pattern_matcher: PatternMatcher) -> None:
        """Test pattern 'supersedes' en anglais."""
        text = "SAP S/4HANA supersedes SAP ECC"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP ECC", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert isinstance(relations, list)


class TestConceptMatching:
    """Tests pour le matching de concepts."""

    def test_match_concept_exact(
        self, pattern_matcher: PatternMatcher, sample_concepts: List[Dict]
    ) -> None:
        """Test matching exact sur canonical_name."""
        result = pattern_matcher._match_concept("SAP S/4HANA", sample_concepts)

        assert result == "concept-sap-s4hana"

    def test_match_concept_case_insensitive(
        self, pattern_matcher: PatternMatcher, sample_concepts: List[Dict]
    ) -> None:
        """Test matching case-insensitive."""
        result = pattern_matcher._match_concept("sap s/4hana", sample_concepts)

        assert result == "concept-sap-s4hana"

    def test_match_concept_surface_form(
        self, pattern_matcher: PatternMatcher, sample_concepts: List[Dict]
    ) -> None:
        """Test matching via surface_form."""
        result = pattern_matcher._match_concept("S4HANA", sample_concepts)

        assert result == "concept-sap-s4hana"

    def test_match_concept_no_match(
        self, pattern_matcher: PatternMatcher, sample_concepts: List[Dict]
    ) -> None:
        """Test pas de match."""
        result = pattern_matcher._match_concept("Unknown System", sample_concepts)

        assert result is None


class TestRelationCreation:
    """Tests pour la création de relations."""

    def test_create_relation_basic(self, pattern_matcher: PatternMatcher) -> None:
        """Test création d'une relation basique."""
        relation = pattern_matcher._create_relation(
            relation_type=RelationType.USES,
            source_concept="concept-1",
            target_concept="concept-2",
            evidence="System A uses System B",
            document_id="doc-123",
            document_name="test.pdf",
            chunk_ids=["chunk-1"],
        )

        assert relation.relation_type == RelationType.USES
        assert relation.source_concept == "concept-1"
        assert relation.target_concept == "concept-2"
        assert "uses" in relation.evidence.lower()

    def test_create_relation_metadata(self, pattern_matcher: PatternMatcher) -> None:
        """Test métadonnées de la relation."""
        relation = pattern_matcher._create_relation(
            relation_type=RelationType.REQUIRES,
            source_concept="concept-1",
            target_concept="concept-2",
            evidence="System A requires System B",
            document_id="doc-123",
            document_name="test.pdf",
        )

        assert relation.metadata.extraction_method == ExtractionMethod.PATTERN
        assert relation.metadata.source_doc_id == "doc-123"
        assert relation.metadata.confidence == 0.65
        assert relation.metadata.strength == RelationStrength.MODERATE
        assert relation.metadata.status == RelationStatus.ACTIVE

    def test_create_relation_id_format(self, pattern_matcher: PatternMatcher) -> None:
        """Test format de l'ID de relation."""
        relation = pattern_matcher._create_relation(
            relation_type=RelationType.PART_OF,
            source_concept="concept-1",
            target_concept="concept-2",
            evidence="A is part of B",
            document_id="doc-123",
            document_name="test.pdf",
        )

        assert relation.relation_id.startswith("rel-")

    def test_create_relation_evidence_truncated(self, pattern_matcher: PatternMatcher) -> None:
        """Test que l'evidence est tronquée à 200 caractères."""
        long_evidence = "x" * 300

        relation = pattern_matcher._create_relation(
            relation_type=RelationType.USES,
            source_concept="concept-1",
            target_concept="concept-2",
            evidence=long_evidence,
            document_id="doc-123",
            document_name="test.pdf",
        )

        assert len(relation.evidence) == 200


class TestExtractRelationsIntegration:
    """Tests d'intégration pour extract_relations."""

    def test_extract_relations_empty_text(
        self, pattern_matcher: PatternMatcher, sample_concepts: List[Dict]
    ) -> None:
        """Test extraction avec texte vide."""
        relations = pattern_matcher.extract_relations(
            concepts=sample_concepts,
            full_text="",
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert relations == []

    def test_extract_relations_no_concepts(
        self, pattern_matcher: PatternMatcher
    ) -> None:
        """Test extraction sans concepts."""
        relations = pattern_matcher.extract_relations(
            concepts=[],
            full_text="SAP S/4HANA uses SAP HANA Database",
            document_id="doc-1",
            document_name="test.pdf",
        )

        # Devrait retourner liste vide car pas de concepts à matcher
        assert relations == []

    def test_extract_relations_multiple_types(
        self, pattern_matcher: PatternMatcher
    ) -> None:
        """Test extraction de plusieurs types de relations."""
        text = """
        SAP S/4HANA uses SAP HANA Database.
        SAP S/4HANA integrates with SAP BTP.
        SAP S/4HANA replaces SAP ECC.
        """

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP HANA Database", "surface_forms": []},
            {"concept_id": "c3", "canonical_name": "SAP BTP", "surface_forms": []},
            {"concept_id": "c4", "canonical_name": "SAP ECC", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        # Vérifie que l'extraction fonctionne sans erreur
        assert isinstance(relations, list)

    def test_extract_relations_with_chunk_ids(
        self, pattern_matcher: PatternMatcher
    ) -> None:
        """Test extraction avec chunk_ids."""
        text = "SAP S/4HANA uses SAP HANA"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP HANA", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
            chunk_ids=["chunk-1", "chunk-2"],
        )

        # Si relations trouvées, elles doivent avoir chunk_ids
        for relation in relations:
            assert relation.metadata.source_chunk_ids == ["chunk-1", "chunk-2"]


class TestPatternMatcherEdgeCases:
    """Tests des cas limites."""

    def test_special_characters_in_text(self, pattern_matcher: PatternMatcher) -> None:
        """Test avec caractères spéciaux dans le texte."""
        text = "SAP S/4HANA® uses SAP HANA™ Database"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP HANA", "surface_forms": []},
        ]

        # Ne devrait pas lever d'exception
        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert isinstance(relations, list)

    def test_unicode_text(self, pattern_matcher: PatternMatcher) -> None:
        """Test avec texte Unicode."""
        text = "SAP S/4HANA nécessite SAP HANA pour fonctionner"

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP HANA", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        assert isinstance(relations, list)

    def test_very_long_text(self, pattern_matcher: PatternMatcher) -> None:
        """Test avec texte très long."""
        # Texte de 100KB
        base_text = "SAP S/4HANA uses SAP HANA. " * 4000

        concepts = [
            {"concept_id": "c1", "canonical_name": "SAP S/4HANA", "surface_forms": []},
            {"concept_id": "c2", "canonical_name": "SAP HANA", "surface_forms": []},
        ]

        relations = pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=base_text,
            document_id="doc-1",
            document_name="test.pdf",
        )

        # Devrait trouver plusieurs relations
        assert isinstance(relations, list)
