# tests/claimfirst/test_qs_comparator.py
"""Tests — Moteur de comparaison cross-doc QS."""

import pytest

from knowbase.claimfirst.comparisons.qs_comparator import (
    ComparisonType,
    ComparisonResult,
    ValueDiff,
    compare_pair,
    find_comparable_pairs,
    compare_all,
)
from knowbase.claimfirst.models.comparability_verdict import ComparabilityLevel
from knowbase.claimfirst.models.question_signature import (
    QuestionSignature,
    QSValueType,
    QSExtractionMethod,
)
from knowbase.claimfirst.models.resolved_scope import ResolvedScope, ScopeAxis


def _make_qs(
    qs_id: str,
    claim_id: str,
    doc_id: str,
    dimension_key: str,
    dimension_id: str,
    value: str,
    value_normalized: str = None,
    value_type: QSValueType = QSValueType.NUMBER,
    operator: str = "=",
    scope_anchor_id: str = None,
    scope_anchor_type: str = "product",
    scope_anchor_label: str = None,
    scope_basis: str = "claim_explicit",
    scope_status: str = "resolved",
) -> QuestionSignature:
    """Helper pour créer une QS de test."""
    qs = QuestionSignature(
        qs_id=qs_id,
        claim_id=claim_id,
        doc_id=doc_id,
        question=f"What is the {dimension_key}?",
        dimension_key=dimension_key,
        dimension_id=dimension_id,
        value_type=value_type,
        extracted_value=value,
        value_normalized=value_normalized,
        operator=operator,
        extraction_method=QSExtractionMethod.LLM_LEVEL_B,
        confidence=0.9,
    )
    scope = ResolvedScope(
        primary_anchor_type=scope_anchor_type,
        primary_anchor_id=scope_anchor_id,
        primary_anchor_label=scope_anchor_label or scope_anchor_id,
        scope_basis=scope_basis,
        scope_status=scope_status,
        scope_confidence=0.90,
        comparable_for_dimension=scope_status != "ambiguous",
    )
    qs.set_resolved_scope(scope)
    return qs


# ── Cas 1 spec : Évolution (valeur différente, même scope, docs différents) ──

class TestEvolution:

    def test_evolution_same_scope_different_docs(self):
        """Cas 1 spec : même dimension, même scope, valeur 1.2→1.3."""
        qs_a = _make_qs(
            "qs_1", "c1", "doc_2022", "min_version", "qd_min_ver",
            "1.2", "1.2", QSValueType.VERSION, ">=",
            scope_anchor_id="ce_product_a", scope_anchor_label="ProductA",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "doc_2023", "min_version", "qd_min_ver",
            "1.3", "1.3", QSValueType.VERSION, ">=",
            scope_anchor_id="ce_product_a", scope_anchor_label="ProductA",
        )
        result = compare_pair(qs_a, qs_b)
        assert result is not None
        assert result.comparison_type == ComparisonType.EVOLUTION
        assert result.value_diff.value_a == "1.2"
        assert result.value_diff.value_b == "1.3"
        assert not result.value_diff.values_equal
        assert result.same_scope is True
        assert result.confidence >= 0.80

    def test_evolution_numeric_increase(self):
        """Valeur numérique augmente : 128→256 GB."""
        qs_a = _make_qs(
            "qs_1", "c1", "doc_old", "min_storage", "qd_stor",
            "128 GB", "128", QSValueType.NUMBER, ">=",
            scope_anchor_id="ce_prod", scope_anchor_label="Platform",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "doc_new", "min_storage", "qd_stor",
            "256 GB", "256", QSValueType.NUMBER, ">=",
            scope_anchor_id="ce_prod", scope_anchor_label="Platform",
        )
        result = compare_pair(qs_a, qs_b)
        assert result.comparison_type == ComparisonType.EVOLUTION
        assert result.value_diff.direction == "increased"

    def test_evolution_numeric_decrease(self):
        """Valeur numérique diminue : 90→30 jours."""
        qs_a = _make_qs(
            "qs_1", "c1", "doc_old", "retention_period", "qd_ret",
            "90 days", "90", QSValueType.NUMBER, "<=",
            scope_anchor_id="ce_prod",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "doc_new", "retention_period", "qd_ret",
            "30 days", "30", QSValueType.NUMBER, "<=",
            scope_anchor_id="ce_prod",
        )
        result = compare_pair(qs_a, qs_b)
        assert result.comparison_type == ComparisonType.EVOLUTION
        assert result.value_diff.direction == "decreased"


# ── Contradiction (même doc, même scope, valeurs différentes) ─────────

class TestContradiction:

    def test_contradiction_same_doc(self):
        """Même doc + même scope + valeurs différentes = contradiction."""
        qs_a = _make_qs(
            "qs_1", "c1", "doc_same", "max_connections", "qd_conn",
            "500", "500", QSValueType.NUMBER, "<=",
            scope_anchor_id="ce_prod",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "doc_same", "max_connections", "qd_conn",
            "1000", "1000", QSValueType.NUMBER, "<=",
            scope_anchor_id="ce_prod",
        )
        result = compare_pair(qs_a, qs_b)
        assert result is not None
        assert result.comparison_type == ComparisonType.CONTRADICTION
        assert result.confidence >= 0.85


# ── Convergence (scopes différents, même valeur) ──────────────────────

class TestConvergence:

    def test_convergence_different_scopes_same_value(self):
        """Scopes différents mais même valeur = convergence."""
        qs_a = _make_qs(
            "qs_1", "c1", "doc_1", "min_version", "qd_ver",
            "1.3", "1.3", QSValueType.VERSION, ">=",
            scope_anchor_id="ce_prod_a", scope_anchor_label="ProductA",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "doc_2", "min_version", "qd_ver",
            "1.3", "1.3", QSValueType.VERSION, ">=",
            scope_anchor_id="ce_prod_b", scope_anchor_label="ProductB",
        )
        result = compare_pair(qs_a, qs_b)
        assert result is not None
        assert result.comparison_type == ComparisonType.CONVERGENCE
        assert result.value_diff.values_equal is True


# ── Agreement (même scope, même valeur, docs différents) ──────────────

class TestAgreement:

    def test_agreement_strict(self):
        """Même scope strict + même valeur = accord cross-doc."""
        qs_a = _make_qs(
            "qs_1", "c1", "doc_1", "default_port", "qd_port",
            "443", "443", QSValueType.NUMBER, "=",
            scope_anchor_id="ce_prod",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "doc_2", "default_port", "qd_port",
            "443", "443", QSValueType.NUMBER, "=",
            scope_anchor_id="ce_prod",
        )
        result = compare_pair(qs_a, qs_b)
        assert result.comparison_type == ComparisonType.AGREEMENT
        assert result.confidence >= 0.90

    def test_agreement_loose_inherited_scope(self):
        """Scope hérité (LOOSE) + même valeur = accord avec confiance réduite."""
        qs_a = _make_qs(
            "qs_1", "c1", "doc_1", "timeout", "qd_timeout",
            "30", "30", QSValueType.NUMBER, "=",
            scope_anchor_id="ce_prod",
            scope_basis="document_context",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "doc_2", "timeout", "qd_timeout",
            "30", "30", QSValueType.NUMBER, "=",
            scope_anchor_id="ce_prod",
            scope_basis="document_context",
        )
        result = compare_pair(qs_a, qs_b)
        assert result.comparison_type == ComparisonType.AGREEMENT
        assert result.confidence < 0.95  # Réduite car LOOSE


# ── Non-comparable (devrait retourner None) ───────────────────────────

class TestNotComparable:

    def test_different_dimensions(self):
        """Dimensions différentes → None."""
        qs_a = _make_qs("qs_1", "c1", "d1", "min_version", "qd_ver", "1.2")
        qs_b = _make_qs("qs_2", "c2", "d2", "max_storage", "qd_stor", "256")
        result = compare_pair(qs_a, qs_b)
        assert result is None

    def test_operator_inversion(self):
        """Opérateurs inversés (>= vs <=) → None."""
        qs_a = _make_qs(
            "qs_1", "c1", "d1", "threshold", "qd_thr",
            "100", operator=">=", scope_anchor_id="ce_1",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "d2", "threshold", "qd_thr",
            "200", operator="<=", scope_anchor_id="ce_1",
        )
        result = compare_pair(qs_a, qs_b)
        assert result is None

    def test_ambiguous_scope(self):
        """Scope ambiguous → NEED_REVIEW, pas None."""
        qs_a = _make_qs(
            "qs_1", "c1", "d1", "min_ver", "qd_v",
            "1.2", scope_anchor_id="ce_1", scope_status="ambiguous",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "d2", "min_ver", "qd_v",
            "1.3", scope_anchor_id="ce_1", scope_status="resolved",
        )
        # are_comparable retourne NEED_REVIEW pour ambiguous
        # compare_pair ne retourne pas None car ce n'est pas NOT_COMPARABLE
        result = compare_pair(qs_a, qs_b)
        assert result is not None
        assert result.comparison_type == ComparisonType.UNDETERMINED


# ── find_comparable_pairs + compare_all ───────────────────────────────

class TestBatchComparison:

    def _make_corpus(self):
        """3 QS : 2 sur même dimension, 1 sur dimension différente."""
        return [
            _make_qs(
                "qs_1", "c1", "doc_1", "min_version", "qd_ver",
                "1.2", "1.2", QSValueType.VERSION, ">=",
                scope_anchor_id="ce_prod",
            ),
            _make_qs(
                "qs_2", "c2", "doc_2", "min_version", "qd_ver",
                "1.3", "1.3", QSValueType.VERSION, ">=",
                scope_anchor_id="ce_prod",
            ),
            _make_qs(
                "qs_3", "c3", "doc_3", "max_storage", "qd_stor",
                "512", "512", QSValueType.NUMBER, "<=",
                scope_anchor_id="ce_other",
            ),
        ]

    def test_find_comparable_pairs(self):
        """Seules les 2 QS sur même dimension forment une paire."""
        corpus = self._make_corpus()
        pairs = find_comparable_pairs(corpus)
        assert len(pairs) == 1
        ids = {pairs[0][0].qs_id, pairs[0][1].qs_id}
        assert ids == {"qs_1", "qs_2"}

    def test_compare_all(self):
        """compare_all produit 1 résultat EVOLUTION."""
        corpus = self._make_corpus()
        results = compare_all(corpus)
        assert len(results) == 1
        assert results[0].comparison_type == ComparisonType.EVOLUTION
        assert results[0].dimension_key == "min_version"

    def test_compare_all_empty(self):
        """Corpus vide → pas de résultats."""
        results = compare_all([])
        assert len(results) == 0

    def test_compare_all_singletons(self):
        """Chaque dimension n'a qu'une QS → pas de paires."""
        corpus = [
            _make_qs("qs_1", "c1", "d1", "dim_a", "qd_a", "v1"),
            _make_qs("qs_2", "c2", "d2", "dim_b", "qd_b", "v2"),
        ]
        results = compare_all(corpus)
        assert len(results) == 0


# ── ValueDiff ─────────────────────────────────────────────────────────

class TestValueDiff:

    def test_to_dict(self):
        """ComparisonResult.to_dict() sérialise correctement."""
        qs_a = _make_qs(
            "qs_1", "c1", "d1", "min_ver", "qd_v",
            "1.2", "1.2", QSValueType.VERSION, ">=",
            scope_anchor_id="ce_1",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "d2", "min_ver", "qd_v",
            "1.3", "1.3", QSValueType.VERSION, ">=",
            scope_anchor_id="ce_1",
        )
        result = compare_pair(qs_a, qs_b)
        d = result.to_dict()
        assert d["comparison_type"] == "EVOLUTION"
        assert d["value_a"] == "1.2"
        assert d["value_b"] == "1.3"
        assert d["same_scope"] is True
        assert "dimension_key" in d

    def test_boolean_evolution(self):
        """Booléen enabled→disabled = évolution."""
        qs_a = _make_qs(
            "qs_1", "c1", "d1", "feature_default", "qd_feat",
            "enabled", value_type=QSValueType.BOOLEAN,
            scope_anchor_id="ce_1",
        )
        qs_b = _make_qs(
            "qs_2", "c2", "d2", "feature_default", "qd_feat",
            "disabled", value_type=QSValueType.BOOLEAN,
            scope_anchor_id="ce_1",
        )
        result = compare_pair(qs_a, qs_b)
        assert result.comparison_type == ComparisonType.EVOLUTION
        assert not result.value_diff.values_equal
