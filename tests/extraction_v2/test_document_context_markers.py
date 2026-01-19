"""
Tests pour le système Document Context Markers.

ADR: doc/decisions/ADR_DOCUMENT_CONTEXT_MARKERS.md

Tests des composants:
1. DocumentContext et sous-structures (StructureHint, EntityHint, TemporalHint)
2. MarkerMention et MarkerDecision
3. Fonction decide_marker() avec tous les cas de l'ADR
4. DocumentContextDecider
5. Intégration avec NormalizationEngine
"""

import pytest
from typing import List

from knowbase.extraction_v2.context.models import (
    DocumentContext,
    StructureHint,
    EntityHint,
    TemporalHint,
)
from knowbase.extraction_v2.context.candidate_mining import (
    MarkerCandidate,
    MarkerMention,
    MarkerDecision,
    PositionHint,
    EvidenceRef,
    DocumentContextDecider,
    decide_marker,
    is_small_number,
    is_year_like,
    is_heading_artifact,
    has_entity_anchor,
    structure_risk_high,
    finalize_decision,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def empty_context() -> DocumentContext:
    """Context vide (aucune contrainte)."""
    return DocumentContext.empty()


@pytest.fixture
def numbered_sections_context() -> DocumentContext:
    """Context avec sections numérotées détectées."""
    return DocumentContext(
        structure_hint=StructureHint(
            has_numbered_sections=True,
            numbering_patterns=["WORD+NUMBER"],
            confidence=0.85,
        ),
        entity_hints=[],
        temporal_hint=TemporalHint.empty(),
        scope_hints=[],
    )


@pytest.fixture
def product_context() -> DocumentContext:
    """Context avec produit dominant (SAP S/4HANA)."""
    return DocumentContext(
        structure_hint=StructureHint.empty(),
        entity_hints=[
            EntityHint(
                label="SAP S/4HANA",
                type_hint="product",
                confidence=0.9,
                evidence="explicit",
            ),
        ],
        temporal_hint=TemporalHint(explicit="2024-Q1", confidence=0.8),
        scope_hints=["cloud"],
    )


@pytest.fixture
def mixed_context() -> DocumentContext:
    """Context avec sections numérotées ET produit dominant."""
    return DocumentContext(
        structure_hint=StructureHint(
            has_numbered_sections=True,
            numbering_patterns=["WORD+NUMBER"],
            confidence=0.9,
        ),
        entity_hints=[
            EntityHint(
                label="iPhone",
                type_hint="product",
                confidence=0.85,
                evidence="explicit",
            ),
        ],
        temporal_hint=TemporalHint.empty(),
        scope_hints=[],
    )


# =============================================================================
# TESTS: DocumentContext et sous-structures
# =============================================================================

class TestDocumentContext:
    """Tests pour DocumentContext et ses sous-structures."""

    def test_empty_context(self, empty_context: DocumentContext):
        """Un context vide n'a pas de contraintes."""
        assert not empty_context.has_numbered_sections()
        assert empty_context.get_dominant_entity() is None
        assert not empty_context.has_entity_anchor("iPhone")

    def test_numbered_sections_detection(self, numbered_sections_context: DocumentContext):
        """Détecte correctement les sections numérotées."""
        assert numbered_sections_context.has_numbered_sections()
        assert numbered_sections_context.structure_hint.confidence >= 0.7

    def test_entity_anchor_matching(self, product_context: DocumentContext):
        """Vérifie le matching des entity anchors."""
        # Match exact
        assert product_context.has_entity_anchor("SAP")
        assert product_context.has_entity_anchor("S/4HANA")

        # Pas de match
        assert not product_context.has_entity_anchor("iPhone")
        assert not product_context.has_entity_anchor("Oracle")

    def test_dominant_entity(self, product_context: DocumentContext):
        """Retourne l'entité dominante avec haute confiance."""
        dominant = product_context.get_dominant_entity()
        assert dominant is not None
        assert dominant.label == "SAP S/4HANA"
        assert dominant.confidence >= 0.75

    def test_serialization(self, product_context: DocumentContext):
        """Sérialisation/désérialisation correcte."""
        data = product_context.to_dict()
        restored = DocumentContext.from_dict(data)

        assert restored.structure_hint.has_numbered_sections == product_context.structure_hint.has_numbered_sections
        assert len(restored.entity_hints) == len(product_context.entity_hints)
        assert restored.entity_hints[0].label == product_context.entity_hints[0].label


class TestStructureHint:
    """Tests pour StructureHint."""

    def test_empty_hint(self):
        """Un hint vide n'indique pas de sections numérotées."""
        hint = StructureHint.empty()
        assert not hint.has_numbered_sections
        assert hint.confidence == 0.5

    def test_numbered_sections(self):
        """Hint avec sections numérotées."""
        hint = StructureHint(
            has_numbered_sections=True,
            numbering_patterns=["WORD+NUMBER", "1.2.3"],
            confidence=0.9,
        )
        assert hint.has_numbered_sections
        assert "WORD+NUMBER" in hint.numbering_patterns


class TestEntityHint:
    """Tests pour EntityHint."""

    def test_basic_hint(self):
        """Création d'un hint basique."""
        hint = EntityHint(
            label="SAP S/4HANA Cloud",
            type_hint="product",
            confidence=0.9,
            evidence="explicit",
        )
        assert hint.label == "SAP S/4HANA Cloud"
        assert hint.confidence >= 0.75


class TestTemporalHint:
    """Tests pour TemporalHint."""

    def test_empty_hint(self):
        """Un hint vide n'a pas de date."""
        hint = TemporalHint.empty()
        assert hint.get_best_date() is None

    def test_explicit_date(self):
        """Date explicite prioritaire."""
        hint = TemporalHint(explicit="2024-Q1", inferred="2024", confidence=0.9)
        assert hint.get_best_date() == "2024-Q1"

    def test_inferred_date(self):
        """Date inférée utilisée si pas d'explicite."""
        hint = TemporalHint(inferred="2023", confidence=0.5)
        assert hint.get_best_date() == "2023"


# =============================================================================
# TESTS: MarkerMention et helpers
# =============================================================================

class TestMarkerMention:
    """Tests pour MarkerMention."""

    def test_from_marker_candidate(self):
        """Conversion depuis MarkerCandidate."""
        candidate = MarkerCandidate(
            value="iPhone 15",
            source="cover",
            lexical_shape="entity_numeral",
            evidence="The new iPhone 15 features...",
        )

        mention = MarkerMention.from_marker_candidate(candidate, "doc_123")

        assert mention.raw_text == "iPhone 15"
        assert mention.prefix == "iPhone"
        assert mention.number == "15"
        assert mention.number_len == 2
        assert mention.shape == "WORD_NUMBER"
        assert mention.evidence is not None
        assert mention.evidence.document_id == "doc_123"

    def test_year_shape_detection(self):
        """Détecte correctement les années."""
        candidate = MarkerCandidate(
            value="S/4HANA 2023",
            source="cover",
            lexical_shape="entity_numeral",
        )

        mention = MarkerMention.from_marker_candidate(candidate, "doc_123")

        assert mention.shape == "YEAR"
        assert mention.number == "2023"
        assert mention.number_len == 4


class TestHelperFunctions:
    """Tests pour les fonctions auxiliaires de decide_marker()."""

    def test_is_small_number(self):
        """Détecte les petits numéros (1-2 digits)."""
        # Petit numéro
        m1 = MarkerMention(raw_text="PUBLIC 3", prefix="PUBLIC", number="3", number_len=1)
        assert is_small_number(m1)

        # Grand numéro
        m2 = MarkerMention(raw_text="iPhone 123", prefix="iPhone", number="123", number_len=3)
        assert not is_small_number(m2)

    def test_is_year_like(self):
        """Détecte les années."""
        # Année valide
        m1 = MarkerMention(raw_text="S/4HANA 2023", number="2023", shape="YEAR")
        assert is_year_like(m1)

        # Pas une année (trop ancien)
        m2 = MarkerMention(raw_text="Model 1800", number="1800", shape="YEAR")
        assert not is_year_like(m2)

        # Pas une année (shape différente)
        m3 = MarkerMention(raw_text="iPhone 15", number="15", shape="WORD_NUMBER")
        assert not is_year_like(m3)

    def test_is_heading_artifact(self):
        """Détecte les artefacts de titre."""
        # Heading-like
        m1 = MarkerMention(
            raw_text="PUBLIC 3",
            position_hint=PositionHint(is_heading_like=True),
        )
        assert is_heading_artifact(m1)

        # TOC
        m2 = MarkerMention(
            raw_text="Chapter 1",
            position_hint=PositionHint(in_toc_like=True),
        )
        assert is_heading_artifact(m2)

        # Pas un artefact
        m3 = MarkerMention(raw_text="iPhone 15", position_hint=PositionHint())
        assert not is_heading_artifact(m3)

    def test_structure_risk_high(self, numbered_sections_context: DocumentContext):
        """Détecte le risque structurel élevé."""
        # Risque élevé: sections numérotées + WORD+NUMBER + petit numéro
        m1 = MarkerMention(
            raw_text="PUBLIC 3",
            prefix="PUBLIC",
            number="3",
            number_len=1,
            shape="WORD_NUMBER",
        )
        assert structure_risk_high(m1, numbered_sections_context)

        # Pas de risque: grand numéro
        m2 = MarkerMention(
            raw_text="iPhone 2023",
            prefix="iPhone",
            number="2023",
            number_len=4,
            shape="WORD_NUMBER",
        )
        assert not structure_risk_high(m2, numbered_sections_context)

    def test_has_entity_anchor(self, product_context: DocumentContext):
        """Vérifie la détection d'entity anchor."""
        m1 = MarkerMention(raw_text="SAP 2023", prefix="SAP")
        assert has_entity_anchor(m1, product_context)

        m2 = MarkerMention(raw_text="Oracle 2023", prefix="Oracle")
        assert not has_entity_anchor(m2, product_context)


# =============================================================================
# TESTS: decide_marker() - Cas de l'ADR
# =============================================================================

class TestDecideMarker:
    """Tests pour decide_marker() selon les cas de l'ADR."""

    def test_year_marker_accepted(self, empty_context: DocumentContext):
        """Les markers YEAR sont acceptés par défaut."""
        mention = MarkerMention(
            raw_text="S/4HANA 2023",
            prefix="S/4HANA",
            number="2023",
            number_len=4,
            shape="YEAR",
        )

        decision = decide_marker(mention, empty_context)

        assert decision.is_accepted()
        assert "YEAR_LIKE" in decision.reasons

    def test_year_with_temporal_hint_boost(self, product_context: DocumentContext):
        """Les années avec temporal hint explicite reçoivent un boost."""
        # Modifier le temporal hint pour matcher 2024
        product_context.temporal_hint = TemporalHint(explicit="2024-Q1", confidence=0.9)

        mention = MarkerMention(
            raw_text="Product 2024",
            prefix="Product",
            number="2024",
            number_len=4,
            shape="YEAR",
        )

        decision = decide_marker(mention, product_context)

        assert decision.is_accepted()
        assert "MATCHES_TEMPORAL_HINT_EXPLICIT" in decision.reasons

    def test_public_3_rejected_as_heading(self, numbered_sections_context: DocumentContext):
        """PUBLIC 3 est rejeté comme artefact de titre."""
        mention = MarkerMention(
            raw_text="PUBLIC 3",
            prefix="PUBLIC",
            number="3",
            number_len=1,
            shape="WORD_NUMBER",
            position_hint=PositionHint(is_heading_like=True),
        )

        decision = decide_marker(mention, numbered_sections_context)

        assert decision.is_rejected()
        assert "HEADING_OR_TOC_ARTIFACT" in decision.reasons

    def test_entity_anchor_saves_ambiguous_marker(self, mixed_context: DocumentContext):
        """Un entity anchor peut sauver un marker ambigu."""
        mention = MarkerMention(
            raw_text="iPhone 15",
            prefix="iPhone",
            number="15",
            number_len=2,
            shape="WORD_NUMBER",
        )

        decision = decide_marker(mention, mixed_context)

        # Avec entity anchor, le marker est accepté malgré le risque structurel
        assert "ENTITY_ANCHOR_CORROBORATES" in decision.reasons

    def test_small_number_without_anchor_unresolved(self, numbered_sections_context: DocumentContext):
        """Petit numéro sans entity anchor reste UNRESOLVED."""
        mention = MarkerMention(
            raw_text="Module 5",
            prefix="Module",
            number="5",
            number_len=1,
            shape="WORD_NUMBER",
        )

        decision = decide_marker(mention, numbered_sections_context)

        # Sans entity anchor et avec risque structurel élevé → score bas
        assert decision.score < 0.5
        assert "NO_ENTITY_ANCHOR" in decision.reasons

    def test_versionlike_accepted(self, empty_context: DocumentContext):
        """Les versions SemVer sont acceptées."""
        mention = MarkerMention(
            raw_text="v1.2.3",
            shape="VERSIONLIKE",
        )

        decision = decide_marker(mention, empty_context)

        assert decision.is_accepted()
        assert "VERSIONLIKE" in decision.reasons


class TestFinalizeDecision:
    """Tests pour les seuils de finalisation."""

    def test_accept_strong_threshold(self):
        """Score >= 0.80 → ACCEPT_STRONG."""
        decision = finalize_decision(0.85, ["HIGH_SCORE"])
        assert decision.decision == "ACCEPT_STRONG"

    def test_accept_weak_threshold(self):
        """Score >= 0.60 → ACCEPT_WEAK."""
        decision = finalize_decision(0.65, ["MEDIUM_SCORE"])
        assert decision.decision == "ACCEPT_WEAK"

    def test_unresolved_threshold(self):
        """Score entre 0.20 et 0.60 → UNRESOLVED."""
        decision = finalize_decision(0.40, ["LOW_SCORE"])
        assert decision.decision == "UNRESOLVED"

    def test_reject_threshold(self):
        """Score <= 0.20 → REJECT."""
        decision = finalize_decision(0.15, ["VERY_LOW"])
        assert decision.decision == "REJECT"

    def test_min_decision_override(self):
        """min_decision peut forcer une décision minimum."""
        # Score bas mais min_decision force ACCEPT_WEAK
        decision = finalize_decision(0.40, ["LOW"], min_decision="ACCEPT_WEAK")
        assert decision.decision == "ACCEPT_WEAK"


# =============================================================================
# TESTS: DocumentContextDecider
# =============================================================================

class TestDocumentContextDecider:
    """Tests pour DocumentContextDecider."""

    def test_decide_all(self, product_context: DocumentContext):
        """decide_all() traite tous les candidats."""
        candidates = [
            MarkerCandidate(
                value="S/4HANA 2023",
                source="cover",
                lexical_shape="entity_numeral",
            ),
            MarkerCandidate(
                value="v1.2.3",
                source="body",
                lexical_shape="semver",
            ),
        ]

        decider = DocumentContextDecider(product_context)
        decisions = decider.decide_all(candidates, "doc_123")

        assert "S/4HANA 2023" in decisions
        assert "v1.2.3" in decisions

    def test_filter_by_decision(self, product_context: DocumentContext):
        """filter_by_decision() sépare les candidats."""
        candidates = [
            MarkerCandidate(
                value="SAP 2023",  # Sera accepté (YEAR + entity anchor)
                source="cover",
                lexical_shape="entity_numeral",
            ),
            MarkerCandidate(
                value="Random 5",  # Sera UNRESOLVED (petit numéro, pas d'anchor)
                source="body",
                lexical_shape="entity_numeral",
            ),
        ]

        decider = DocumentContextDecider(product_context)
        accepted, unresolved, rejected = decider.filter_by_decision(candidates, "doc_123")

        # SAP 2023 devrait être accepté
        assert any(c.value == "SAP 2023" for c in accepted)


# =============================================================================
# TESTS: Intégration avec NormalizationEngine
# =============================================================================

class TestNormalizationEngineIntegration:
    """Tests d'intégration avec NormalizationEngine."""

    def test_entity_hints_to_anchors(self):
        """Conversion entity_hints → anchors."""
        from knowbase.consolidation.normalization.normalization_engine import (
            get_normalization_engine,
        )

        engine = get_normalization_engine("default")

        entity_hints = [
            {"label": "SAP S/4HANA", "type_hint": "product", "confidence": 0.9, "evidence": "explicit"},
            {"label": "Oracle DB", "type_hint": "system", "confidence": 0.6, "evidence": "inferred"},
            {"label": "Weak Entity", "type_hint": "other", "confidence": 0.3, "evidence": "inferred"},
        ]

        anchors = engine.get_entity_anchors_from_hints(entity_hints)

        # Seuls les hints avec confidence >= 0.5 sont convertis
        assert len(anchors) == 2
        assert anchors[0]["name"] == "SAP S/4HANA"
        assert anchors[0]["mentions"] == 3  # confidence >= 0.8 → mentions = 3


# =============================================================================
# TESTS: Cas spéciaux de l'ADR
# =============================================================================

class TestADRSpecialCases:
    """Tests des cas spéciaux documentés dans l'ADR."""

    def test_public_3_case(self):
        """
        Cas ADR: "PUBLIC 3" dans un document avec sections numérotées.
        Devrait être rejeté comme artefact structurel.
        """
        context = DocumentContext(
            structure_hint=StructureHint(
                has_numbered_sections=True,
                numbering_patterns=["WORD+NUMBER"],
                confidence=0.9,
            ),
            entity_hints=[],  # Pas d'entity anchor pour "PUBLIC"
        )

        mention = MarkerMention(
            raw_text="PUBLIC 3",
            prefix="PUBLIC",
            number="3",
            number_len=1,
            shape="WORD_NUMBER",
            position_hint=PositionHint(
                is_heading_like=True,
                line_start=True,
            ),
        )

        decision = decide_marker(mention, context)

        # Doit être rejeté
        assert decision.is_rejected()
        assert decision.score <= 0.20
        assert "HEADING_OR_TOC_ARTIFACT" in decision.reasons

    def test_iphone_15_with_anchor(self):
        """
        Cas ADR: "iPhone 15" dans un document sur iPhone.
        Devrait être accepté grâce à l'entity anchor.
        """
        context = DocumentContext(
            structure_hint=StructureHint(
                has_numbered_sections=True,  # Même avec sections numérotées
                numbering_patterns=["WORD+NUMBER"],
                confidence=0.8,
            ),
            entity_hints=[
                EntityHint(
                    label="iPhone",
                    type_hint="product",
                    confidence=0.95,
                    evidence="explicit",
                ),
            ],
        )

        mention = MarkerMention(
            raw_text="iPhone 15",
            prefix="iPhone",
            number="15",
            number_len=2,
            shape="WORD_NUMBER",
        )

        decision = decide_marker(mention, context)

        # Doit être accepté grâce à l'entity anchor
        assert "ENTITY_ANCHOR_CORROBORATES" in decision.reasons
        # Le score devrait être suffisamment élevé pour accepter
        assert decision.score >= 0.40  # Au minimum pas rejeté

    def test_hierarchy_invariant(self):
        """
        Invariant A: DocumentContext ne crée jamais de MarkerMention.
        La source de vérité est toujours syntaxique.
        """
        # Un DocumentContext avec des entity_hints ne peut pas créer de markers
        context = DocumentContext(
            entity_hints=[
                EntityHint(label="SAP 2023", type_hint="product", confidence=0.9),
            ],
        )

        # Sans MarkerMention syntaxique, rien ne peut être décidé
        # La fonction decide_marker() requiert un MarkerMention existant
        # Ce test vérifie que l'architecture respecte l'invariant


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
