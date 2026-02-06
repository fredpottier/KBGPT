# tests/claimfirst/test_intent_resolver.py
"""
Tests pour IntentResolver.

INV-18: Disambiguation UI enrichie
INV-24: ≥2 candidats sauf exact match lexical (garde-fou)
C3: Garde-fou lexical, pas juste numérique
"""

import pytest

from knowbase.claimfirst.query.intent_resolver import (
    IntentResolver,
    TargetClaimIntent,
    DisambiguationOption,
    ClusterCandidate,
    DELTA_THRESHOLD,
    MIN_CONFIDENCE,
    MAX_SOFT_CLUSTERS,
)


@pytest.fixture
def resolver():
    """Crée un resolver sans Neo4j."""
    return IntentResolver(neo4j_driver=None, tenant_id="default")


@pytest.fixture
def sample_candidates():
    """Crée des candidats de test."""
    return [
        ClusterCandidate(
            cluster_id="c1",
            label="GL Accounting Configuration",
            score=0.95,
            entities=["GL Accounting", "Configuration"],
            facets=["Finance"],
            doc_count=5,
            claim_count=20,
            sample_claim_text="GL Accounting supports multi-currency.",
        ),
        ClusterCandidate(
            cluster_id="c2",
            label="Asset Accounting Setup",
            score=0.85,
            entities=["Asset Accounting", "Setup"],
            facets=["Finance"],
            doc_count=3,
            claim_count=12,
            sample_claim_text="Asset Accounting is integrated with GL.",
        ),
        ClusterCandidate(
            cluster_id="c3",
            label="Cost Center Management",
            score=0.75,
            entities=["Cost Center", "Management"],
            facets=["Controlling"],
            doc_count=4,
            claim_count=15,
            sample_claim_text="Cost Centers are assigned to organizational units.",
        ),
    ]


class TestIntentResolver:
    """Tests pour IntentResolver."""

    def test_disambiguation_forced_on_vague_query(self, resolver, sample_candidates):
        """INV-24: Disambiguation forcée sur query vague."""
        # Query vague qui ne mentionne rien explicitement
        result = resolver.resolve(
            query="accounting features",
            candidates=sample_candidates,
        )

        # Doit retourner ≥2 candidats car pas d'exact match
        assert len(result.candidate_clusters) >= 2
        assert result.exact_match is False

    def test_min_2_candidates_no_exact_match(self, resolver):
        """INV-24: Jamais 1 seul candidat sans exact match."""
        candidates = [
            ClusterCandidate(
                cluster_id="c1",
                label="Feature X",
                score=0.95,
                entities=["Feature X"],
            ),
            ClusterCandidate(
                cluster_id="c2",
                label="Feature Y",
                score=0.60,
                entities=["Feature Y"],
            ),
        ]

        # Query qui ne matche pas exactement
        result = resolver.resolve(
            query="some generic query",
            candidates=candidates,
        )

        # Malgré le delta > DELTA_THRESHOLD, on garde 2 candidats
        assert len(result.candidate_clusters) >= 2
        assert result.exact_match is False

    def test_single_candidate_with_exact_match(self, resolver):
        """C3: 1 candidat autorisé SEULEMENT avec exact match lexical."""
        candidates = [
            ClusterCandidate(
                cluster_id="c1",
                label="GL Accounting",
                score=0.95,
                entities=["GL Accounting", "Finance"],
            ),
            ClusterCandidate(
                cluster_id="c2",
                label="Other Topic",
                score=0.60,
                entities=["Other"],
            ),
        ]

        # Query avec mention explicite du label
        result = resolver.resolve(
            query="What is GL Accounting?",
            candidates=candidates,
        )

        # Exact match trouvé → 1 candidat autorisé
        assert result.exact_match is True
        assert len(result.candidate_clusters) == 1
        assert result.candidate_clusters[0] == "c1"
        assert result.selected_cluster_id == "c1"

    def test_exact_match_by_entity(self, resolver):
        """C3: Exact match via mention d'entité."""
        candidates = [
            ClusterCandidate(
                cluster_id="c1",
                label="Configuration Options",
                score=0.90,
                entities=["Multi-Currency", "Exchange Rates"],
            ),
            ClusterCandidate(
                cluster_id="c2",
                label="Other Topic",
                score=0.70,
                entities=["Something Else"],
            ),
        ]

        # Query mentionnant une entité
        result = resolver.resolve(
            query="How does multi-currency work?",
            candidates=candidates,
        )

        # Devrait reconnaître l'exact match via l'entité
        assert result.exact_match is True
        assert result.selected_cluster_id == "c1"

    def test_enriched_disambiguation_options(self, resolver, sample_candidates):
        """INV-18: Options de disambiguation enrichies."""
        result = resolver.resolve(
            query="vague query",
            candidates=sample_candidates,
        )

        # Vérifier que les options sont enrichies
        for option in result.disambiguation_options:
            assert option.cluster_id is not None
            assert option.label is not None
            assert option.sample_claim_text is not None  # INV-18
            assert isinstance(option.facet_names, list)  # INV-18
            assert isinstance(option.entity_names, list)  # INV-18
            assert option.doc_count >= 0  # INV-18

    def test_max_soft_clusters(self, resolver):
        """Limite à MAX_SOFT_CLUSTERS si pas d'exact match."""
        many_candidates = [
            ClusterCandidate(
                cluster_id=f"c{i}",
                label=f"Topic {i}",
                score=0.90 - i * 0.05,
            )
            for i in range(10)
        ]

        result = resolver.resolve(
            query="generic",
            candidates=many_candidates,
        )

        assert len(result.candidate_clusters) <= MAX_SOFT_CLUSTERS

    def test_empty_candidates(self, resolver):
        """Gère le cas sans candidats."""
        result = resolver.resolve(
            query="anything",
            candidates=[],
        )

        assert result.candidate_clusters == []
        assert result.disambiguation_needed is True

    def test_stats_tracking(self, resolver, sample_candidates):
        """Vérifie le tracking des statistiques."""
        resolver.reset_stats()

        resolver.resolve("query 1", sample_candidates)
        resolver.resolve("GL Accounting query", sample_candidates)  # Exact match

        stats = resolver.get_stats()
        assert stats["queries_resolved"] == 2
        assert stats["exact_matches"] >= 1


class TestDisambiguationOption:
    """Tests pour DisambiguationOption."""

    def test_option_creation(self):
        """Vérifie la création d'une option."""
        option = DisambiguationOption(
            cluster_id="c1",
            label="Test Cluster",
            sample_claim_text="This is a sample claim.",
            facet_names=["Facet A", "Facet B"],
            entity_names=["Entity 1", "Entity 2"],
            doc_count=5,
            scope_preview="5 documents, 20 claims",
        )

        assert option.cluster_id == "c1"
        assert option.sample_claim_text == "This is a sample claim."
        assert len(option.facet_names) == 2


class TestClusterCandidate:
    """Tests pour ClusterCandidate."""

    def test_candidate_creation(self):
        """Vérifie la création d'un candidat."""
        candidate = ClusterCandidate(
            cluster_id="c1",
            label="Test",
            score=0.85,
        )

        assert candidate.cluster_id == "c1"
        assert candidate.score == 0.85
        assert candidate.entities == []
        assert candidate.facets == []


class TestGardeFouLexical:
    """Tests spécifiques pour le garde-fou lexical (C3)."""

    def test_lexical_match_required_for_single(self, resolver):
        """Le score numérique seul ne suffit pas pour 1 candidat."""
        candidates = [
            ClusterCandidate(
                cluster_id="c1",
                label="ABC Feature",
                score=0.99,  # Très haut score
            ),
            ClusterCandidate(
                cluster_id="c2",
                label="XYZ Feature",
                score=0.50,  # Score bas
            ),
        ]

        # Query sans mention explicite
        result = resolver.resolve(
            query="something completely different",
            candidates=candidates,
        )

        # Malgré le delta de 0.49 > DELTA_THRESHOLD, pas de single candidate
        assert result.exact_match is False
        assert len(result.candidate_clusters) >= 2

    def test_partial_word_match_not_enough(self, resolver):
        """Un match partiel de mot ne suffit pas."""
        candidates = [
            ClusterCandidate(
                cluster_id="c1",
                label="Accounting Features",
                score=0.90,
            ),
            ClusterCandidate(
                cluster_id="c2",
                label="Other",
                score=0.70,
            ),
        ]

        # "count" apparaît dans "Accounting" mais ce n'est pas un exact match
        result = resolver.resolve(
            query="count something",
            candidates=candidates,
        )

        # Ne devrait pas être considéré comme exact match
        # (le label "Accounting Features" n'est pas dans "count something")
        assert result.exact_match is False

    def test_case_insensitive_match(self, resolver):
        """Le match est case-insensitive."""
        candidates = [
            ClusterCandidate(
                cluster_id="c1",
                label="GL ACCOUNTING",
                score=0.90,
            ),
            ClusterCandidate(
                cluster_id="c2",
                label="Other",
                score=0.70,
            ),
        ]

        result = resolver.resolve(
            query="what is gl accounting?",
            candidates=candidates,
        )

        assert result.exact_match is True
