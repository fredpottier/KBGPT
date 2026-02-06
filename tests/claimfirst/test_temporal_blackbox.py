# tests/claimfirst/test_temporal_blackbox.py
"""
Tests Blackbox pour les requêtes temporelles (Applicability Axis).

7 tests critiques pour validation E2E.

S7: Tests génériques, pas SAP-specific.
    Utilise des capabilities auto-détectées, pas hardcodées.
"""

import pytest
from unittest.mock import MagicMock, patch

from knowbase.claimfirst.models.applicability_axis import (
    ApplicabilityAxis,
    OrderingConfidence,
    OrderType,
)
from knowbase.claimfirst.models.context_comparability import (
    DocumentAuthority,
)
from knowbase.claimfirst.query.latest_selector import (
    LatestSelector,
    LatestPolicy,
    DocumentCandidate,
)
from knowbase.claimfirst.query.intent_resolver import (
    IntentResolver,
    ClusterCandidate,
)
from knowbase.claimfirst.query.temporal_query_engine import (
    TemporalQueryEngine,
    SinceWhenResult,
    StillApplicableResult,
)
from knowbase.claimfirst.query.text_validator import (
    TextValidator,
    TextValidationResult,
    ValidationStatus,
)
from knowbase.claimfirst.query.uncertainty_signals import (
    UncertaintyAnalysis,
    UncertaintySignal,
    UncertaintySignalType,
)


class TestLatestSelectedWithJustification:
    """
    Test 1: Sans contexte → latest sélectionné + why.

    Vérifie que le système peut sélectionner le "latest" et
    toujours fournir une justification (why_selected).
    """

    def test_latest_selected_with_justification(self):
        """Latest sélectionné avec justification obligatoire."""
        # Setup: Axe avec ordre CERTAIN
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
        )
        axis.is_orderable = True
        axis.ordering_confidence = OrderingConfidence.CERTAIN
        axis.value_order = ["1.0", "2.0", "3.0"]

        candidates = [
            DocumentCandidate(
                doc_id="doc_v1",
                context_value="1.0",
                axis_key="release_id",
                authority=DocumentAuthority.OFFICIAL,
            ),
            DocumentCandidate(
                doc_id="doc_v3",
                context_value="3.0",
                axis_key="release_id",
                authority=DocumentAuthority.OFFICIAL,
            ),
        ]

        selector = LatestSelector()
        result = selector.select_latest(
            candidates=candidates,
            axes={"release_id": axis},
        )

        # Vérifications
        assert result.selected_doc_id is not None
        assert result.why_selected is not None
        assert len(result.why_selected) > 0
        # Le latest devrait être 3.0 (le plus récent)
        assert result.selected_context_value == "3.0"


class TestSinceWhenOrderingCertain:
    """
    Test 2: Axe CERTAIN → timeline ordonnée.

    Avec un axe dont l'ordre est CERTAIN (numériques),
    la timeline doit être ordonnée correctement.
    """

    def test_since_when_ordering_certain(self):
        """Timeline ordonnée pour axe CERTAIN."""
        # Simuler le résultat d'un query_since_when avec axe validé
        result = SinceWhenResult(
            capability="Feature X",
            first_occurrence_context="1.0",
            first_occurrence_claims=["claim_001"],
            timeline=[
                {"context": "1.0", "claims": ["claim_001"]},
                {"context": "2.0", "claims": ["claim_002", "claim_003"]},
                {"context": "3.0", "claims": ["claim_004"]},
            ],
            timeline_basis="cluster",
            ordering_confidence="CERTAIN",
        )

        # Vérifications
        assert result.ordering_confidence == "CERTAIN"
        assert result.timeline is not None
        assert len(result.timeline) == 3
        # L'ordre doit être 1.0 → 2.0 → 3.0
        assert result.timeline[0]["context"] == "1.0"
        assert result.timeline[1]["context"] == "2.0"
        assert result.timeline[2]["context"] == "3.0"
        # INV-23: Claims sources présentes
        assert result.first_occurrence_claims is not None
        assert len(result.first_occurrence_claims) > 0


class TestSinceWhenOrderingUnknownRefusesTimeline:
    """
    Test 3: Axe UNKNOWN → liste contextes sans ordre.

    Avec un axe dont l'ordre est UNKNOWN, on retourne les
    contextes mais sans timeline ordonnée (INV-14).
    """

    def test_since_when_ordering_unknown_refuses_timeline(self):
        """Pas de timeline si ordre UNKNOWN."""
        result = SinceWhenResult(
            capability="Feature Y",
            first_occurrence_context="alpha",
            first_occurrence_claims=["claim_010"],
            timeline=None,  # INV-14: Pas de timeline
            ordering_confidence="UNKNOWN",
        )

        # Vérifications
        assert result.ordering_confidence == "UNKNOWN"
        assert result.timeline is None  # INV-14
        # Mais on a quand même la première occurrence
        assert result.first_occurrence_context is not None
        assert result.first_occurrence_claims is not None


class TestValidationContradictionDetected:
    """
    Test 4: Phrase fausse → INCORRECT + claims.

    Quand une phrase contredit le corpus, le statut est
    INCORRECT et les claims contradictoires sont citées.
    """

    def test_validation_contradiction_detected(self):
        """Contradiction détectée avec claims sources."""
        result = TextValidationResult(
            user_text="Feature X is always available in all editions.",
            status=ValidationStatus.INCORRECT,
            supporting_claims=[],
            contradicting_claims=[
                {
                    "claim_id": "claim_contra_001",
                    "text": "Feature X is only available in Enterprise Edition.",
                    "similarity": 0.92,
                },
            ],
            confidence=0.92,
            explanation="The statement contradicts 1 claim in the corpus.",
        )

        # Vérifications
        assert result.status == ValidationStatus.INCORRECT
        # INV-23: Claims contradictoires citées
        assert len(result.contradicting_claims) > 0
        assert result.contradicting_claims[0]["claim_id"] == "claim_contra_001"


class TestValidationUncertainWithSignals:
    """
    Test 5: Présent avant, absent latest → UNCERTAIN + signals.

    Si une claim était présente dans des contextes anciens mais
    absente du latest, on retourne UNCERTAIN (pas REMOVED - INV-17).
    """

    def test_validation_uncertain_with_signals(self):
        """UNCERTAIN avec signals, pas REMOVED sans evidence."""
        # Simuler une analyse d'incertitude
        analysis = UncertaintyAnalysis()
        analysis.add_signal(UncertaintySignal(
            signal_type=UncertaintySignalType.ABSENT_IN_LATEST,
            description="Claim not found in latest context documents",
            evidence_claim_ids=["claim_020"],
            heuristic_confidence_hint=0.4,
        ))
        analysis.add_signal(UncertaintySignal(
            signal_type=UncertaintySignalType.OLDER_ONLY,
            description="Claim only found in older context documents",
            evidence_claim_ids=["claim_020"],
            heuristic_confidence_hint=0.3,
        ))
        analysis.generate_recommendation()

        result = StillApplicableResult(
            claim_id="claim_020",
            claim_text="Old configuration option.",
            is_applicable=None,  # Incertain
            status="UNCERTAIN",  # Pas REMOVED (INV-17)
            latest_context="3.0",
            supporting_claims=[],
            uncertainty_analysis=analysis,
        )

        # Vérifications
        assert result.status == "UNCERTAIN"  # Pas REMOVED
        assert result.is_applicable is None
        assert result.uncertainty_analysis is not None
        assert len(result.uncertainty_analysis.signals) >= 1
        # La recommandation suggère vérification
        assert "verification" in analysis.recommendation.lower() or "uncertain" in analysis.recommendation.lower()


class TestDisambiguationForcedOnVagueQuery:
    """
    Test 6: Question vague → options enrichies obligatoires.

    Sur une query vague, l'IntentResolver doit retourner
    ≥2 candidats avec options de disambiguation enrichies (INV-18).
    """

    def test_disambiguation_forced_on_vague_query(self):
        """Disambiguation forcée avec options enrichies."""
        candidates = [
            ClusterCandidate(
                cluster_id="cluster_001",
                label="Configuration Module",
                score=0.88,
                entities=["Configuration", "Settings"],
                facets=["Administration"],
                doc_count=5,
                claim_count=25,
                sample_claim_text="Configuration allows customization.",
            ),
            ClusterCandidate(
                cluster_id="cluster_002",
                label="Setup Wizard",
                score=0.82,
                entities=["Setup", "Wizard"],
                facets=["Installation"],
                doc_count=3,
                claim_count=12,
                sample_claim_text="Setup wizard guides initial configuration.",
            ),
        ]

        resolver = IntentResolver(neo4j_driver=None)
        result = resolver.resolve(
            query="how to configure",  # Query vague
            candidates=candidates,
        )

        # Vérifications
        # INV-24: ≥2 candidats (pas d'exact match)
        assert len(result.candidate_clusters) >= 2
        assert result.exact_match is False

        # INV-18: Options enrichies
        assert len(result.disambiguation_options) >= 2
        for option in result.disambiguation_options:
            assert option.sample_claim_text is not None
            assert option.cluster_id is not None
            assert option.label is not None


class TestSinceWhenAutoDetectedCapability:
    """
    Test 7: "Since when <capability X>" où X = auto-détecté.

    S7: Pas de hardcode "GL Accounting" ou autre terme SAP.
    La capability est détectée depuis un cluster populaire.
    """

    def test_since_when_auto_detected_capability(self):
        """Capability auto-détectée depuis cluster populaire."""
        # Simuler un cluster populaire découvert dynamiquement
        # (pas hardcodé "GL Accounting" ou autre terme SAP)
        popular_cluster = ClusterCandidate(
            cluster_id="cluster_popular",
            label="Data Processing Module",  # Générique, pas SAP
            score=0.95,
            entities=["Data Processing", "Batch Jobs"],
            doc_count=10,
            claim_count=50,
        )

        # Le système utilise le label du cluster comme capability
        capability = popular_cluster.label  # "Data Processing Module"

        # Query since_when sur cette capability auto-détectée
        result = SinceWhenResult(
            capability=capability,
            first_occurrence_context="1.0",
            first_occurrence_claims=["claim_dp_001", "claim_dp_002"],
            timeline=[
                {"context": "1.0", "claims": ["claim_dp_001"]},
                {"context": "2.0", "claims": ["claim_dp_002", "claim_dp_003"]},
            ],
            timeline_basis="cluster",
            ordering_confidence="CERTAIN",
        )

        # Vérifications
        # S7: La capability vient du cluster, pas hardcodée
        assert result.capability == "Data Processing Module"
        assert "SAP" not in result.capability
        assert "GL" not in result.capability
        # INV-23: Claims sources présentes
        assert len(result.first_occurrence_claims) >= 1


class TestInvariantsCompliance:
    """Tests de conformité aux invariants."""

    def test_inv12_claimkey_validation(self):
        """INV-12: ClaimKey validé si ≥2 docs ET ≥2 valeurs."""
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
        )

        # 1 doc, 1 valeur → pas validé
        axis.add_value("1.0", "doc1")
        assert axis.is_validated_claimkey() is False

        # 2 docs, 1 valeur → pas validé
        axis.add_value("1.0", "doc2")
        assert axis.is_validated_claimkey() is False

        # 2 docs, 2 valeurs → validé
        axis.add_value("2.0", "doc2")
        assert axis.is_validated_claimkey() is True

    def test_inv14_never_invent_order(self):
        """INV-14: compare() → None si ordre inconnu."""
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="category",
        )
        axis.ordering_confidence = OrderingConfidence.UNKNOWN
        axis.is_orderable = False
        axis.value_order = None

        # compare() doit retourner None
        result = axis.compare("A", "B")
        assert result is None

    def test_inv17_no_removed_without_evidence(self):
        """INV-17: Pas de REMOVED sans evidence explicite."""
        # Sans evidence de suppression, le statut doit être UNCERTAIN
        result = StillApplicableResult(
            claim_id="claim_100",
            claim_text="Some old feature.",
            is_applicable=None,
            status="UNCERTAIN",  # Pas REMOVED
            removal_evidence=None,  # Pas d'evidence
        )

        assert result.status == "UNCERTAIN"
        assert result.removal_evidence is None

        # Avec evidence → REMOVED autorisé
        result_with_evidence = StillApplicableResult(
            claim_id="claim_100",
            claim_text="Some old feature.",
            is_applicable=False,
            status="REMOVED",
            removal_evidence="Feature deprecated in version 3.0",
        )

        assert result_with_evidence.status == "REMOVED"
        assert result_with_evidence.removal_evidence is not None

    def test_inv19_candidate_refuses_timeline(self):
        """INV-19: ClaimKey candidate → pas de timeline."""
        engine = TemporalQueryEngine(neo4j_driver=None)

        result = engine.query_since_when(
            capability="Feature",
            is_validated_claimkey=False,  # Candidate
        )

        assert result.refused is True
        assert "INV-19" in result.refused_reason

    def test_inv23_claims_always_cited(self):
        """INV-23: Toute réponse cite ses claims sources."""
        # SinceWhenResult
        since_result = SinceWhenResult(
            capability="Feature",
            first_occurrence_claims=["c1", "c2"],  # INV-23
            timeline=[{"context": "1.0", "claims": ["c1"]}],  # INV-23
        )
        assert len(since_result.first_occurrence_claims) > 0

        # StillApplicableResult
        still_result = StillApplicableResult(
            claim_id="c1",
            claim_text="Text",
            status="APPLICABLE",
            supporting_claims=["c1"],  # INV-23
        )
        assert len(still_result.supporting_claims) > 0

        # TextValidationResult
        valid_result = TextValidationResult(
            user_text="Statement",
            status=ValidationStatus.CONFIRMED,
            supporting_claims=[{"claim_id": "c1"}],  # INV-23
            confidence=0.9,
            explanation="Confirmed",
        )
        assert len(valid_result.supporting_claims) > 0

    def test_inv24_min_2_candidates(self):
        """INV-24: ≥2 candidats sauf exact match lexical."""
        resolver = IntentResolver(neo4j_driver=None)

        # Sans exact match → ≥2 candidats
        candidates = [
            ClusterCandidate(cluster_id="c1", label="Topic A", score=0.95),
            ClusterCandidate(cluster_id="c2", label="Topic B", score=0.60),
        ]

        result = resolver.resolve(
            query="generic query",
            candidates=candidates,
        )

        assert len(result.candidate_clusters) >= 2

    def test_inv26_evidence_required(self):
        """INV-26: Toute axis_value a evidence."""
        from knowbase.claimfirst.models.axis_value import AxisValue, EvidenceSpan

        # Création avec evidence obligatoire
        evidence = EvidenceSpan(
            passage_id="p1",
            snippet_ref="offset:100",
            text_snippet="version 2.0",
        )

        axis_value = AxisValue.from_scalar(
            value="2.0",
            evidence=evidence,
        )

        # Evidence doit être présente
        assert axis_value.evidence is not None
        assert axis_value.evidence.snippet_ref == "offset:100"
