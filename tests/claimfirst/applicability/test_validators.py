# tests/claimfirst/applicability/test_validators.py
"""Tests pour la pipeline de validation (Layer D)."""

import pytest

from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrame,
    CandidateProfile,
    EvidenceUnit,
    FrameField,
    FrameFieldConfidence,
    ValueCandidate,
)
from knowbase.claimfirst.applicability.validators import (
    EvidenceIntegrityValidator,
    FrameValidationPipeline,
    LexicalSanityValidator,
    MetricContextValidator,
    NoEvidenceValidator,
    ValueConsistencyValidator,
)


def _make_units() -> list:
    """Crée des EvidenceUnits de test."""
    return [
        EvidenceUnit(unit_id="EU:0:0", text="This applies to version 2023.", passage_idx=0, sentence_idx=0),
        EvidenceUnit(unit_id="EU:0:1", text="The release is available now.", passage_idx=0, sentence_idx=1),
        EvidenceUnit(unit_id="EU:1:0", text="S/4HANA 2023 features include HA.", passage_idx=1, sentence_idx=0),
    ]


def _make_profile() -> CandidateProfile:
    """Crée un CandidateProfile de test."""
    return CandidateProfile(
        doc_id="test_doc",
        title="S/4HANA 2023 Guide",
        primary_subject="S/4HANA",
        total_units=3,
        total_chars=200,
        value_candidates=[
            ValueCandidate(
                candidate_id="VC:numeric_identifier:abc123",
                raw_value="2023",
                value_type="numeric_identifier",
                unit_ids=["EU:0:0", "EU:1:0"],
                frequency=2,
            ),
        ],
    )


class TestEvidenceIntegrityValidator:
    """Tests pour EvidenceIntegrityValidator."""

    def test_removes_invalid_unit_ids(self):
        """Supprime les unit_ids qui n'existent pas."""
        units = _make_units()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0", "EU:99:99", "EU:0:1"],
                ),
            ],
        )

        validator = EvidenceIntegrityValidator()
        result = validator.validate(frame, units, _make_profile())

        assert len(result.fields[0].evidence_unit_ids) == 2
        assert "EU:99:99" not in result.fields[0].evidence_unit_ids
        assert len(result.validation_notes) == 1

    def test_keeps_valid_unit_ids(self):
        """Garde les unit_ids valides intacts."""
        units = _make_units()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0", "EU:1:0"],
                ),
            ],
        )

        validator = EvidenceIntegrityValidator()
        result = validator.validate(frame, units, _make_profile())

        assert len(result.fields[0].evidence_unit_ids) == 2
        assert len(result.validation_notes) == 0


class TestNoEvidenceValidator:
    """Tests pour NoEvidenceValidator."""

    def test_rejects_field_without_evidence(self):
        """Rejette les champs sans evidence."""
        units = _make_units()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0"],
                ),
                FrameField(
                    field_name="edition",
                    value_normalized="Enterprise",
                    evidence_unit_ids=[],
                ),
            ],
        )

        validator = NoEvidenceValidator()
        result = validator.validate(frame, units, _make_profile())

        assert len(result.fields) == 1
        assert result.fields[0].field_name == "year"

    def test_keeps_field_with_evidence(self):
        """Garde les champs avec evidence."""
        units = _make_units()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = NoEvidenceValidator()
        result = validator.validate(frame, units, _make_profile())

        assert len(result.fields) == 1


class TestValueConsistencyValidator:
    """Tests pour ValueConsistencyValidator."""

    def test_keeps_value_in_candidates(self):
        """Garde les valeurs présentes dans les candidats."""
        units = _make_units()
        profile = _make_profile()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = ValueConsistencyValidator()
        result = validator.validate(frame, units, profile)

        assert len(result.fields) == 1
        assert result.fields[0].confidence != FrameFieldConfidence.LOW

    def test_degrades_invented_value(self):
        """Dégrade la confiance d'une valeur inventée."""
        units = _make_units()
        profile = _make_profile()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="2025",  # N'existe pas dans les candidats ni les units
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = ValueConsistencyValidator()
        result = validator.validate(frame, units, profile)

        assert len(result.fields) == 1
        assert result.fields[0].confidence == FrameFieldConfidence.LOW


class TestLexicalSanityValidator:
    """Tests pour LexicalSanityValidator."""

    def test_valid_year_passes(self):
        """Une année valide passe sans problème."""
        units = _make_units()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = LexicalSanityValidator()
        result = validator.validate(frame, units, _make_profile())

        assert result.fields[0].confidence != FrameFieldConfidence.LOW

    def test_invalid_year_degraded(self):
        """Une année invalide dégrade la confiance."""
        units = _make_units()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="not_a_year",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = LexicalSanityValidator()
        result = validator.validate(frame, units, _make_profile())

        assert result.fields[0].confidence == FrameFieldConfidence.LOW

    def test_value_too_long_degraded(self):
        """Une valeur trop longue dégrade la confiance."""
        units = _make_units()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="A" * 60,
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = LexicalSanityValidator()
        result = validator.validate(frame, units, _make_profile())

        assert result.fields[0].confidence == FrameFieldConfidence.LOW

    def test_version_with_product_name_degraded(self):
        """Version contenant le nom du produit dégrade la confiance."""
        units = _make_units()
        profile = _make_profile()
        profile.primary_subject = "S/4HANA"
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="SAP S/4HANA Cloud Private Edition 2025",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = LexicalSanityValidator()
        result = validator.validate(frame, units, profile)

        assert result.fields[0].confidence == FrameFieldConfidence.LOW


class TestMetricContextValidator:
    """Tests pour MetricContextValidator."""

    def test_rejects_high_version_number(self):
        """Rejette un release_id avec major >= 50 (probablement SLA)."""
        units = [
            EvidenceUnit(unit_id="EU:0:0", text="SLA guarantees 99.9% uptime.", passage_idx=0, sentence_idx=0),
        ]
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="99.9",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = MetricContextValidator()
        result = validator.validate(frame, units, _make_profile())

        assert len(result.fields) == 0  # Rejeté
        assert any("MetricContext" in n for n in result.validation_notes)

    def test_keeps_low_version_number(self):
        """Garde un release_id avec major < 50 (version légitime)."""
        units = [
            EvidenceUnit(unit_id="EU:0:0", text="Upgrade to 3.2.1 for new features.", passage_idx=0, sentence_idx=0),
        ]
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="version",
                    value_normalized="3.2.1",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = MetricContextValidator()
        result = validator.validate(frame, units, _make_profile())

        assert len(result.fields) == 1
        assert result.fields[0].confidence != FrameFieldConfidence.LOW

    def test_degrades_sla_context(self):
        """Dégrade la confiance si keywords SLA dans l'evidence."""
        units = [
            EvidenceUnit(unit_id="EU:0:0", text="The SLA for version 3.0 guarantees availability.", passage_idx=0, sentence_idx=0),
        ]
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="version",
                    value_normalized="3.0",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = MetricContextValidator()
        result = validator.validate(frame, units, _make_profile())

        assert len(result.fields) == 1
        assert result.fields[0].confidence == FrameFieldConfidence.LOW

    def test_ignores_non_version_fields(self):
        """N'affecte pas les champs qui ne sont pas version/release."""
        units = [
            EvidenceUnit(unit_id="EU:0:0", text="Published in 2023.", passage_idx=0, sentence_idx=0),
        ]
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="publication_year",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = MetricContextValidator()
        result = validator.validate(frame, units, _make_profile())

        assert len(result.fields) == 1

    def test_named_version_not_rejected(self):
        """Un named_version comme 'Release 2023' n'est pas rejeté (valeur non numérique pure)."""
        units = [
            EvidenceUnit(unit_id="EU:0:0", text="This applies to Release 2023.", passage_idx=0, sentence_idx=0),
        ]
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="Release 2023",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        validator = MetricContextValidator()
        result = validator.validate(frame, units, _make_profile())

        assert len(result.fields) == 1


class TestFrameValidationPipeline:
    """Tests pour la pipeline complète."""

    def test_full_pipeline(self):
        """La pipeline complète fonctionne de bout en bout."""
        units = _make_units()
        profile = _make_profile()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0", "EU:99:99"],
                ),
                FrameField(
                    field_name="edition",
                    value_normalized="Enterprise",
                    evidence_unit_ids=[],
                ),
            ],
        )

        pipeline = FrameValidationPipeline()
        result = pipeline.validate(frame, units, profile)

        # edition rejeté (NoEvidence), year gardé mais EU:99:99 supprimé
        assert len(result.fields) == 1
        assert result.fields[0].field_name == "year"
        assert "EU:99:99" not in result.fields[0].evidence_unit_ids
        assert len(result.validation_notes) >= 2
