"""
Tests pour PointerValidator - Validation 3 niveaux des concepts pointés.

Ref: Plan Pointer-Based Extraction (2026-01-27)

Tests couverts:
- Niveau 1: Score lexical (tokens + patterns valeur)
- Niveau 2: Type markers (PRESCRIPTIVE → must/shall/required)
- Niveau 3: Value patterns (version, percentage, size)
- Batch validation
- Edge cases
"""

import pytest
from knowbase.stratified.pass1.pointer_validator import (
    ValidationStatus,
    AbstainReason,
    ValidationResult,
    PointerValidationStats,
    PointerValidator,
    validate_pointer_concept,
    reconstruct_exact_quote,
)
from knowbase.stratified.pass1.assertion_unit_indexer import (
    AssertionUnitIndexer,
    UnitIndexResult,
    AssertionUnit,
)


class TestValidationResult:
    """Tests pour ValidationResult."""

    def test_is_valid_for_valid(self):
        """VALID doit retourner is_valid=True."""
        result = ValidationResult(status=ValidationStatus.VALID, score=2.0)
        assert result.is_valid is True

    def test_is_valid_for_downgrade(self):
        """DOWNGRADE doit retourner is_valid=True."""
        result = ValidationResult(
            status=ValidationStatus.DOWNGRADE,
            score=1.5,
            new_type="DEFINITIONAL"
        )
        assert result.is_valid is True

    def test_is_valid_for_abstain(self):
        """ABSTAIN doit retourner is_valid=False."""
        result = ValidationResult(
            status=ValidationStatus.ABSTAIN,
            reason=AbstainReason.NO_LEXICAL_SUPPORT,
        )
        assert result.is_valid is False


class TestPointerValidatorLexical:
    """Tests pour le niveau 1: Score lexical."""

    @pytest.fixture
    def validator(self):
        return PointerValidator(lexical_threshold=1.5)

    def test_exact_token_match(self, validator):
        """Un token exact du label doit scorer +1.0."""
        result = validator.validate(
            concept_label="TLS version",
            concept_type="FACTUAL",
            unit_text="TLS 1.2 is required for all connections.",
        )
        # "TLS" match exact → +1.0, "version" pas dans le texte
        # Mais il y a un pattern valeur (1.2) → +1.0
        # Total: 2.0 ≥ 1.5 → VALID
        assert result.status == ValidationStatus.VALID
        assert result.score >= 1.5

    def test_value_pattern_scores(self, validator):
        """Un motif valeur doit scorer +1.0."""
        result = validator.validate(
            concept_label="encryption standard",
            concept_type="FACTUAL",
            unit_text="Use 256-bit encryption for data protection.",
        )
        # "encryption" match → +1.0
        # "256" est un pattern valeur → +1.0
        # Total: 2.0 ≥ 1.5 → VALID
        assert result.status == ValidationStatus.VALID

    def test_no_lexical_support_abstains(self, validator):
        """Sans support lexical, doit ABSTAIN."""
        result = validator.validate(
            concept_label="network bandwidth",
            concept_type="FACTUAL",
            unit_text="TLS 1.2 is required for all connections.",
        )
        # Aucun token de "network bandwidth" dans le texte
        # Score < 1.5 → ABSTAIN
        assert result.status == ValidationStatus.ABSTAIN
        assert result.reason == AbstainReason.NO_LEXICAL_SUPPORT

    def test_short_tokens_ignored(self, validator):
        """Les tokens courts (<3 chars) doivent être ignorés."""
        result = validator.validate(
            concept_label="at least one",
            concept_type="FACTUAL",
            unit_text="At least one connection is required.",
        )
        # "at" et "one" sont trop courts (len < 3)
        # Seul "least" pourrait matcher
        # Avec pattern valeur potentiel, le score peut varier
        # Ce test vérifie juste que le validator ne crash pas
        assert result.status in [ValidationStatus.VALID, ValidationStatus.ABSTAIN]

    def test_word_boundary_matching(self, validator):
        """Le matching doit être sur mots entiers."""
        result = validator.validate(
            concept_label="port number",
            concept_type="FACTUAL",
            unit_text="The report is generated daily.",
        )
        # "port" n'est PAS dans "report" en mot entier
        # Score devrait être bas → ABSTAIN
        assert result.status == ValidationStatus.ABSTAIN


class TestPointerValidatorTypeMarkers:
    """Tests pour le niveau 2: Type markers."""

    @pytest.fixture
    def validator(self):
        return PointerValidator(strict_type_markers=True)

    def test_prescriptive_with_must_valid(self, validator):
        """PRESCRIPTIVE avec 'must' reste VALID."""
        result = validator.validate(
            concept_label="TLS requirement",
            concept_type="PRESCRIPTIVE",
            unit_text="TLS 1.2 must be used for all connections.",
        )
        assert result.status == ValidationStatus.VALID
        assert result.new_type is None

    def test_prescriptive_with_shall_valid(self, validator):
        """PRESCRIPTIVE avec 'shall' reste VALID."""
        result = validator.validate(
            concept_label="data rest",
            concept_type="PRESCRIPTIVE",
            unit_text="All data shall be encrypted at rest.",
        )
        # "data" +1.0, "rest" +1.0 → score 2.0, "shall" → marker OK
        assert result.status == ValidationStatus.VALID

    def test_prescriptive_with_required_valid(self, validator):
        """PRESCRIPTIVE avec 'required' reste VALID."""
        result = validator.validate(
            concept_label="multi-factor authentication",
            concept_type="PRESCRIPTIVE",
            unit_text="Multi-factor authentication is required.",
        )
        # "multi-factor" ou "authentication" → score, "required" → marker OK
        assert result.status == ValidationStatus.VALID

    def test_prescriptive_without_marker_downgrades(self, validator):
        """PRESCRIPTIVE sans marqueur → DOWNGRADE vers DEFINITIONAL."""
        result = validator.validate(
            concept_label="TLS feature",
            concept_type="PRESCRIPTIVE",
            unit_text="TLS 1.2 provides secure connections.",
        )
        # Pas de must/shall/required → DOWNGRADE
        assert result.status == ValidationStatus.DOWNGRADE
        assert result.new_type == "DEFINITIONAL"

    def test_prescriptive_french_marker(self, validator):
        """PRESCRIPTIVE avec marqueur français ('doit') reste VALID."""
        result = validator.validate(
            concept_label="chiffrement obligatoire",
            concept_type="PRESCRIPTIVE",
            unit_text="Le chiffrement AES-256 doit être utilisé.",
        )
        assert result.status == ValidationStatus.VALID

    def test_non_prescriptive_not_checked(self, validator):
        """Les types non-PRESCRIPTIVE ne sont pas vérifiés pour markers."""
        result = validator.validate(
            concept_label="TLS feature",
            concept_type="DEFINITIONAL",
            unit_text="TLS 1.2 provides secure connections.",
        )
        # DEFINITIONAL n'a pas besoin de marqueurs prescriptifs
        assert result.status == ValidationStatus.VALID


class TestPointerValidatorValuePatterns:
    """Tests pour le niveau 3: Value patterns."""

    @pytest.fixture
    def validator(self):
        return PointerValidator()

    def test_version_pattern_present(self, validator):
        """Avec value_kind=version, le pattern doit être présent."""
        result = validator.validate(
            concept_label="TLS version",
            concept_type="FACTUAL",
            unit_text="TLS 1.2 is the minimum supported version.",
            value_kind="version",
        )
        # Pattern version (\d+\.\d+) présent → VALID
        assert result.status == ValidationStatus.VALID

    def test_version_pattern_missing(self, validator):
        """Avec value_kind=version, absence du pattern → ABSTAIN."""
        result = validator.validate(
            concept_label="TLS protocol",
            concept_type="FACTUAL",
            unit_text="TLS is the minimum supported protocol standard.",
            value_kind="version",
        )
        # "TLS" match +1.0, "protocol" match +1.0 → score 2.0 (lexical OK)
        # Mais pas de pattern version (pas de chiffre) → ABSTAIN
        assert result.status == ValidationStatus.ABSTAIN
        assert result.reason == AbstainReason.VALUE_PATTERN_MISMATCH

    def test_percentage_pattern(self, validator):
        """value_kind=percentage doit trouver le pattern %."""
        result = validator.validate(
            concept_label="uptime guarantee",
            concept_type="FACTUAL",
            unit_text="The service guarantees 99.9% uptime.",
            value_kind="percentage",
        )
        assert result.status == ValidationStatus.VALID

    def test_percentage_pattern_missing(self, validator):
        """value_kind=percentage sans % → ABSTAIN."""
        result = validator.validate(
            concept_label="uptime guarantee",
            concept_type="FACTUAL",
            unit_text="The service guarantees high uptime.",
            value_kind="percentage",
        )
        assert result.status == ValidationStatus.ABSTAIN

    def test_size_pattern(self, validator):
        """value_kind=size doit trouver GB/TB/MB."""
        result = validator.validate(
            concept_label="storage limit",
            concept_type="FACTUAL",
            unit_text="Maximum storage is 256 GB per user.",
            value_kind="size",
        )
        assert result.status == ValidationStatus.VALID

    def test_duration_pattern(self, validator):
        """value_kind=duration doit trouver les patterns temporels."""
        result = validator.validate(
            concept_label="session timeout",
            concept_type="FACTUAL",
            unit_text="Session timeout is 30 min after inactivity.",
            value_kind="duration",
        )
        assert result.status == ValidationStatus.VALID


class TestPointerValidatorBatch:
    """Tests pour la validation batch."""

    @pytest.fixture
    def validator(self):
        return PointerValidator()

    @pytest.fixture
    def unit_index(self):
        """Crée un index de test."""
        indexer = AssertionUnitIndexer(min_unit_length=10)

        result1 = indexer.index_docitem(
            docitem_id="test:doc:item1",
            text="TLS 1.2 must be used for all connections.",
            item_type="paragraph",
        )
        result2 = indexer.index_docitem(
            docitem_id="test:doc:item2",
            text="Data encryption is recommended.",
            item_type="paragraph",
        )

        return {
            "test:doc:item1": result1,
            "test:doc:item2": result2,
        }

    def test_batch_validation_valid(self, validator, unit_index):
        """La validation batch doit traiter plusieurs concepts."""
        concepts = [
            {
                "label": "TLS requirement",
                "type": "PRESCRIPTIVE",
                "docitem_id": "test:doc:item1",
                "unit_id": "U1",
            },
            {
                "label": "encryption recommendation",
                "type": "FACTUAL",
                "docitem_id": "test:doc:item2",
                "unit_id": "U1",
            },
        ]

        valid, abstained, stats = validator.validate_batch(concepts, unit_index)

        assert stats.total == 2
        assert stats.valid + stats.abstained + stats.downgraded == 2

    def test_batch_invalid_unit_id(self, validator, unit_index):
        """Un unit_id inexistant doit ABSTAIN."""
        concepts = [
            {
                "label": "unknown concept",
                "type": "FACTUAL",
                "docitem_id": "test:doc:item1",
                "unit_id": "U99",  # N'existe pas
            },
        ]

        valid, abstained, stats = validator.validate_batch(concepts, unit_index)

        assert stats.abstained == 1
        assert stats.abstain_invalid_unit == 1
        assert len(abstained) == 1

    def test_batch_unknown_docitem(self, validator, unit_index):
        """Un docitem_id inconnu doit ABSTAIN."""
        concepts = [
            {
                "label": "unknown concept",
                "type": "FACTUAL",
                "docitem_id": "unknown:doc:item",
                "unit_id": "U1",
            },
        ]

        valid, abstained, stats = validator.validate_batch(concepts, unit_index)

        assert stats.abstained == 1
        assert stats.abstain_invalid_unit == 1

    def test_batch_adds_exact_quote(self, validator, unit_index):
        """Les concepts validés doivent avoir exact_quote ajouté."""
        concepts = [
            {
                "label": "TLS requirement",
                "type": "PRESCRIPTIVE",
                "docitem_id": "test:doc:item1",
                "unit_id": "U1",
            },
        ]

        valid, _, _ = validator.validate_batch(concepts, unit_index)

        assert len(valid) > 0
        assert "exact_quote" in valid[0]
        assert "TLS 1.2 must be used" in valid[0]["exact_quote"]


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_unit_text(self):
        """Un texte d'unité vide doit ABSTAIN."""
        validator = PointerValidator()
        result = validator.validate(
            concept_label="test",
            concept_type="FACTUAL",
            unit_text="",
        )
        assert result.status == ValidationStatus.ABSTAIN
        assert result.reason == AbstainReason.EMPTY_UNIT

    def test_whitespace_only_unit_text(self):
        """Un texte avec seulement des espaces doit ABSTAIN."""
        validator = PointerValidator()
        result = validator.validate(
            concept_label="test",
            concept_type="FACTUAL",
            unit_text="   \n\t  ",
        )
        assert result.status == ValidationStatus.ABSTAIN
        assert result.reason == AbstainReason.EMPTY_UNIT

    def test_helper_validate_pointer_concept(self):
        """Le helper validate_pointer_concept doit fonctionner."""
        result = validate_pointer_concept(
            concept_label="TLS version",
            concept_type="FACTUAL",
            unit_text="TLS 1.2 is required.",
        )
        assert isinstance(result, ValidationResult)
        assert result.status in [ValidationStatus.VALID, ValidationStatus.ABSTAIN, ValidationStatus.DOWNGRADE]


class TestValidationStats:
    """Tests pour PointerValidationStats."""

    def test_valid_rate_calculation(self):
        """valid_rate doit être calculé correctement."""
        stats = PointerValidationStats(total=10, valid=7, abstained=3)
        assert stats.valid_rate == 0.7

    def test_abstain_rate_calculation(self):
        """abstain_rate doit être calculé correctement."""
        stats = PointerValidationStats(total=10, valid=7, abstained=3)
        assert stats.abstain_rate == 0.3

    def test_rates_with_zero_total(self):
        """Les rates avec total=0 doivent être 0."""
        stats = PointerValidationStats(total=0)
        assert stats.valid_rate == 0.0
        assert stats.abstain_rate == 0.0
