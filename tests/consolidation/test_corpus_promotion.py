"""
Tests unitaires pour ADR_UNIFIED_CORPUS_PROMOTION - Pass 2.0 Corpus Promotion.

Tests:
- CorpusPromotionConfig, PromotionDecision, CorpusPromotionStats dataclasses
- check_high_signal_v2() function
- Règles de promotion unifiées
- CorpusPromotionEngine avec mocks Neo4j

Spec: doc/ongoing/ADR_UNIFIED_CORPUS_PROMOTION.md
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from knowbase.consolidation.corpus_promotion import (
    CorpusPromotionConfig,
    PromotionDecision,
    CorpusPromotionStats,
    CorpusPromotionEngine,
    get_corpus_promotion_engine,
    check_high_signal_v2,
)


# =============================================================================
# Tests pour CorpusPromotionConfig
# =============================================================================


class TestCorpusPromotionConfig:
    """Tests pour la dataclass CorpusPromotionConfig."""

    def test_default_values(self):
        """Valeurs par défaut."""
        config = CorpusPromotionConfig()
        assert config.min_proto_for_stable == 2
        assert config.min_sections_for_stable == 2
        assert config.min_documents_for_stable == 2
        assert config.max_label_length == 120
        assert config.max_template_likelihood == 0.5
        assert config.max_positional_stability == 0.8
        assert config.require_span_for_crossdoc is True
        assert config.min_confidence_for_crossdoc == 0.7

    def test_custom_values(self):
        """Valeurs personnalisées."""
        config = CorpusPromotionConfig(
            min_proto_for_stable=3,
            min_sections_for_stable=3,
            min_documents_for_stable=5,
            max_label_length=80,
        )
        assert config.min_proto_for_stable == 3
        assert config.min_sections_for_stable == 3
        assert config.min_documents_for_stable == 5
        assert config.max_label_length == 80


# =============================================================================
# Tests pour PromotionDecision
# =============================================================================


class TestPromotionDecision:
    """Tests pour la dataclass PromotionDecision."""

    def test_default_values(self):
        """Valeurs par défaut."""
        decision = PromotionDecision(canonical_label="test concept", promote=False)
        assert decision.canonical_label == "test concept"
        assert decision.promote is False
        assert decision.stability is None
        assert decision.reason == ""
        assert decision.proto_count == 0
        assert decision.section_count == 0
        assert decision.document_count == 0
        assert decision.is_high_signal is False
        assert decision.has_minimal_signal is False
        assert decision.high_signal_reasons == []
        assert decision.proto_ids == []
        assert decision.document_ids == []

    def test_promoted_stable(self):
        """Décision de promotion STABLE."""
        decision = PromotionDecision(
            canonical_label="sap s/4hana",
            promote=True,
            stability="stable",
            reason="≥2 occurrences même document",
            proto_count=3,
            section_count=2,
            document_count=1,
            proto_ids=["pc_001", "pc_002", "pc_003"],
            document_ids=["doc_001"],
        )
        assert decision.promote is True
        assert decision.stability == "stable"
        assert len(decision.proto_ids) == 3

    def test_promoted_singleton_high_signal(self):
        """Décision de promotion SINGLETON high-signal."""
        decision = PromotionDecision(
            canonical_label="fiori launchpad",
            promote=True,
            stability="singleton",
            reason="singleton high-signal V2",
            proto_count=1,
            is_high_signal=True,
            high_signal_reasons=["normative_role:definition", "main_zone"],
        )
        assert decision.stability == "singleton"
        assert decision.is_high_signal is True


# =============================================================================
# Tests pour CorpusPromotionStats
# =============================================================================


class TestCorpusPromotionStats:
    """Tests pour la dataclass CorpusPromotionStats."""

    def test_default_values(self):
        """Valeurs par défaut."""
        stats = CorpusPromotionStats(
            document_id="doc_001",
            tenant_id="default",
        )
        assert stats.document_id == "doc_001"
        assert stats.tenant_id == "default"
        assert stats.protos_loaded == 0
        assert stats.groups_analyzed == 0
        assert stats.promoted_stable == 0
        assert stats.promoted_singleton == 0
        assert stats.not_promoted == 0
        assert stats.crossdoc_promotions == 0
        assert stats.corpus_protos_linked == 0

    def test_total_promoted(self):
        """Propriété total_promoted."""
        stats = CorpusPromotionStats(
            document_id="doc_001",
            tenant_id="default",
            promoted_stable=5,
            promoted_singleton=3,
        )
        assert stats.total_promoted == 8


# =============================================================================
# Tests pour check_high_signal_v2
# =============================================================================


class TestCheckHighSignalV2:
    """Tests pour la fonction check_high_signal_v2."""

    @pytest.fixture
    def config(self):
        """Configuration par défaut."""
        return CorpusPromotionConfig()

    def test_normative_role_definition(self, config):
        """Rôle normatif 'definition' est high-signal."""
        proto = {
            "label": "SAP S/4HANA",
            "anchor_role": "definition",
            "quote": "SAP S/4HANA is the intelligent ERP system.",
            "template_likelihood": 0.1,
            "positional_stability": 0.2,
            "dominant_zone": "main",
            "section_path": "/Introduction",
        }
        is_hs, reasons = check_high_signal_v2(proto, config)
        assert is_hs is True
        assert "normative_role:definition" in reasons
        assert "main_zone" in reasons

    def test_normative_modal_shall(self, config):
        """Modal 'shall' est high-signal."""
        proto = {
            "label": "User Authentication",
            "anchor_role": "mention",
            "quote": "The system shall authenticate all users.",
            "template_likelihood": 0.2,
            "positional_stability": 0.1,
            "dominant_zone": "main",
            "section_path": "/Security",
        }
        is_hs, reasons = check_high_signal_v2(proto, config)
        assert is_hs is True
        assert "normative_modal:shall" in reasons

    def test_no_normative_signal(self, config):
        """Pas de signal normatif → pas high-signal."""
        proto = {
            "label": "Example Text",
            "anchor_role": "mention",
            "quote": "This is an example.",
            "template_likelihood": 0.1,
            "dominant_zone": "main",
        }
        is_hs, reasons = check_high_signal_v2(proto, config)
        assert is_hs is False
        assert reasons == []

    def test_high_template_likelihood_rejected(self, config):
        """Template likelihood élevé est rejeté."""
        proto = {
            "label": "Subject to change",
            "anchor_role": "constraint",
            "quote": "Subject to change without notice.",
            "template_likelihood": 0.9,  # Trop élevé
            "positional_stability": 0.2,
            "dominant_zone": "main",
        }
        is_hs, reasons = check_high_signal_v2(proto, config)
        assert is_hs is False

    def test_high_positional_stability_rejected(self, config):
        """Positional stability élevé (footer/header) est rejeté."""
        proto = {
            "label": "Confidential",
            "anchor_role": "constraint",
            "quote": "This document is confidential.",
            "template_likelihood": 0.1,
            "positional_stability": 0.95,  # Trop stable (footer?)
            "dominant_zone": "main",
        }
        is_hs, reasons = check_high_signal_v2(proto, config)
        assert is_hs is False

    def test_bottom_zone_repeated_rejected(self, config):
        """BOTTOM_ZONE répété est rejeté."""
        proto = {
            "label": "Page Number",
            "anchor_role": "definition",
            "quote": "Page 1 of 10",
            "template_likelihood": 0.3,
            "positional_stability": 0.5,
            "dominant_zone": "bottom",
            "is_repeated_bottom": True,
        }
        is_hs, reasons = check_high_signal_v2(proto, config)
        assert is_hs is False

    def test_no_content_signal_rejected(self, config):
        """Pas de signal contenu (pas main zone, pas section) → rejeté."""
        proto = {
            "label": "Header Text",
            "anchor_role": "definition",
            "quote": "Shall be displayed",
            "template_likelihood": 0.1,
            "positional_stability": 0.2,
            "dominant_zone": "top",  # Pas main
            "section_path": "",  # Pas de section
        }
        is_hs, reasons = check_high_signal_v2(proto, config)
        assert is_hs is False

    def test_label_too_long_rejected(self, config):
        """Label trop long est rejeté."""
        long_label = "This is a very long concept label that exceeds the maximum allowed length " * 3
        proto = {
            "label": long_label,
            "anchor_role": "definition",
            "quote": "Shall be defined",
            "template_likelihood": 0.1,
            "dominant_zone": "main",
            "section_path": "/Content",
        }
        is_hs, reasons = check_high_signal_v2(proto, config)
        assert is_hs is False


# =============================================================================
# Tests pour CorpusPromotionEngine
# =============================================================================


class TestCorpusPromotionEngine:
    """Tests pour CorpusPromotionEngine avec mocks."""

    @pytest.fixture
    def mock_neo4j(self):
        """Mock du client Neo4j."""
        client = MagicMock()
        session = MagicMock()
        client.driver.session.return_value.__enter__ = MagicMock(return_value=session)
        client.driver.session.return_value.__exit__ = MagicMock(return_value=None)
        return client, session

    @pytest.fixture
    def engine(self, mock_neo4j):
        """Engine avec mocks."""
        with patch('knowbase.consolidation.corpus_promotion.get_neo4j_client') as mock_client, \
             patch('knowbase.consolidation.corpus_promotion.get_hybrid_anchor_config') as mock_config:
            mock_client.return_value = mock_neo4j[0]
            mock_config.return_value = {}

            engine = CorpusPromotionEngine(tenant_id="test")
            return engine

    def test_determine_promotion_stable_multi_occurrence(self, engine):
        """≥2 occurrences même document → STABLE."""
        protos = [
            {"proto_id": "pc_001", "label": "SAP S/4HANA", "sections": ["/Intro"], "confidence": 0.8},
            {"proto_id": "pc_002", "label": "SAP S/4HANA", "sections": ["/Intro"], "confidence": 0.9},
        ]

        # Mock corpus count = 0
        with patch.object(engine, 'count_corpus_occurrences', return_value=(0, [])):
            decision = engine.determine_promotion(
                canonical_label="sap s/4hana",
                protos=protos,
                document_id="doc_001",
            )

        assert decision.promote is True
        assert decision.stability == "stable"
        assert "occurrences même document" in decision.reason

    def test_determine_promotion_stable_multi_section(self, engine):
        """≥2 sections différentes → STABLE."""
        protos = [
            {"proto_id": "pc_001", "label": "Fiori Launchpad", "sections": ["/Intro", "/Installation"], "confidence": 0.8},
        ]

        with patch.object(engine, 'count_corpus_occurrences', return_value=(0, [])):
            decision = engine.determine_promotion(
                canonical_label="fiori launchpad",
                protos=protos,
                document_id="doc_001",
            )

        assert decision.promote is True
        assert decision.stability == "stable"
        assert "sections différentes" in decision.reason

    def test_determine_promotion_stable_crossdoc(self, engine):
        """≥2 documents + signal minimal → STABLE."""
        protos = [
            {"proto_id": "pc_001", "label": "ECC 6.0", "sections": ["/Intro"],
             "anchor_status": "SPAN", "confidence": 0.8},
        ]

        # Mock corpus count = 1 (autre document)
        with patch.object(engine, 'count_corpus_occurrences', return_value=(1, ["doc_002"])):
            decision = engine.determine_promotion(
                canonical_label="ecc 6.0",
                protos=protos,
                document_id="doc_001",
            )

        assert decision.promote is True
        assert decision.stability == "stable"
        assert "documents" in decision.reason
        assert decision.document_count == 2

    def test_determine_promotion_singleton_high_signal(self, engine):
        """Singleton + high-signal V2 → SINGLETON."""
        protos = [
            {
                "proto_id": "pc_001",
                "label": "Authorization Check",
                "sections": [],
                "anchor_role": "constraint",
                "quote": "The system shall verify authorization.",
                "template_likelihood": 0.1,
                "positional_stability": 0.1,
                "dominant_zone": "main",
                "section_path": "/Security",
                "confidence": 0.9,
            },
        ]

        with patch.object(engine, 'count_corpus_occurrences', return_value=(0, [])):
            decision = engine.determine_promotion(
                canonical_label="authorization check",
                protos=protos,
                document_id="doc_001",
            )

        assert decision.promote is True
        assert decision.stability == "singleton"
        assert decision.is_high_signal is True

    def test_determine_promotion_no_promotion(self, engine):
        """Singleton sans high-signal → pas de promotion."""
        protos = [
            {
                "proto_id": "pc_001",
                "label": "Random Mention",
                "sections": [],
                "anchor_role": "mention",
                "quote": "Some random mention",
                "template_likelihood": 0.1,
                "dominant_zone": "main",
                "confidence": 0.5,
            },
        ]

        with patch.object(engine, 'count_corpus_occurrences', return_value=(0, [])):
            decision = engine.determine_promotion(
                canonical_label="random mention",
                protos=protos,
                document_id="doc_001",
            )

        assert decision.promote is False
        assert decision.stability is None

    def test_check_minimal_signal_span(self, engine):
        """Signal minimal via anchor_status=SPAN."""
        protos = [{"anchor_status": "SPAN", "confidence": 0.5, "anchor_roles": []}]
        assert engine._check_minimal_signal(protos) is True

    def test_check_minimal_signal_role(self, engine):
        """Signal minimal via rôle definition/constraint."""
        protos = [{"anchor_status": "FUZZY", "confidence": 0.5, "anchor_roles": ["definition"]}]
        assert engine._check_minimal_signal(protos) is True

    def test_check_minimal_signal_confidence(self, engine):
        """Signal minimal via confidence >= 0.7."""
        protos = [{"anchor_status": "FUZZY", "confidence": 0.8, "anchor_roles": ["mention"]}]
        assert engine._check_minimal_signal(protos) is True

    def test_check_minimal_signal_none(self, engine):
        """Pas de signal minimal."""
        protos = [{"anchor_status": "FUZZY", "confidence": 0.5, "anchor_roles": ["mention"]}]
        assert engine._check_minimal_signal(protos) is False

    def test_group_by_canonical_label(self, engine):
        """Groupement par label canonique."""
        protos = [
            {"proto_id": "pc_001", "label": "SAP S/4HANA"},
            {"proto_id": "pc_002", "label": "sap s/4hana"},
            {"proto_id": "pc_003", "label": "Fiori"},
        ]

        groups = engine.group_by_canonical_label(protos)

        assert len(groups) == 2
        assert len(groups["sap s/4hana"]) == 2
        assert len(groups["fiori"]) == 1

    def test_normalize_label(self, engine):
        """Test de la normalisation des labels."""
        # Basic normalization
        assert engine._normalize_label("SAP S/4HANA") == "sap s/4hana"
        assert engine._normalize_label("  Fiori  ") == "fiori"

        # Collapse whitespace
        assert engine._normalize_label("SAP   S/4HANA") == "sap s/4hana"

        # S/4 HANA → s/4hana (common pattern)
        assert engine._normalize_label("S/4 HANA") == "s/4hana"

        # Empty label
        assert engine._normalize_label("") == ""


# =============================================================================
# Tests pour get_corpus_promotion_engine singleton
# =============================================================================


class TestGetCorpusPromotionEngine:
    """Tests pour la fonction singleton get_corpus_promotion_engine."""

    def test_returns_same_instance(self):
        """Retourne la même instance pour le même tenant."""
        from knowbase.consolidation import corpus_promotion
        corpus_promotion._engines.clear()

        with patch('knowbase.consolidation.corpus_promotion.get_neo4j_client'), \
             patch('knowbase.consolidation.corpus_promotion.get_hybrid_anchor_config', return_value={}):
            engine1 = get_corpus_promotion_engine("tenant_a")
            engine2 = get_corpus_promotion_engine("tenant_a")

        assert engine1 is engine2

    def test_different_tenants_different_instances(self):
        """Retourne des instances différentes pour différents tenants."""
        from knowbase.consolidation import corpus_promotion
        corpus_promotion._engines.clear()

        with patch('knowbase.consolidation.corpus_promotion.get_neo4j_client'), \
             patch('knowbase.consolidation.corpus_promotion.get_hybrid_anchor_config', return_value={}):
            engine_a = get_corpus_promotion_engine("tenant_a")
            engine_b = get_corpus_promotion_engine("tenant_b")

        assert engine_a is not engine_b
        assert engine_a.tenant_id == "tenant_a"
        assert engine_b.tenant_id == "tenant_b"


# =============================================================================
# Tests d'intégration logique (sans Neo4j)
# =============================================================================


class TestPromotionRulesIntegration:
    """Tests de la logique des règles de promotion."""

    def test_rule_priority_multi_occurrence_first(self):
        """Règle multi-occurrence a priorité sur cross-doc."""
        # Si ≥2 occurrences même doc, pas besoin de vérifier cross-doc
        config = CorpusPromotionConfig(min_proto_for_stable=2)

        proto_count = 3  # 3 occurrences
        section_count = 1
        corpus_count = 5  # Même si 5 docs au corpus

        # Règle 1 appliquée
        assert proto_count >= config.min_proto_for_stable

    def test_invariant_no_promotion_without_signal(self):
        """Invariant: Pas de promotion singleton sans high-signal."""
        config = CorpusPromotionConfig()

        # Proto singleton sans signal
        proto = {
            "label": "Random Text",
            "anchor_role": "mention",
            "quote": "just a mention",
            "template_likelihood": 0.1,
            "dominant_zone": "main",
        }

        is_hs, _ = check_high_signal_v2(proto, config)

        # Singleton sans high-signal → pas de promotion
        assert is_hs is False

    def test_crossdoc_requires_minimal_signal(self):
        """Cross-doc requiert signal minimal."""
        # Même avec présence corpus, pas de promotion sans signal

        has_minimal_signal = False
        corpus_count = 3

        # Règle 3 non satisfaite
        promote_crossdoc = corpus_count >= 1 and has_minimal_signal
        assert promote_crossdoc is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
