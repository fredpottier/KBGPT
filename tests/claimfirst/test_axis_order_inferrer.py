# tests/claimfirst/test_axis_order_inferrer.py
"""
Tests pour AxisOrderInferrer.

INV-14: Si ordre inconnu, value_order = None (jamais inventer)
"""

import pytest

from knowbase.claimfirst.axes.axis_order_inferrer import (
    AxisOrderInferrer,
    OrderInferenceResult,
)
from knowbase.claimfirst.models.applicability_axis import (
    OrderingConfidence,
    OrderType,
)


@pytest.fixture
def inferrer():
    """Crée un inferrer."""
    return AxisOrderInferrer()


class TestAxisOrderInferrer:
    """Tests pour AxisOrderInferrer."""

    def test_infer_certain_semver(self, inferrer):
        """Infère ordre CERTAIN pour versions semver."""
        values = ["1.0", "2.0", "1.5", "3.0"]

        result = inferrer.infer_order("release_id", values)

        assert result.is_orderable is True
        assert result.confidence == OrderingConfidence.CERTAIN
        assert result.order_type == OrderType.TOTAL
        assert result.inferred_order == ["1.0", "1.5", "2.0", "3.0"]

    def test_infer_certain_years(self, inferrer):
        """Infère ordre CERTAIN pour années."""
        values = ["2022", "2020", "2023", "2021"]

        result = inferrer.infer_order("year", values)

        assert result.is_orderable is True
        assert result.confidence == OrderingConfidence.CERTAIN
        assert result.inferred_order == ["2020", "2021", "2022", "2023"]

    def test_infer_certain_numeric(self, inferrer):
        """Infère ordre CERTAIN pour nombres simples."""
        values = ["3", "1", "2"]

        result = inferrer.infer_order("level", values)

        assert result.is_orderable is True
        assert result.confidence == OrderingConfidence.CERTAIN
        assert result.inferred_order == ["1", "2", "3"]

    def test_infer_certain_sap_year_fps(self, inferrer):
        """Infère ordre CERTAIN pour années SAP avec FPS."""
        values = ["2021 FPS02", "2021", "2021 FPS01", "2022"]

        result = inferrer.infer_order("release_id", values)

        assert result.is_orderable is True
        assert result.confidence == OrderingConfidence.CERTAIN
        assert result.inferred_order == ["2021", "2021 FPS01", "2021 FPS02", "2022"]

    def test_infer_inferred_roman(self, inferrer):
        """Infère ordre INFERRED pour chiffres romains."""
        values = ["III", "I", "II"]

        result = inferrer.infer_order("phase", values)

        assert result.is_orderable is True
        assert result.confidence == OrderingConfidence.INFERRED
        assert result.inferred_order == ["I", "II", "III"]

    def test_infer_inferred_ordinal_words(self, inferrer):
        """Infère ordre INFERRED pour mots ordinaux."""
        values = ["second", "first", "third"]

        result = inferrer.infer_order("stage", values)

        assert result.is_orderable is True
        assert result.confidence == OrderingConfidence.INFERRED
        assert result.inferred_order == ["first", "second", "third"]

    def test_infer_inferred_edition(self, inferrer):
        """Infère ordre INFERRED pour éditions."""
        values = ["enterprise", "standard", "professional"]

        result = inferrer.infer_order("edition", values)

        assert result.is_orderable is True
        assert result.confidence == OrderingConfidence.INFERRED
        # standard < professional < enterprise
        assert result.inferred_order == ["standard", "professional", "enterprise"]

    def test_infer_unknown_mixed_values(self, inferrer):
        """INV-14: Retourne UNKNOWN pour valeurs mixtes."""
        values = ["alpha", "2.0", "beta", "1.0"]

        result = inferrer.infer_order("version", values)

        # Ne peut pas déterminer l'ordre
        assert result.confidence == OrderingConfidence.UNKNOWN
        assert result.inferred_order is None  # INV-14

    def test_infer_unknown_arbitrary_strings(self, inferrer):
        """INV-14: Retourne UNKNOWN pour strings arbitraires."""
        values = ["red", "blue", "green"]

        result = inferrer.infer_order("color", values)

        assert result.confidence == OrderingConfidence.UNKNOWN
        assert result.inferred_order is None  # INV-14

    def test_never_invent_order(self, inferrer):
        """INV-14: Ne jamais inventer un ordre."""
        # Valeurs qui ressemblent à un ordre mais ne matchent aucun pattern
        values = ["release-a", "release-b", "release-c"]

        result = inferrer.infer_order("release", values)

        # Même si ça ressemble à un ordre, on ne l'invente pas
        assert result.confidence == OrderingConfidence.UNKNOWN
        assert result.inferred_order is None

    def test_single_value_no_order(self, inferrer):
        """Une seule valeur = pas d'ordre possible."""
        values = ["2023"]

        result = inferrer.infer_order("year", values)

        assert result.is_orderable is False
        assert result.inferred_order is None

    def test_empty_values(self, inferrer):
        """Liste vide = pas d'ordre."""
        values = []

        result = inferrer.infer_order("any", values)

        assert result.is_orderable is False
        assert result.inferred_order is None

    def test_semver_with_prerelease(self, inferrer):
        """Gère semver avec tags prerelease."""
        values = ["1.0.0", "1.0.1", "2.0.0-beta"]

        result = inferrer.infer_order("version", values)

        assert result.is_orderable is True
        assert result.confidence == OrderingConfidence.CERTAIN
        # Le prerelease est ignoré pour l'ordre
        assert "1.0.0" in result.inferred_order
        assert "2.0.0-beta" in result.inferred_order


class TestOrderInferenceResult:
    """Tests pour OrderInferenceResult."""

    def test_dataclass_creation(self):
        """Vérifie la création du dataclass."""
        result = OrderInferenceResult(
            is_orderable=True,
            order_type=OrderType.TOTAL,
            confidence=OrderingConfidence.CERTAIN,
            inferred_order=["1", "2", "3"],
            reason="Numeric ordering",
        )

        assert result.is_orderable is True
        assert result.order_type == OrderType.TOTAL
        assert result.confidence == OrderingConfidence.CERTAIN
        assert result.inferred_order == ["1", "2", "3"]
        assert result.reason == "Numeric ordering"

    def test_unknown_result(self):
        """Vérifie le résultat UNKNOWN."""
        result = OrderInferenceResult(
            is_orderable=False,
            order_type=OrderType.NONE,
            confidence=OrderingConfidence.UNKNOWN,
            inferred_order=None,
            reason="Could not determine ordering",
        )

        assert result.is_orderable is False
        assert result.inferred_order is None
