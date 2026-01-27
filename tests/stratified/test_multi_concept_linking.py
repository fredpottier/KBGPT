"""
Tests unitaires pour Multi-Concept Linking (V2.1)
=================================================
Ref: doc/ongoing/PLAN_CAPTATION_V2.md

Teste:
- MultiConceptLink dataclass
- _filter_multi_links (C3: Anti "Spray & Pray")
- _has_trigger_match (C1c: Word boundary vs substring)
"""

import pytest
from unittest.mock import MagicMock

from knowbase.stratified.pass1.assertion_extractor import (
    AssertionExtractorV2,
    MultiConceptLink,
    ConceptLink,
    MIN_LINK_CONFIDENCE,
    MAX_LINKS_PER_ASSERTION,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def extractor():
    """AssertionExtractorV2 sans LLM."""
    return AssertionExtractorV2(llm_client=None, allow_fallback=True)


# ============================================================================
# TEST: MultiConceptLink
# ============================================================================

class TestMultiConceptLink:
    """Tests pour MultiConceptLink dataclass."""

    def test_basic_creation(self):
        """Test de création basique."""
        link = MultiConceptLink(
            assertion_id="a1",
            concept_ids=["c1", "c2", "c3"],
            link_types={"c1": "defines", "c2": "describes", "c3": "constrains"},
            justifications={"c1": "J1", "c2": "J2", "c3": "J3"},
            confidences={"c1": 0.9, "c2": 0.8, "c3": 0.7}
        )

        assert link.assertion_id == "a1"
        assert len(link.concept_ids) == 3
        assert link.confidences["c1"] == 0.9

    def test_primary_concept_id(self):
        """Test du concept principal (plus haute confiance)."""
        link = MultiConceptLink(
            assertion_id="a1",
            concept_ids=["c1", "c2", "c3"],
            link_types={"c1": "defines", "c2": "describes", "c3": "constrains"},
            justifications={},
            confidences={"c1": 0.7, "c2": 0.95, "c3": 0.8}  # c2 a la plus haute
        )

        assert link.primary_concept_id == "c2"

    def test_to_legacy_links(self):
        """Test de conversion en ConceptLink legacy."""
        multi = MultiConceptLink(
            assertion_id="a1",
            concept_ids=["c1", "c2"],
            link_types={"c1": "defines", "c2": "describes"},
            justifications={"c1": "J1", "c2": "J2"},
            confidences={"c1": 0.9, "c2": 0.8}
        )

        legacy = multi.to_legacy_links()

        assert len(legacy) == 2
        assert all(isinstance(l, ConceptLink) for l in legacy)
        assert legacy[0].assertion_id == "a1"
        assert legacy[0].concept_id == "c1"
        assert legacy[0].link_type == "defines"


# ============================================================================
# TEST: _filter_multi_links (C3)
# ============================================================================

class TestFilterMultiLinks:
    """Tests pour _filter_multi_links (C3: Anti Spray & Pray)."""

    def test_high_confidence_links_kept(self, extractor):
        """C3: Liens avec haute confiance gardés."""
        raw_links = [
            {"concept_id": "c1", "link_type": "defines", "confidence": 0.9},
            {"concept_id": "c2", "link_type": "describes", "confidence": 0.85},
            {"concept_id": "c3", "link_type": "constrains", "confidence": 0.75},
        ]
        valid_ids = {"c1", "c2", "c3"}
        triggers = {"c1": [], "c2": [], "c3": []}  # Pas de triggers = accepter

        filtered = extractor._filter_multi_links(
            raw_links, "Some text", valid_ids, triggers
        )

        assert len(filtered) == 3

    def test_low_confidence_links_filtered(self, extractor):
        """C3: Liens avec basse confiance filtrés."""
        raw_links = [
            {"concept_id": "c1", "link_type": "defines", "confidence": 0.9},
            {"concept_id": "c2", "link_type": "describes", "confidence": 0.5},  # < 0.70
            {"concept_id": "c3", "link_type": "constrains", "confidence": 0.3},  # < 0.70
        ]
        valid_ids = {"c1", "c2", "c3"}
        triggers = {}

        filtered = extractor._filter_multi_links(
            raw_links, "Some text", valid_ids, triggers
        )

        # Seul c1 a confiance >= 0.70
        # c2 est gardé car top-2 avec écart <= 0.10 ? Non, 0.9-0.5 = 0.4 > 0.10
        assert len(filtered) == 1
        assert filtered[0]["concept_id"] == "c1"

    def test_top_k_close_kept(self, extractor):
        """C3: Top-k gardés si écart faible."""
        raw_links = [
            {"concept_id": "c1", "link_type": "defines", "confidence": 0.85},
            {"concept_id": "c2", "link_type": "describes", "confidence": 0.80},  # Écart 0.05 <= 0.10
            {"concept_id": "c3", "link_type": "constrains", "confidence": 0.5},  # Écart 0.35 > 0.10
        ]
        valid_ids = {"c1", "c2", "c3"}
        triggers = {}

        filtered = extractor._filter_multi_links(
            raw_links, "Some text", valid_ids, triggers
        )

        # c1 et c2 gardés (top-2 avec écart faible), c3 rejeté
        assert len(filtered) == 2

    def test_max_links_limit(self, extractor):
        """C3: Maximum 5 liens par assertion."""
        raw_links = [
            {"concept_id": f"c{i}", "link_type": "describes", "confidence": 0.9 - i * 0.01}
            for i in range(10)
        ]
        valid_ids = {f"c{i}" for i in range(10)}
        triggers = {}

        filtered = extractor._filter_multi_links(
            raw_links, "Some text", valid_ids, triggers
        )

        assert len(filtered) <= MAX_LINKS_PER_ASSERTION

    def test_trigger_validation(self, extractor):
        """C3: Liens validés par trigger."""
        raw_links = [
            {"concept_id": "c1", "link_type": "defines", "confidence": 0.9},
            {"concept_id": "c2", "link_type": "describes", "confidence": 0.85},
        ]
        valid_ids = {"c1", "c2"}
        triggers = {
            "c1": ["TLS", "encryption"],  # Présents dans le texte
            "c2": ["absent", "nowhere"],  # Absents du texte
        }

        filtered = extractor._filter_multi_links(
            raw_links, "TLS encryption is required", valid_ids, triggers
        )

        # Seul c1 a un trigger présent
        assert len(filtered) == 1
        assert filtered[0]["concept_id"] == "c1"

    def test_invalid_concept_ids_filtered(self, extractor):
        """C3: Concept IDs invalides filtrés."""
        raw_links = [
            {"concept_id": "valid", "link_type": "defines", "confidence": 0.9},
            {"concept_id": "invalid", "link_type": "describes", "confidence": 0.9},
        ]
        valid_ids = {"valid"}
        triggers = {}

        filtered = extractor._filter_multi_links(
            raw_links, "Some text", valid_ids, triggers
        )

        assert len(filtered) == 1
        assert filtered[0]["concept_id"] == "valid"


# ============================================================================
# TEST: _has_trigger_match (C1c)
# ============================================================================

class TestHasTriggerMatch:
    """Tests pour _has_trigger_match (C1c: Word boundary)."""

    def test_word_boundary_match(self, extractor):
        """C1c: Match avec word boundary pour mots normaux."""
        text = "TLS encryption is required"

        assert extractor._has_trigger_match(text, ["TLS"]) is True
        assert extractor._has_trigger_match(text, ["encryption"]) is True
        assert extractor._has_trigger_match(text, ["required"]) is True

    def test_word_boundary_no_partial_match(self, extractor):
        """C1c: Pas de match partiel (cat dans category)."""
        text = "The category includes various items"

        # "cat" ne devrait PAS matcher dans "category"
        assert extractor._has_trigger_match(text, ["cat"]) is False

    def test_value_substring_match(self, extractor):
        """C1c: Match substring pour valeurs."""
        text = "Version 1.2 is required with 99.9% uptime"

        # Les valeurs peuvent matcher en substring
        assert extractor._has_trigger_match(text, ["1.2"]) is True
        assert extractor._has_trigger_match(text, ["99.9%"]) is True

    def test_case_insensitive(self, extractor):
        """C1c: Match case-insensitive."""
        text = "TLS Encryption is REQUIRED"

        assert extractor._has_trigger_match(text, ["tls"]) is True
        assert extractor._has_trigger_match(text, ["ENCRYPTION"]) is True
        assert extractor._has_trigger_match(text, ["Required"]) is True

    def test_empty_triggers(self, extractor):
        """C1c: Pas de triggers = accepter (rétrocompatibilité)."""
        assert extractor._has_trigger_match("Any text", []) is True

    def test_no_match(self, extractor):
        """C1c: Aucun trigger ne matche."""
        text = "The system provides features"

        assert extractor._has_trigger_match(text, ["absent", "missing"]) is False


# ============================================================================
# TEST: Integration - parse multi-concept response
# ============================================================================

class TestParseMultiConceptResponse:
    """Tests d'intégration pour le parsing multi-concept."""

    def test_parse_multi_concept_format(self, extractor):
        """Test du parsing du nouveau format multi-concept."""
        from knowbase.stratified.pass1.assertion_extractor import RawAssertion
        from knowbase.stratified.models import Concept, ConceptRole

        # Préparer les données
        assertions = [
            RawAssertion(
                assertion_id="a1",
                text="S/4HANA requires ABAP and JavaScript skills",
                assertion_type=MagicMock(),
                chunk_id="chunk1",
                start_char=0,
                end_char=50,
                confidence=0.9
            )
        ]
        concepts = [
            Concept(
                concept_id="c1",
                theme_id="t1",
                name="S/4HANA Migration",
                role=ConceptRole.CENTRAL,
                lexical_triggers=["S/4HANA", "migration"]
            ),
            Concept(
                concept_id="c2",
                theme_id="t1",
                name="ABAP Skills",
                role=ConceptRole.STANDARD,
                lexical_triggers=["ABAP", "skills"]
            ),
        ]

        # Response JSON avec format multi-concept
        response = '''```json
{
    "links": [
        {
            "assertion_id": "a1",
            "concept_links": [
                {"concept_id": "c1", "link_type": "describes", "justification": "J1", "confidence": 0.9},
                {"concept_id": "c2", "link_type": "describes", "justification": "J2", "confidence": 0.85}
            ]
        }
    ],
    "unlinked_assertions": []
}
```'''

        links = extractor._parse_links_response(response, assertions, concepts)

        # Devrait retourner 2 ConceptLink (un par concept)
        assert len(links) == 2
        assert links[0].concept_id in ["c1", "c2"]
        assert links[1].concept_id in ["c1", "c2"]
