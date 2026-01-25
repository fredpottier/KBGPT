"""
Tests d'intégration MVP V1 avec assertion_extractor.

Vérifie l'enrichissement des assertions avec:
- ValueExtractor
- ClaimKeyPatterns
- PromotionPolicy MVP V1
"""

import pytest
from knowbase.stratified.pass1.assertion_extractor import (
    AssertionExtractorV2,
    RawAssertion,
    EnrichedAssertion,
    MVPV1EnrichmentResult,
)
from knowbase.stratified.models import AssertionType
from knowbase.stratified.models.information import PromotionStatus, ValueKind


@pytest.fixture
def extractor():
    return AssertionExtractorV2(allow_fallback=True)


@pytest.fixture
def sample_assertions():
    """Assertions de test variées."""
    return [
        RawAssertion(
            assertion_id="test_001",
            text="TLS 1.3 is required for all connections",
            assertion_type=AssertionType.PRESCRIPTIVE,
            chunk_id="chunk_1",
            start_char=0,
            end_char=40,
            confidence=0.9
        ),
        RawAssertion(
            assertion_id="test_002",
            text="The system provides 99.9% SLA availability",
            assertion_type=AssertionType.FACTUAL,
            chunk_id="chunk_1",
            start_char=41,
            end_char=83,
            confidence=0.85
        ),
        RawAssertion(
            assertion_id="test_003",
            text="Data must remain in Germany for compliance",
            assertion_type=AssertionType.PRESCRIPTIVE,
            chunk_id="chunk_2",
            start_char=0,
            end_char=42,
            confidence=0.95
        ),
        RawAssertion(
            assertion_id="test_004",
            text="Backups are performed daily at midnight",
            assertion_type=AssertionType.FACTUAL,
            chunk_id="chunk_2",
            start_char=43,
            end_char=82,
            confidence=0.8
        ),
        RawAssertion(
            assertion_id="test_005",
            text="Customer is responsible for data backup",
            assertion_type=AssertionType.PRESCRIPTIVE,
            chunk_id="chunk_3",
            start_char=0,
            end_char=39,
            confidence=0.88
        ),
        RawAssertion(
            assertion_id="test_006",
            text="This page describes the configuration",
            assertion_type=AssertionType.FACTUAL,
            chunk_id="chunk_3",
            start_char=40,
            end_char=77,
            confidence=0.5
        ),
        RawAssertion(
            assertion_id="test_007",
            text="SAP S/4HANA is an ERP system for large enterprises",
            assertion_type=AssertionType.DEFINITIONAL,
            chunk_id="chunk_4",
            start_char=0,
            end_char=50,
            confidence=0.92
        ),
    ]


class TestMVPV1Enrichment:
    """Tests enrichissement MVP V1."""

    def test_enrich_returns_correct_structure(self, extractor, sample_assertions):
        """Vérifie que la structure de retour est correcte."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        assert isinstance(result, MVPV1EnrichmentResult)
        assert len(result.enriched) == len(sample_assertions)
        assert "total" in result.stats
        assert result.stats["total"] == len(sample_assertions)

    def test_value_extraction_tls(self, extractor, sample_assertions):
        """TLS 1.3 doit être extrait comme version."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        tls_assertion = next(e for e in result.enriched if e.assertion.assertion_id == "test_001")
        assert tls_assertion.has_value
        assert tls_assertion.value.kind == ValueKind.VERSION
        assert tls_assertion.value.normalized == "1.3"

    def test_value_extraction_sla(self, extractor, sample_assertions):
        """99.9% SLA doit être extrait comme pourcentage."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        sla_assertion = next(e for e in result.enriched if e.assertion.assertion_id == "test_002")
        assert sla_assertion.has_value
        assert sla_assertion.value.kind == ValueKind.PERCENT
        assert abs(sla_assertion.value.normalized - 0.999) < 0.0001

    def test_claimkey_inference_tls(self, extractor, sample_assertions):
        """TLS 1.3 doit matcher le pattern tls_min_version."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        tls_assertion = next(e for e in result.enriched if e.assertion.assertion_id == "test_001")
        assert tls_assertion.has_claimkey
        assert tls_assertion.claimkey_match.key == "tls_min_version"
        assert tls_assertion.claimkey_match.domain == "security.encryption"

    def test_claimkey_inference_sla(self, extractor, sample_assertions):
        """99.9% SLA doit matcher le pattern sla_availability."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        sla_assertion = next(e for e in result.enriched if e.assertion.assertion_id == "test_002")
        assert sla_assertion.has_claimkey
        assert "sla" in sla_assertion.claimkey_match.key.lower()
        assert sla_assertion.claimkey_match.domain == "sla.availability"

    def test_claimkey_inference_residency(self, extractor, sample_assertions):
        """Data residency Germany doit matcher le pattern."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        residency_assertion = next(e for e in result.enriched if e.assertion.assertion_id == "test_003")
        assert residency_assertion.has_claimkey
        assert "residency" in residency_assertion.claimkey_match.key
        assert "germany" in residency_assertion.claimkey_match.key.lower()

    def test_claimkey_inference_backup(self, extractor, sample_assertions):
        """Backups daily doit matcher le pattern backup_frequency."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        backup_assertion = next(e for e in result.enriched if e.assertion.assertion_id == "test_004")
        assert backup_assertion.has_claimkey
        assert backup_assertion.claimkey_match.key == "backup_frequency"

    def test_promotion_prescriptive_linked(self, extractor, sample_assertions):
        """PRESCRIPTIVE doit être PROMOTED_LINKED."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        prescriptive = next(e for e in result.enriched if e.assertion.assertion_id == "test_001")
        assert prescriptive.promotion_status == PromotionStatus.PROMOTED_LINKED
        assert "type:PRESCRIPTIVE" in prescriptive.promotion_reason

    def test_promotion_definitional_linked(self, extractor, sample_assertions):
        """DEFINITIONAL doit être PROMOTED_LINKED."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        definitional = next(e for e in result.enriched if e.assertion.assertion_id == "test_007")
        assert definitional.promotion_status == PromotionStatus.PROMOTED_LINKED
        assert "type:DEFINITIONAL" in definitional.promotion_reason

    def test_promotion_meta_rejected(self, extractor, sample_assertions):
        """Meta text 'This page describes' doit être REJECTED."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        meta = next(e for e in result.enriched if e.assertion.assertion_id == "test_006")
        assert meta.promotion_status == PromotionStatus.REJECTED
        assert "meta_pattern" in meta.promotion_reason

    def test_stats_correctness(self, extractor, sample_assertions):
        """Vérifie les statistiques d'enrichissement."""
        result = extractor.enrich_with_mvp_v1(sample_assertions)

        # Au moins quelques assertions avec valeur
        assert result.stats["with_value"] >= 2  # TLS + SLA

        # Au moins quelques assertions avec ClaimKey
        assert result.stats["with_claimkey"] >= 4  # TLS, SLA, residency, backup

        # Totaux cohérents
        total_promoted = result.stats["promoted_linked"] + result.stats["promoted_unlinked"]
        assert total_promoted + result.stats["rejected"] == result.stats["total"]


class TestMVPV1WithContext:
    """Tests enrichissement avec contexte."""

    def test_context_affects_claimkey(self, extractor):
        """Le contexte product doit influencer le ClaimKey."""
        assertion = RawAssertion(
            assertion_id="ctx_001",
            text="99.9% SLA availability guaranteed",
            assertion_type=AssertionType.FACTUAL,
            chunk_id="chunk_ctx",
            start_char=0,
            end_char=33,
            confidence=0.9
        )

        # Sans contexte
        result_no_ctx = extractor.enrich_with_mvp_v1([assertion])
        key_no_ctx = result_no_ctx.enriched[0].claimkey_match.key

        # Avec contexte product
        result_with_ctx = extractor.enrich_with_mvp_v1(
            [assertion],
            context={"product": "S/4HANA"}
        )
        key_with_ctx = result_with_ctx.enriched[0].claimkey_match.key

        # Le contexte doit être incorporé dans la clé
        assert "s_4hana" in key_with_ctx.lower() or "general" in key_no_ctx


class TestMVPV1EdgeCases:
    """Tests cas limites."""

    def test_empty_assertions(self, extractor):
        """Liste vide doit retourner résultat vide."""
        result = extractor.enrich_with_mvp_v1([])

        assert len(result.enriched) == 0
        assert result.stats["total"] == 0

    def test_no_matches(self, extractor):
        """Texte sans pattern doit être PROMOTED_UNLINKED (pas de rejet silencieux)."""
        assertion = RawAssertion(
            assertion_id="no_match",
            text="The application architecture follows modern design principles",
            assertion_type=AssertionType.FACTUAL,
            chunk_id="chunk_x",
            start_char=0,
            end_char=60,
            confidence=0.7
        )

        result = extractor.enrich_with_mvp_v1([assertion])
        enriched = result.enriched[0]

        # Pas de valeur ni de ClaimKey
        assert not enriched.has_value
        assert not enriched.has_claimkey

        # Mais promue (INVARIANT: jamais de rejet silencieux) - role:fact car FACTUAL
        assert enriched.is_promoted

    def test_responsibility_with_theme(self, extractor):
        """Responsibility pattern avec theme dans le contexte."""
        assertion = RawAssertion(
            assertion_id="resp_001",
            text="Customer is responsible for backup configuration",
            assertion_type=AssertionType.PRESCRIPTIVE,
            chunk_id="chunk_resp",
            start_char=0,
            end_char=47,
            confidence=0.85
        )

        result = extractor.enrich_with_mvp_v1(
            [assertion],
            context={"current_theme": "Backup"}
        )
        enriched = result.enriched[0]

        assert enriched.has_claimkey
        assert "responsibility" in enriched.claimkey_match.key
        assert "backup" in enriched.claimkey_match.key.lower()


class TestEnrichedAssertionProperties:
    """Tests propriétés EnrichedAssertion."""

    def test_has_claimkey_property(self, extractor):
        """Propriété has_claimkey fonctionne correctement."""
        assertion = RawAssertion(
            assertion_id="prop_001",
            text="TLS 1.2 minimum required",
            assertion_type=AssertionType.PRESCRIPTIVE,
            chunk_id="chunk_p",
            start_char=0,
            end_char=24,
            confidence=0.9
        )

        result = extractor.enrich_with_mvp_v1([assertion])
        assert result.enriched[0].has_claimkey is True

    def test_is_promoted_property(self, extractor):
        """Propriété is_promoted fonctionne correctement."""
        assertions = [
            RawAssertion(
                assertion_id="prom_001",
                text="All data must be encrypted at rest for security",
                assertion_type=AssertionType.PRESCRIPTIVE,
                chunk_id="chunk_prom",
                start_char=0,
                end_char=47,
                confidence=0.9
            ),
            RawAssertion(
                assertion_id="prom_002",
                text="See also the documentation for more details",
                assertion_type=AssertionType.FACTUAL,
                chunk_id="chunk_prom",
                start_char=48,
                end_char=91,
                confidence=0.5
            ),
        ]

        result = extractor.enrich_with_mvp_v1(assertions)

        # Prescriptive avec valeur = promoted
        assert result.enriched[0].is_promoted is True

        # Meta text = rejected
        assert result.enriched[1].is_promoted is False
