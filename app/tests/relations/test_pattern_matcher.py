# Tests Phase 2 OSMOSE - PatternMatcher

import pytest
from knowbase.relations.pattern_matcher import PatternMatcher
from knowbase.relations.types import RelationType


class TestPatternMatcher:
    """Tests extraction pattern-based de relations."""

    @pytest.fixture
    def pattern_matcher(self):
        """Fixture PatternMatcher."""
        return PatternMatcher(languages=["EN", "FR"])

    @pytest.fixture
    def sample_concepts(self):
        """Concepts de test."""
        return [
            {
                "concept_id": "concept-sap-s4hana",
                "canonical_name": "SAP S/4HANA",
                "surface_forms": ["S/4HANA", "S4HANA"],
                "concept_type": "PRODUCT"
            },
            {
                "concept_id": "concept-sap-fiori",
                "canonical_name": "SAP Fiori",
                "surface_forms": ["Fiori"],
                "concept_type": "PRODUCT"
            },
            {
                "concept_id": "concept-sap-hana",
                "canonical_name": "SAP HANA",
                "surface_forms": ["HANA"],
                "concept_type": "PRODUCT"
            },
        ]

    def test_init(self, pattern_matcher):
        """Test initialisation PatternMatcher."""
        assert pattern_matcher is not None
        assert "EN" in pattern_matcher.languages
        assert "FR" in pattern_matcher.languages
        assert len(pattern_matcher.compiled_patterns) > 0

    def test_extract_part_of_en(self, pattern_matcher, sample_concepts):
        """Test extraction PART_OF (EN)."""
        text = "SAP Fiori is a component of SAP S/4HANA."

        relations = pattern_matcher.extract_relations(
            concepts=sample_concepts,
            full_text=text,
            document_id="test-doc-1",
            document_name="test.pdf"
        )

        # Devrait extraire 1 relation PART_OF
        assert len(relations) > 0

        part_of_relations = [r for r in relations if r.relation_type == RelationType.PART_OF]
        assert len(part_of_relations) >= 1

        rel = part_of_relations[0]
        assert rel.source_concept == "concept-sap-fiori"
        assert rel.target_concept == "concept-sap-s4hana"
        assert rel.metadata.confidence > 0.5
        assert "Fiori" in rel.evidence or "component" in rel.evidence

    def test_extract_requires_en(self, pattern_matcher, sample_concepts):
        """Test extraction REQUIRES (EN)."""
        text = "SAP S/4HANA requires SAP HANA as the underlying database."

        relations = pattern_matcher.extract_relations(
            concepts=sample_concepts,
            full_text=text,
            document_id="test-doc-2",
            document_name="test.pdf"
        )

        # Devrait extraire 1 relation REQUIRES
        requires_relations = [r for r in relations if r.relation_type == RelationType.REQUIRES]
        assert len(requires_relations) >= 1

        rel = requires_relations[0]
        assert rel.source_concept == "concept-sap-s4hana"
        assert rel.target_concept == "concept-sap-hana"

    def test_extract_part_of_fr(self, pattern_matcher, sample_concepts):
        """Test extraction PART_OF (FR)."""
        text = "SAP Fiori est un composant de SAP S/4HANA."

        relations = pattern_matcher.extract_relations(
            concepts=sample_concepts,
            full_text=text,
            document_id="test-doc-3",
            document_name="test.pdf"
        )

        # Devrait extraire 1 relation PART_OF
        part_of_relations = [r for r in relations if r.relation_type == RelationType.PART_OF]
        assert len(part_of_relations) >= 1

    def test_no_extraction_unknown_concepts(self, pattern_matcher):
        """Test: pas d'extraction si concepts inconnus."""
        text = "Product A is part of Product B."

        relations = pattern_matcher.extract_relations(
            concepts=[],  # Pas de concepts connus
            full_text=text,
            document_id="test-doc-4",
            document_name="test.pdf"
        )

        # Ne devrait extraire aucune relation (concepts inconnus)
        assert len(relations) == 0

    def test_extract_multiple_relations(self, pattern_matcher, sample_concepts):
        """Test extraction de plusieurs relations dans un texte."""
        text = """
        SAP S/4HANA is an ERP system that requires SAP HANA database.
        SAP Fiori is a component of SAP S/4HANA and provides the user interface.
        """

        relations = pattern_matcher.extract_relations(
            concepts=sample_concepts,
            full_text=text,
            document_id="test-doc-5",
            document_name="test.pdf"
        )

        # Devrait extraire au moins 2 relations (REQUIRES + PART_OF)
        assert len(relations) >= 2

        relation_types = set(r.relation_type for r in relations)
        assert RelationType.PART_OF in relation_types or RelationType.REQUIRES in relation_types
