# tests/claimfirst/test_latest_selector.py
"""
Tests pour LatestSelector.

INV-20: Authority unknown → ask, pas score
S5: Fallback axis ordering si primary axis CERTAIN
"""

import pytest

from knowbase.claimfirst.query.latest_selector import (
    LatestSelector,
    LatestPolicy,
    DocumentCandidate,
)
from knowbase.claimfirst.models.applicability_axis import (
    ApplicabilityAxis,
    OrderingConfidence,
    OrderType,
)
from knowbase.claimfirst.models.context_comparability import (
    DocumentAuthority,
    TieBreakingStrategy,
)


@pytest.fixture
def selector():
    """Crée un sélecteur avec politique par défaut."""
    return LatestSelector()


@pytest.fixture
def policy_with_fallback():
    """Politique autorisant le fallback axis."""
    return LatestPolicy(
        primary_axis="release_id",
        allow_axis_fallback=True,
        min_authority_known_ratio=0.5,
    )


@pytest.fixture
def policy_no_fallback():
    """Politique sans fallback axis."""
    return LatestPolicy(
        primary_axis="release_id",
        allow_axis_fallback=False,
        min_authority_known_ratio=0.5,
    )


@pytest.fixture
def certain_axis():
    """Axe avec ordre CERTAIN."""
    axis = ApplicabilityAxis.create_new(
        tenant_id="default",
        axis_key="release_id",
    )
    axis.is_orderable = True
    axis.ordering_confidence = OrderingConfidence.CERTAIN
    axis.value_order = ["2020", "2021", "2022", "2023"]
    return axis


@pytest.fixture
def unknown_axis():
    """Axe avec ordre UNKNOWN."""
    axis = ApplicabilityAxis.create_new(
        tenant_id="default",
        axis_key="release_id",
    )
    axis.is_orderable = False
    axis.ordering_confidence = OrderingConfidence.UNKNOWN
    axis.value_order = None
    return axis


class TestLatestSelector:
    """Tests pour LatestSelector."""

    def test_authority_based_selection(self, selector, certain_axis):
        """Sélection par autorité quand assez d'autorités connues."""
        candidates = [
            DocumentCandidate(
                doc_id="d1",
                context_value="2021",
                axis_key="release_id",
                authority=DocumentAuthority.OFFICIAL,
            ),
            DocumentCandidate(
                doc_id="d2",
                context_value="2023",
                axis_key="release_id",
                authority=DocumentAuthority.COMMUNITY,
            ),
        ]

        result = selector.select_latest(
            candidates=candidates,
            axes={"release_id": certain_axis},
        )

        # OFFICIAL > COMMUNITY donc d1 sélectionné
        assert result.selected_doc_id == "d1"
        assert result.fallback_used is False
        assert "authority" in result.why_selected.lower()

    def test_authority_tie_resolved_by_axis(self, selector, certain_axis):
        """Égalité d'autorité départagée par axe."""
        candidates = [
            DocumentCandidate(
                doc_id="d1",
                context_value="2021",
                axis_key="release_id",
                authority=DocumentAuthority.OFFICIAL,
            ),
            DocumentCandidate(
                doc_id="d2",
                context_value="2023",
                axis_key="release_id",
                authority=DocumentAuthority.OFFICIAL,
            ),
        ]

        result = selector.select_latest(
            candidates=candidates,
            axes={"release_id": certain_axis},
        )

        # Même autorité, 2023 > 2021 dans l'ordre de l'axe
        assert result.selected_doc_id == "d2"
        assert "tiebreak" in result.why_selected.lower()

    def test_authority_unknown_ask_user(self, selector, unknown_axis, policy_no_fallback):
        """INV-20: Authority unknown sans fallback → ask user."""
        candidates = [
            DocumentCandidate(
                doc_id="d1",
                context_value="2021",
                axis_key="release_id",
                authority=DocumentAuthority.UNKNOWN,
            ),
            DocumentCandidate(
                doc_id="d2",
                context_value="2023",
                axis_key="release_id",
                authority=DocumentAuthority.UNKNOWN,
            ),
        ]

        result = selector.select_latest(
            candidates=candidates,
            axes={"release_id": unknown_axis},
            policy=policy_no_fallback,
        )

        # Authority unknown + pas de fallback → ask user
        assert result.ask_user_needed is True
        assert result.selected_doc_id is None

    def test_axis_fallback_when_authority_unknown(self, selector, certain_axis, policy_with_fallback):
        """S5: Fallback axis quand >50% authority unknown et axis CERTAIN."""
        candidates = [
            DocumentCandidate(
                doc_id="d1",
                context_value="2021",
                axis_key="release_id",
                authority=DocumentAuthority.UNKNOWN,
            ),
            DocumentCandidate(
                doc_id="d2",
                context_value="2023",
                axis_key="release_id",
                authority=DocumentAuthority.UNKNOWN,
            ),
        ]

        result = selector.select_latest(
            candidates=candidates,
            axes={"release_id": certain_axis},
            policy=policy_with_fallback,
        )

        # Fallback to axis ordering car axis CERTAIN
        assert result.selected_doc_id == "d2"  # 2023 est le plus récent
        assert result.fallback_used is True
        assert "fallback" in result.why_selected.lower()

    def test_no_fallback_when_axis_unknown(self, selector, unknown_axis, policy_with_fallback):
        """Pas de fallback si axis ordering UNKNOWN."""
        candidates = [
            DocumentCandidate(
                doc_id="d1",
                context_value="2021",
                axis_key="release_id",
                authority=DocumentAuthority.UNKNOWN,
            ),
            DocumentCandidate(
                doc_id="d2",
                context_value="2023",
                axis_key="release_id",
                authority=DocumentAuthority.UNKNOWN,
            ),
        ]

        result = selector.select_latest(
            candidates=candidates,
            axes={"release_id": unknown_axis},
            policy=policy_with_fallback,
        )

        # Pas de fallback car axis UNKNOWN → ask user
        assert result.ask_user_needed is True

    def test_why_selected_always_present(self, selector, certain_axis):
        """why_selected toujours présent."""
        candidates = [
            DocumentCandidate(
                doc_id="d1",
                context_value="2021",
                axis_key="release_id",
                authority=DocumentAuthority.OFFICIAL,
            ),
        ]

        result = selector.select_latest(
            candidates=candidates,
            axes={"release_id": certain_axis},
        )

        assert result.why_selected is not None
        assert len(result.why_selected) > 0

    def test_empty_candidates(self, selector):
        """Gère le cas sans candidats."""
        result = selector.select_latest(
            candidates=[],
            axes={},
        )

        assert result.selected_doc_id is None
        assert "no candidates" in result.why_selected.lower()

    def test_filters_applied(self, selector, certain_axis):
        """Les filtres de politique sont appliqués."""
        policy = LatestPolicy(
            required_status="active",
            excluded_types=["draft"],
        )

        candidates = [
            DocumentCandidate(
                doc_id="d1",
                context_value="2023",
                axis_key="release_id",
                authority=DocumentAuthority.OFFICIAL,
                status="active",
                document_type="guide",
            ),
            DocumentCandidate(
                doc_id="d2",
                context_value="2024",
                axis_key="release_id",
                authority=DocumentAuthority.OFFICIAL,
                status="draft",  # Devrait être exclu
                document_type="draft",
            ),
        ]

        result = selector.select_latest(
            candidates=candidates,
            axes={"release_id": certain_axis},
            policy=policy,
        )

        # d2 exclu car status != active et type = draft
        assert result.selected_doc_id == "d1"


class TestLatestPolicy:
    """Tests pour LatestPolicy."""

    def test_default_policy(self):
        """Vérifie la politique par défaut."""
        policy = LatestPolicy()

        assert policy.primary_axis == "release_id"
        assert policy.allow_axis_fallback is True
        assert policy.min_authority_known_ratio == 0.5
        assert policy.on_tie == TieBreakingStrategy.ASK_USER

    def test_custom_policy(self):
        """Vérifie une politique personnalisée."""
        policy = LatestPolicy(
            primary_axis="year",
            authority_ranking=[DocumentAuthority.VERIFIED, DocumentAuthority.OFFICIAL],
            required_status="published",
            excluded_types=["deprecated"],
            on_tie=TieBreakingStrategy.LATEST_WINS,
            allow_axis_fallback=False,
        )

        assert policy.primary_axis == "year"
        assert policy.authority_ranking[0] == DocumentAuthority.VERIFIED
        assert policy.required_status == "published"
        assert policy.allow_axis_fallback is False

    def test_to_criteria(self):
        """Conversion en LatestSelectionCriteria."""
        policy = LatestPolicy(primary_axis="year")
        criteria = policy.to_criteria()

        assert criteria.primary_axis == "year"


class TestDocumentCandidate:
    """Tests pour DocumentCandidate."""

    def test_candidate_creation(self):
        """Vérifie la création d'un candidat."""
        candidate = DocumentCandidate(
            doc_id="d1",
            context_value="2023",
            axis_key="release_id",
        )

        assert candidate.doc_id == "d1"
        assert candidate.authority == DocumentAuthority.UNKNOWN  # Default
        assert candidate.metadata == {}  # Default

    def test_candidate_with_metadata(self):
        """Candidat avec métadonnées."""
        candidate = DocumentCandidate(
            doc_id="d1",
            context_value="2023",
            axis_key="release_id",
            metadata={"source": "official"},
        )

        assert candidate.metadata["source"] == "official"
