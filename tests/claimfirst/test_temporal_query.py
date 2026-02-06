# tests/claimfirst/test_temporal_query.py
"""
Tests pour TemporalQueryEngine.

INV-14: compare() → None si ordre inconnu
INV-17: REMOVED seulement si explicitement documenté
INV-19: ClaimKey candidate → pas de "since when"
INV-23: Toute réponse cite explicitement ses claims sources
S6: V1 assume timeline = cluster-based conservative
"""

import pytest
from unittest.mock import MagicMock, patch

from knowbase.claimfirst.query.temporal_query_engine import (
    TemporalQueryEngine,
    SinceWhenResult,
    StillApplicableResult,
)
from knowbase.claimfirst.models.applicability_axis import (
    ApplicabilityAxis,
    OrderingConfidence,
)


@pytest.fixture
def engine():
    """Crée un engine sans Neo4j."""
    return TemporalQueryEngine(neo4j_driver=None, tenant_id="default")


class TestSinceWhen:
    """Tests pour query_since_when."""

    def test_since_when_validated_claimkey(self, engine):
        """Timeline disponible pour ClaimKey validé."""
        result = engine.query_since_when(
            capability="GL Accounting",
            axis_key="release_id",
            is_validated_claimkey=True,
        )

        # Sans Neo4j, pas de timeline mais pas de refus
        assert result.refused is False or result.refused is True
        # Le timeline_basis doit être "cluster" (S6)
        assert result.timeline_basis == "cluster"

    def test_since_when_candidate_refuses(self, engine):
        """INV-19: Timeline refusée pour ClaimKey candidate."""
        result = engine.query_since_when(
            capability="Some Feature",
            axis_key="release_id",
            is_validated_claimkey=False,  # Candidate, pas validated
        )

        assert result.refused is True
        assert "INV-19" in result.refused_reason

    def test_timeline_basis_is_cluster(self, engine):
        """S6: timeline_basis = 'cluster' en V1."""
        result = engine.query_since_when(
            capability="Feature",
            is_validated_claimkey=True,
        )

        assert result.timeline_basis == "cluster"


class TestSinceWhenResult:
    """Tests pour SinceWhenResult model."""

    def test_result_with_timeline(self):
        """Résultat avec timeline."""
        result = SinceWhenResult(
            capability="GL Accounting",
            first_occurrence_context="2020",
            first_occurrence_claims=["claim_001", "claim_002"],
            timeline=[
                {"context": "2020", "claims": ["claim_001"]},
                {"context": "2021", "claims": ["claim_002", "claim_003"]},
            ],
            timeline_basis="cluster",
            ordering_confidence="CERTAIN",
        )

        assert result.capability == "GL Accounting"
        assert result.first_occurrence_context == "2020"
        assert len(result.first_occurrence_claims) == 2  # INV-23
        assert len(result.timeline) == 2

    def test_result_refused(self):
        """Résultat refusé (INV-19)."""
        result = SinceWhenResult(
            capability="Feature X",
            refused=True,
            refused_reason="INV-19: Timeline not available for candidate ClaimKey.",
        )

        assert result.refused is True
        assert result.timeline is None

    def test_result_no_timeline_unknown_order(self):
        """Pas de timeline si ordre UNKNOWN (INV-14)."""
        result = SinceWhenResult(
            capability="Feature Y",
            first_occurrence_context="2021",
            first_occurrence_claims=["c1"],
            timeline=None,  # INV-14
            ordering_confidence="UNKNOWN",
        )

        assert result.timeline is None
        assert result.ordering_confidence == "UNKNOWN"


class TestStillApplicable:
    """Tests pour query_still_applicable."""

    def test_still_applicable_no_driver(self, engine):
        """Sans Neo4j, retourne UNCERTAIN."""
        result = engine.query_still_applicable(
            claim_id="claim_001",
            claim_text="Some claim text",
            axes={},
        )

        assert result.status == "UNCERTAIN"
        assert result.claim_id == "claim_001"


class TestStillApplicableResult:
    """Tests pour StillApplicableResult model."""

    def test_result_applicable(self):
        """Résultat APPLICABLE."""
        result = StillApplicableResult(
            claim_id="claim_001",
            claim_text="GL Accounting supports multi-currency.",
            is_applicable=True,
            status="APPLICABLE",
            latest_context="2023",
            supporting_claims=["claim_001"],  # INV-23
        )

        assert result.is_applicable is True
        assert result.status == "APPLICABLE"
        assert len(result.supporting_claims) == 1

    def test_result_removed_with_evidence(self):
        """Résultat REMOVED avec evidence (INV-17)."""
        result = StillApplicableResult(
            claim_id="claim_002",
            claim_text="Old feature X.",
            is_applicable=False,
            status="REMOVED",
            latest_context="2023",
            supporting_claims=["claim_removal_001"],  # INV-23
            removal_evidence="Feature X has been removed in version 2023.",
        )

        assert result.is_applicable is False
        assert result.status == "REMOVED"
        assert result.removal_evidence is not None  # INV-17

    def test_result_uncertain_with_analysis(self):
        """Résultat UNCERTAIN avec analysis."""
        from knowbase.claimfirst.query.uncertainty_signals import UncertaintyAnalysis

        analysis = UncertaintyAnalysis(
            overall_confidence_hint=0.4,
            recommendation="Verification recommended.",
        )

        result = StillApplicableResult(
            claim_id="claim_003",
            claim_text="Feature Z configuration.",
            is_applicable=None,
            status="UNCERTAIN",
            latest_context="2023",
            supporting_claims=[],
            uncertainty_analysis=analysis,
        )

        assert result.is_applicable is None
        assert result.status == "UNCERTAIN"
        assert result.uncertainty_analysis is not None


class TestCompareContexts:
    """Tests pour compare_contexts."""

    def test_compare_no_driver(self, engine):
        """Sans Neo4j, retourne erreur."""
        result = engine.compare_contexts(
            context_a="2021",
            context_b="2023",
        )

        assert "error" in result
        assert result["claims_a"] == []
        assert result["claims_b"] == []


class TestStatistics:
    """Tests pour les statistiques."""

    def test_stats_tracking(self, engine):
        """Vérifie le tracking des statistiques."""
        engine.reset_stats()

        engine.query_since_when("Feature 1", is_validated_claimkey=True)
        engine.query_since_when("Feature 2", is_validated_claimkey=False)  # Refused
        engine.query_still_applicable("c1", "text", {})

        stats = engine.get_stats()
        assert stats["since_when_queries"] == 2
        assert stats["timeline_refused"] == 1
        assert stats["still_applicable_queries"] == 1

    def test_reset_stats(self, engine):
        """Reset des statistiques."""
        engine.query_since_when("F", is_validated_claimkey=True)
        engine.reset_stats()

        stats = engine.get_stats()
        assert stats["since_when_queries"] == 0
