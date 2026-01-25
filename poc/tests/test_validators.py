"""
Tests pour les validateurs du POC
"""

import pytest
from poc.models.schemas import (
    ConceptSitue,
    ConceptRole,
    Information,
    InfoType,
    Anchor
)
from poc.validators.frugality_guard import FrugalityGuard, FrugalityStatus
from poc.validators.anchor_validator import AnchorValidator


class TestFrugalityGuard:
    """Tests pour le coupe-circuit frugalite"""

    def setup_method(self):
        self.guard = FrugalityGuard()

    def _make_concepts(self, count: int) -> list:
        """Genere une liste de concepts"""
        return [
            ConceptSitue(
                name=f"Concept_{i}",
                role=ConceptRole.STANDARD,
                theme_ref="Test"
            )
            for i in range(count)
        ]

    def test_ok_normal_range(self):
        """Concepts dans la plage normale -> OK"""
        concepts = self._make_concepts(25)
        result = self.guard.validate(concepts)

        assert result.status == FrugalityStatus.OK
        assert result.is_valid is True
        assert result.concept_count == 25

    def test_fail_over_60(self):
        """Plus de 60 concepts -> FAIL"""
        concepts = self._make_concepts(65)
        result = self.guard.validate(concepts)

        assert result.status == FrugalityStatus.FAIL
        assert result.is_valid is False
        assert "sur-structuration" in result.message.lower()

    def test_warn_under_5(self):
        """Moins de 5 concepts -> WARN"""
        concepts = self._make_concepts(3)
        result = self.guard.validate(concepts)

        assert result.status == FrugalityStatus.WARN
        assert result.is_valid is True  # Warning, pas fail

    def test_hostile_success(self):
        """Document hostile avec <10 concepts -> SUCCESS_HOSTILE"""
        concepts = self._make_concepts(5)
        result = self.guard.validate(concepts, doc_type="HOSTILE")

        assert result.status == FrugalityStatus.SUCCESS_HOSTILE
        assert result.is_valid is True

    def test_hostile_fail_too_many(self):
        """Document hostile avec >=10 concepts -> FAIL"""
        concepts = self._make_concepts(15)
        result = self.guard.validate(concepts, doc_type="HOSTILE")

        assert result.status == FrugalityStatus.FAIL
        assert result.is_valid is False

    def test_validate_or_raise(self):
        """validate_or_raise leve une exception si FAIL"""
        concepts = self._make_concepts(70)

        with pytest.raises(ValueError) as exc_info:
            self.guard.validate_or_raise(concepts)

        assert "sur-structuration" in str(exc_info.value).lower()


class TestAnchorValidator:
    """Tests pour le validateur d'anchors"""

    def setup_method(self):
        self.validator = AnchorValidator()
        self.chunks = {
            "chunk_001": "Ceci est le premier chunk avec du contenu suffisant pour etre valide.",
            "chunk_002": "Deuxieme chunk avec encore plus de texte pour les tests de validation."
        }

    def test_valid_anchor(self):
        """Anchor valide -> success"""
        anchor = Anchor(chunk_id="chunk_001", start_char=0, end_char=50)
        is_valid, text = self.validator.validate_single(anchor, self.chunks)

        assert is_valid is True
        assert len(text) == 50

    def test_invalid_chunk_not_found(self):
        """Chunk inexistant -> fail"""
        anchor = Anchor(chunk_id="chunk_999", start_char=0, end_char=50)
        is_valid, error = self.validator.validate_single(anchor, self.chunks)

        assert is_valid is False
        assert "non trouve" in error

    def test_invalid_bounds(self):
        """Bornes invalides -> fail"""
        anchor = Anchor(chunk_id="chunk_001", start_char=50, end_char=30)
        is_valid, error = self.validator.validate_single(anchor, self.chunks)

        assert is_valid is False
        assert "start_char >= end_char" in error

    def test_invalid_too_short(self):
        """Texte trop court -> fail"""
        anchor = Anchor(chunk_id="chunk_001", start_char=0, end_char=5)
        is_valid, error = self.validator.validate_single(anchor, self.chunks)

        assert is_valid is False
        assert "trop court" in error

    def test_validate_all(self):
        """Validation de toutes les Information"""
        infos = [
            Information(
                info_type=InfoType.FACT,
                anchor=Anchor(chunk_id="chunk_001", start_char=0, end_char=50),
                concept_refs=["c1"],
                theme_ref="T1"
            ),
            Information(
                info_type=InfoType.FACT,
                anchor=Anchor(chunk_id="chunk_999", start_char=0, end_char=50),  # Invalid
                concept_refs=["c2"],
                theme_ref="T1"
            )
        ]

        result = self.validator.validate_all(infos, self.chunks)

        assert result.total_count == 2
        assert result.valid_count == 1
        assert result.invalid_count == 1
        assert result.success_rate == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
