"""
Tests unitaires pour le Confidence Engine v2 - OSMOSE Answer+Proof

Ces tests valident que le Confidence Engine est:
- Deterministe: memes entrees = memes sorties
- Stable: pas de flapping entre etats
- Non "gadget metrique": les seuils ont un sens produit

Table de verite testee:
| E | C | O | M | S | EpistemicState |
|---|---|---|---|---|----------------|
| 0 | * | * | * | * | INCOMPLETE     |
| 1 | 1 | * | * | * | DEBATE         |
| 1 | 0 | 1 | * | * | INCOMPLETE     |
| 1 | 0 | 0 | 1 | * | INCOMPLETE     |
| 1 | 0 | 0 | 0 | 1 | ESTABLISHED    |
| 1 | 0 | 0 | 0 | 0 | PARTIAL        |
"""

import pytest
from knowbase.api.services.confidence_engine import (
    EpistemicState,
    ContractState,
    KGSignals,
    DomainSignals,
    ConfidenceResult,
    compute_epistemic_state,
    compute_contract_state,
    build_confidence_result,
    get_confidence_engine,
)


class TestEpistemicState:
    """Tests pour le calcul de l'etat epistemique."""

    def test_no_edges_returns_incomplete(self):
        """Pas de relations typees -> INCOMPLETE (ligne 1 truth table)."""
        signals = KGSignals(
            typed_edges_count=0,
            avg_conf=0.0,
            validated_ratio=0.0,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=0,
            expected_edges_missing_count=0,
        )
        state, rules = compute_epistemic_state(signals)
        assert state == EpistemicState.INCOMPLETE
        assert "NO_TYPED_EDGES" in rules

    def test_conflict_dominates_everything(self):
        """Le conflit l'emporte meme si toutes les autres metriques sont parfaites (ligne 2)."""
        signals = KGSignals(
            typed_edges_count=10,
            avg_conf=0.95,
            validated_ratio=1.0,
            conflicts_count=1,  # UN SEUL conflit
            orphan_concepts_count=0,
            independent_sources_count=5,
            expected_edges_missing_count=0,
        )
        state, rules = compute_epistemic_state(signals)
        assert state == EpistemicState.DEBATE
        assert "CONFLICT_DETECTED" in rules

    def test_orphans_return_incomplete(self):
        """Concepts orphelins -> INCOMPLETE (ligne 3)."""
        signals = KGSignals(
            typed_edges_count=5,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=2,  # Orphelins
            independent_sources_count=3,
            expected_edges_missing_count=0,
        )
        state, rules = compute_epistemic_state(signals)
        assert state == EpistemicState.INCOMPLETE
        assert "ORPHAN_CONCEPTS" in rules

    def test_missing_expected_edges_returns_incomplete(self):
        """Relations attendues manquantes -> INCOMPLETE (ligne 4)."""
        signals = KGSignals(
            typed_edges_count=5,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=3,
            expected_edges_missing_count=2,  # Manques
        )
        state, rules = compute_epistemic_state(signals)
        assert state == EpistemicState.INCOMPLETE
        assert "MISSING_EXPECTED_EDGES" in rules

    def test_established_happy_path(self):
        """Toutes conditions reunies -> ESTABLISHED (ligne 5)."""
        signals = KGSignals(
            typed_edges_count=8,
            avg_conf=0.85,  # >= 0.80
            validated_ratio=0.80,  # >= 0.70
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,  # >= 2
            expected_edges_missing_count=0,
        )
        state, rules = compute_epistemic_state(signals)
        assert state == EpistemicState.ESTABLISHED
        assert "STRONG_MATURITY" in rules
        assert "STRONG_CONFIDENCE" in rules
        assert "MULTI_SOURCES" in rules

    def test_partial_by_lack_of_sources(self):
        """Metriques OK mais une seule source -> PARTIAL (ligne 6)."""
        signals = KGSignals(
            typed_edges_count=8,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=1,  # Une seule source
            expected_edges_missing_count=0,
        )
        state, rules = compute_epistemic_state(signals)
        assert state == EpistemicState.PARTIAL
        assert "SINGLE_SOURCE" in rules

    def test_partial_by_low_maturity(self):
        """Maturity faible -> PARTIAL."""
        signals = KGSignals(
            typed_edges_count=8,
            avg_conf=0.85,
            validated_ratio=0.50,  # < 0.70
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=3,
            expected_edges_missing_count=0,
        )
        state, rules = compute_epistemic_state(signals)
        assert state == EpistemicState.PARTIAL
        assert "WEAK_MATURITY" in rules

    def test_partial_by_low_confidence(self):
        """Confidence faible -> PARTIAL."""
        signals = KGSignals(
            typed_edges_count=8,
            avg_conf=0.60,  # < 0.80
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=3,
            expected_edges_missing_count=0,
        )
        state, rules = compute_epistemic_state(signals)
        assert state == EpistemicState.PARTIAL
        assert "WEAK_CONFIDENCE" in rules


class TestContractState:
    """Tests pour le calcul de l'etat contractuel."""

    def test_covered_when_domains_match(self):
        """COVERED si matched_domains non vide."""
        signals = DomainSignals(
            in_scope_domains=["RGPD", "Finance"],
            matched_domains=["RGPD"],
        )
        assert compute_contract_state(signals) == ContractState.COVERED

    def test_out_of_scope_when_no_match(self):
        """OUT_OF_SCOPE si matched_domains vide."""
        signals = DomainSignals(
            in_scope_domains=["Finance", "RH"],
            matched_domains=[],
        )
        assert compute_contract_state(signals) == ContractState.OUT_OF_SCOPE

    def test_out_of_scope_does_not_change_epistemic(self):
        """OUT_OF_SCOPE ne modifie pas l'etat epistemique."""
        # Un etat ESTABLISHED reste ESTABLISHED meme hors scope
        kg_signals = KGSignals(
            typed_edges_count=8,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,
            expected_edges_missing_count=0,
        )
        domain_signals = DomainSignals(
            in_scope_domains=["Finance", "RH"],
            matched_domains=[],  # Pas de match
        )

        epistemic, _ = compute_epistemic_state(kg_signals)
        contract = compute_contract_state(domain_signals)

        # Les deux etats sont independants
        assert epistemic == EpistemicState.ESTABLISHED
        assert contract == ContractState.OUT_OF_SCOPE


class TestConfidenceResult:
    """Tests pour le resultat complet du Confidence Engine."""

    def test_build_result_with_established_covered(self):
        """Test du resultat pour ESTABLISHED + COVERED."""
        kg_signals = KGSignals(
            typed_edges_count=8,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,
            expected_edges_missing_count=0,
        )
        domain_signals = DomainSignals(
            in_scope_domains=["RGPD"],
            matched_domains=["RGPD"],
        )

        result = build_confidence_result(kg_signals, domain_signals)

        assert result.epistemic_state == EpistemicState.ESTABLISHED
        assert result.contract_state == ContractState.COVERED
        assert result.badge == "Reponse controlee"
        assert "8" in result.micro_text  # typed_edges_count
        assert len(result.warnings) == 0
        assert len(result.blockers) == 0

    def test_build_result_with_debate(self):
        """Test du resultat pour DEBATE."""
        kg_signals = KGSignals(
            typed_edges_count=5,
            avg_conf=0.75,
            validated_ratio=0.60,
            conflicts_count=2,
            orphan_concepts_count=0,
            independent_sources_count=3,
            expected_edges_missing_count=0,
        )
        domain_signals = DomainSignals(
            in_scope_domains=["RGPD"],
            matched_domains=["RGPD"],
        )

        result = build_confidence_result(kg_signals, domain_signals)

        assert result.epistemic_state == EpistemicState.DEBATE
        assert result.badge == "Reponse controversee"
        assert len(result.blockers) > 0
        assert "conflit" in result.blockers[0].lower()

    def test_build_result_with_partial_warnings(self):
        """Test des warnings pour PARTIAL."""
        kg_signals = KGSignals(
            typed_edges_count=5,
            avg_conf=0.75,
            validated_ratio=0.50,  # < 0.70
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=1,  # < 2
            expected_edges_missing_count=0,
        )
        domain_signals = DomainSignals(
            in_scope_domains=["RGPD"],
            matched_domains=["RGPD"],
        )

        result = build_confidence_result(kg_signals, domain_signals)

        assert result.epistemic_state == EpistemicState.PARTIAL
        assert len(result.warnings) >= 2  # maturity + sources

    def test_result_serialization(self):
        """Test de la serialisation to_dict()."""
        kg_signals = KGSignals(
            typed_edges_count=5,
            avg_conf=0.75,
            validated_ratio=0.60,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,
            expected_edges_missing_count=0,
        )
        domain_signals = DomainSignals(
            in_scope_domains=["RGPD"],
            matched_domains=["RGPD"],
        )

        result = build_confidence_result(kg_signals, domain_signals)
        data = result.to_dict()

        assert "epistemic_state" in data
        assert "contract_state" in data
        assert "badge" in data
        assert "kg_signals" in data
        assert data["kg_signals"]["typed_edges_count"] == 5


class TestConfidenceEngine:
    """Tests pour le service ConfidenceEngine."""

    def test_singleton_instance(self):
        """Test que get_confidence_engine retourne un singleton."""
        engine1 = get_confidence_engine()
        engine2 = get_confidence_engine()
        assert engine1 is engine2

    def test_evaluate_method(self):
        """Test de la methode evaluate()."""
        engine = get_confidence_engine()

        kg_signals = KGSignals(
            typed_edges_count=5,
            avg_conf=0.75,
            validated_ratio=0.60,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,
            expected_edges_missing_count=0,
        )
        domain_signals = DomainSignals(
            in_scope_domains=["RGPD"],
            matched_domains=["RGPD"],
        )

        result = engine.evaluate(kg_signals, domain_signals)

        assert isinstance(result, ConfidenceResult)
        assert result.epistemic_state in EpistemicState
        assert result.contract_state in ContractState

    def test_evaluate_from_dict(self):
        """Test de la methode evaluate_from_dict()."""
        engine = get_confidence_engine()

        kg_dict = {
            "typed_edges_count": 5,
            "avg_conf": 0.75,
            "validated_ratio": 0.60,
            "conflicts_count": 0,
            "orphan_concepts_count": 0,
            "independent_sources_count": 2,
            "expected_edges_missing_count": 0,
        }
        domain_dict = {
            "in_scope_domains": ["RGPD"],
            "matched_domains": ["RGPD"],
        }

        result = engine.evaluate_from_dict(kg_dict, domain_dict)

        assert isinstance(result, ConfidenceResult)
        assert result.epistemic_state == EpistemicState.PARTIAL


class TestDeterminism:
    """Tests pour garantir le determinisme du Confidence Engine."""

    def test_same_inputs_same_outputs(self):
        """Memes entrees = memes sorties (determinisme)."""
        kg_signals = KGSignals(
            typed_edges_count=7,
            avg_conf=0.82,
            validated_ratio=0.75,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,
            expected_edges_missing_count=0,
        )
        domain_signals = DomainSignals(
            in_scope_domains=["RGPD"],
            matched_domains=["RGPD"],
        )

        # Executer 10 fois
        results = [
            build_confidence_result(kg_signals, domain_signals)
            for _ in range(10)
        ]

        # Verifier que tous les resultats sont identiques
        first = results[0]
        for result in results[1:]:
            assert result.epistemic_state == first.epistemic_state
            assert result.contract_state == first.contract_state
            assert result.badge == first.badge
            assert result.rules_fired == first.rules_fired

    def test_edge_cases_boundary_values(self):
        """Test des valeurs limites (seuils exacts)."""
        # Exactement au seuil de ESTABLISHED
        signals_at_threshold = KGSignals(
            typed_edges_count=1,
            avg_conf=0.80,  # Exactement au seuil
            validated_ratio=0.70,  # Exactement au seuil
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,  # Exactement au seuil
            expected_edges_missing_count=0,
        )
        state, _ = compute_epistemic_state(signals_at_threshold)
        assert state == EpistemicState.ESTABLISHED

        # Juste en dessous du seuil
        signals_below = KGSignals(
            typed_edges_count=1,
            avg_conf=0.79,  # Juste en dessous
            validated_ratio=0.70,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,
            expected_edges_missing_count=0,
        )
        state, _ = compute_epistemic_state(signals_below)
        assert state == EpistemicState.PARTIAL
