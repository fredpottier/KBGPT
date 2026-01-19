"""
Tests d'intégration End-to-End pour Evidence Bundle - Sprint 1 OSMOSE.

Ces tests vérifient le pipeline complet de création et promotion de bundles.
Nécessite Neo4j en cours d'exécution.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from knowbase.relations.evidence_bundle_models import (
    BundleProcessingResult,
    BundleProcessingStats,
    BundleValidationStatus,
    CandidatePair,
    EvidenceBundle,
    EvidenceFragment,
    ExtractionMethodBundle,
    FragmentType,
    PredicateCandidate,
)
from knowbase.relations.evidence_bundle_resolver import (
    EvidenceBundleResolver,
    PREDICATE_TO_RELATION_TYPE,
    DEFAULT_RELATION_TYPE,
)
from knowbase.relations.bundle_validator import validate_bundle, apply_validation_to_bundle
from knowbase.relations.confidence_calculator import compute_bundle_confidence_from_fragments


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_neo4j_client():
    """Client Neo4j mocké."""
    client = MagicMock()
    client.database = "neo4j"

    # Mock driver session
    mock_session = MagicMock()
    client.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    client.driver.session.return_value.__exit__ = MagicMock(return_value=None)

    return client


@pytest.fixture
def sample_candidate_pair():
    """Paire candidate de test."""
    return CandidatePair(
        subject_concept_id="cc:sap-s4hana",
        subject_label="SAP S/4HANA",
        object_concept_id="cc:btp",
        object_label="BTP",
        shared_context_id="sec:doc123:abc",
        subject_quote="SAP S/4HANA",
        object_quote="BTP",
        subject_char_start=0,
        subject_char_end=11,
        object_char_start=20,
        object_char_end=23,
    )


@pytest.fixture
def sample_predicate():
    """Prédicat candidat de test."""
    return PredicateCandidate(
        text="intègre",
        lemma="intégrer",
        pos="VERB",
        dep="ROOT",
        char_start=12,
        char_end=19,
        token_index=2,
        is_auxiliary=False,
        is_copula=False,
        is_modal=False,
        has_prep_complement=False,
        structure_confidence=0.85,
    )


@pytest.fixture
def sample_bundle():
    """Bundle complet de test."""
    subject = EvidenceFragment(
        fragment_id="frag:subj",
        fragment_type=FragmentType.ENTITY_MENTION,
        text="SAP S/4HANA",
        source_context_id="sec:doc123:abc",
        char_start=0,
        char_end=11,
        confidence=0.9,
        extraction_method=ExtractionMethodBundle.CHARSPAN_EXACT,
    )

    obj = EvidenceFragment(
        fragment_id="frag:obj",
        fragment_type=FragmentType.ENTITY_MENTION,
        text="BTP",
        source_context_id="sec:doc123:abc",
        char_start=20,
        char_end=23,
        confidence=0.85,
        extraction_method=ExtractionMethodBundle.CHARSPAN_EXACT,
    )

    predicate = EvidenceFragment(
        fragment_id="frag:pred",
        fragment_type=FragmentType.PREDICATE_LEXICAL,
        text="intègre",
        source_context_id="sec:doc123:abc",
        char_start=12,
        char_end=19,
        confidence=0.8,
        extraction_method=ExtractionMethodBundle.SPACY_DEP,
    )

    return EvidenceBundle(
        bundle_id="bnd:test123",
        tenant_id="default",
        document_id="doc:test",
        evidence_subject=subject,
        evidence_object=obj,
        evidence_predicate=[predicate],
        subject_concept_id="cc:sap-s4hana",
        object_concept_id="cc:btp",
        relation_type_candidate="INTEGRATES_WITH",
        typing_confidence=0.75,
        confidence=0.8,
        validation_status=BundleValidationStatus.CANDIDATE,
    )


# =============================================================================
# Tests Création de Bundles
# =============================================================================

class TestIntraSectionBundleCreation:
    """Tests création de bundles intra-section."""

    def test_build_bundle_from_pair(self, mock_neo4j_client, sample_candidate_pair, sample_predicate):
        """Construire un bundle à partir d'une paire et prédicat."""
        resolver = EvidenceBundleResolver(
            neo4j_client=mock_neo4j_client,
            lang="fr",
            auto_promote=False,
        )

        section_text = "SAP S/4HANA intègre nativement BTP."

        bundle = resolver._build_bundle(
            pair=sample_candidate_pair,
            predicate=sample_predicate,
            section_text=section_text,
            document_id="doc:test",
            tenant_id="default",
        )

        assert bundle is not None
        assert bundle.subject_concept_id == "cc:sap-s4hana"
        assert bundle.object_concept_id == "cc:btp"
        assert bundle.relation_type_candidate == "INTEGRATES_WITH"
        assert bundle.confidence > 0

    def test_bundle_confidence_calculation(self, sample_bundle):
        """La confiance est bien calculée (min rule)."""
        confidence = compute_bundle_confidence_from_fragments(
            sample_bundle.evidence_subject,
            sample_bundle.evidence_object,
            sample_bundle.evidence_predicate,
        )

        # Min des 3 fragments: 0.9, 0.85, 0.8 = 0.8
        assert confidence == 0.8


class TestBundleValidation:
    """Tests validation de bundles."""

    def test_valid_bundle_passes(self, sample_bundle):
        """Un bundle valide passe la validation."""
        result = validate_bundle(sample_bundle)

        assert result.is_valid is True
        assert len(result.checks_failed) == 0

    def test_self_relation_rejected(self, sample_bundle):
        """Auto-relation (sujet == objet) est rejetée."""
        sample_bundle.object_concept_id = sample_bundle.subject_concept_id

        result = validate_bundle(sample_bundle)

        assert result.is_valid is False
        assert "different_concepts" in result.checks_failed

    def test_low_confidence_rejected(self, sample_bundle):
        """Confiance trop basse est rejetée."""
        sample_bundle.confidence = 0.3

        result = validate_bundle(sample_bundle)

        assert result.is_valid is False
        assert "confidence_threshold" in result.checks_failed

    def test_missing_predicate_rejected(self, sample_bundle):
        """Bundle sans prédicat est rejeté."""
        sample_bundle.evidence_predicate = []

        result = validate_bundle(sample_bundle)

        assert result.is_valid is False
        assert "predicate_present" in result.checks_failed


class TestBundlePromotion:
    """Tests promotion de bundles en relations."""

    def test_apply_validation_promoted(self, sample_bundle):
        """Un bundle valide reste CANDIDATE (prêt pour promotion)."""
        section_text = "SAP S/4HANA intègre nativement BTP."

        bundle = apply_validation_to_bundle(sample_bundle, section_text, "fr")

        # Reste CANDIDATE car validation OK
        assert bundle.validation_status == BundleValidationStatus.CANDIDATE
        assert bundle.rejection_reason is None

    def test_apply_validation_rejected(self, sample_bundle):
        """Un bundle invalide est marqué REJECTED."""
        sample_bundle.confidence = 0.2

        bundle = apply_validation_to_bundle(sample_bundle, None, "fr")

        assert bundle.validation_status == BundleValidationStatus.REJECTED
        assert bundle.rejection_reason is not None


class TestRejectionLogging:
    """Tests logging des rejets."""

    def test_rejection_has_reason(self, sample_bundle):
        """Un bundle rejeté a toujours une raison."""
        sample_bundle.confidence = 0.1

        bundle = apply_validation_to_bundle(sample_bundle, None, "fr")

        assert bundle.validation_status == BundleValidationStatus.REJECTED
        assert bundle.rejection_reason is not None
        assert len(bundle.rejection_reason) > 0


# =============================================================================
# Tests Relation Type Mapping
# =============================================================================

class TestRelationTypeMapping:
    """Tests mapping prédicat -> type de relation."""

    def test_integrer_maps_correctly(self):
        """'intégrer' mappe vers INTEGRATES_WITH."""
        assert PREDICATE_TO_RELATION_TYPE.get("intégrer") == "INTEGRATES_WITH"

    def test_utiliser_maps_correctly(self):
        """'utiliser' mappe vers USES."""
        assert PREDICATE_TO_RELATION_TYPE.get("utiliser") == "USES"

    def test_unknown_lemma_fallback(self):
        """Un lemme inconnu utilise DEFAULT_RELATION_TYPE."""
        unknown = "xyzabc"
        result = PREDICATE_TO_RELATION_TYPE.get(unknown, DEFAULT_RELATION_TYPE)
        assert result == DEFAULT_RELATION_TYPE


# =============================================================================
# Tests Processing Stats
# =============================================================================

class TestProcessingStats:
    """Tests statistiques de traitement."""

    def test_stats_counting(self):
        """Les stats comptent correctement."""
        stats = BundleProcessingStats(
            pairs_found=10,
            pairs_with_charspan=8,
            pairs_skipped_no_charspan=2,
            bundles_created=6,
            bundles_promoted=4,
            bundles_rejected=2,
            rejection_counts={"GENERIC_VERB": 1, "LOW_CONFIDENCE": 1},
        )

        assert stats.pairs_found == 10
        assert stats.bundles_created == 6
        assert stats.bundles_promoted + stats.bundles_rejected == 6

    def test_processing_result_complete(self):
        """Le résultat de traitement contient toutes les infos."""
        stats = BundleProcessingStats()
        result = BundleProcessingResult(
            document_id="doc:test",
            tenant_id="default",
            bundles=[],
            stats=stats,
            processing_time_seconds=1.5,
        )

        assert result.document_id == "doc:test"
        assert result.processing_time_seconds == 1.5
        assert result.stats is not None


# =============================================================================
# Tests E2E avec Mock
# =============================================================================

class TestFullDocumentProcessing:
    """Tests traitement complet d'un document (mocké)."""

    @patch("knowbase.relations.evidence_bundle_resolver.EvidenceBundleResolver._process_pair")
    @patch("knowbase.relations.candidate_detector.CandidateDetector.find_intra_section_pairs")
    @patch("knowbase.relations.candidate_detector.CandidateDetector.get_section_text")
    def test_process_document_flow(
        self,
        mock_get_text,
        mock_find_pairs,
        mock_process_pair,
        mock_neo4j_client,
        sample_bundle,
    ):
        """Le flux de traitement d'un document fonctionne."""
        # Setup mocks
        mock_find_pairs.return_value = [
            CandidatePair(
                subject_concept_id="cc:a",
                subject_label="A",
                object_concept_id="cc:b",
                object_label="B",
                shared_context_id="sec:test",
                subject_char_start=0,
                subject_char_end=1,
                object_char_start=5,
                object_char_end=6,
            )
        ]
        mock_get_text.return_value = "A uses B."
        mock_process_pair.return_value = sample_bundle

        # Créer resolver avec auto_promote=False pour éviter les appels Neo4j
        resolver = EvidenceBundleResolver(
            neo4j_client=mock_neo4j_client,
            lang="fr",
            auto_promote=False,
        )

        # Mock persistence
        with patch.object(resolver.persistence, "persist_bundle"):
            result = resolver.process_document("doc:test", "default")

        # Vérifications
        assert result.document_id == "doc:test"
        assert result.stats.pairs_found == 1


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
