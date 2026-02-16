# tests/claimfirst/applicability/test_canonical_and_policy.py
"""
Tests pour les nouvelles fonctionnalités Phase A + Phase B :
- compute_canonical_value (A2)
- Validation canonique via candidate_ids dans _parse_llm_response (A3)
- Persistence canonical via candidate_ids dans FrameAdapter (A4)
- PlausibilityValidator (A5)
- PolicyValidator (B3)
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrame,
    CandidateProfile,
    EvidenceUnit,
    FrameField,
    FrameFieldConfidence,
    ValueCandidate,
    compute_canonical_value,
)
from knowbase.claimfirst.applicability.validators import (
    PlausibilityValidator,
    PolicyValidator,
)
from knowbase.claimfirst.applicability.frame_adapter import FrameAdapter
from knowbase.claimfirst.applicability.frame_builder import FrameBuilder


# ============================================================================
# Test compute_canonical_value (A2)
# ============================================================================

class TestComputeCanonicalValue:
    """Tests pour compute_canonical_value()."""

    def test_named_version_strips_prefix(self):
        """'Edition 2025' → '2025' quand strip_prefixes contient 'Edition'."""
        result = compute_canonical_value(
            raw_value="Edition 2025",
            value_type="named_version",
            strip_prefixes=["Version", "Release", "Edition"],
        )
        assert result == "2025"

    def test_named_version_strips_release(self):
        """'Release 1809' → '1809'."""
        result = compute_canonical_value(
            raw_value="Release 1809",
            value_type="named_version",
            strip_prefixes=["Version", "Release"],
        )
        assert result == "1809"

    def test_named_version_strips_version(self):
        """'Version 3.2.1' → '3.2.1'."""
        result = compute_canonical_value(
            raw_value="Version 3.2.1",
            value_type="named_version",
            strip_prefixes=["Version"],
        )
        assert result == "3.2.1"

    def test_named_version_case_insensitive(self):
        """Le stripping est case-insensitive."""
        result = compute_canonical_value(
            raw_value="version 2023",
            value_type="named_version",
            strip_prefixes=["Version"],
        )
        assert result == "2023"

    def test_non_named_version_returns_none(self):
        """value_type != 'named_version' → None."""
        result = compute_canonical_value(
            raw_value="2023",
            value_type="numeric_identifier",
            strip_prefixes=["Version"],
        )
        assert result is None

    def test_no_strip_prefixes_returns_none(self):
        """strip_prefixes vide → None (pas de policy)."""
        result = compute_canonical_value(
            raw_value="Version 2023",
            value_type="named_version",
            strip_prefixes=[],
        )
        assert result is None

    def test_none_strip_prefixes_returns_none(self):
        """strip_prefixes=None → None."""
        result = compute_canonical_value(
            raw_value="Version 2023",
            value_type="named_version",
            strip_prefixes=None,
        )
        assert result is None

    def test_no_matching_prefix_returns_none(self):
        """Aucun préfixe ne matche → None (raw IS canonical)."""
        result = compute_canonical_value(
            raw_value="FPS01",
            value_type="named_version",
            strip_prefixes=["Version", "Release"],
        )
        assert result is None

    def test_only_prefix_no_remainder(self):
        """Valeur = juste le préfixe → pattern ne matche pas car pas d'espace + suite.
        Le regex exige prefix + whitespace + quelque chose, donc 'Version' seul ne matche pas."""
        result = compute_canonical_value(
            raw_value="Version",
            value_type="named_version",
            strip_prefixes=["Version"],
        )
        # "Version" seul ne matche pas le pattern "^Version\s+" → aucun stripping → None
        assert result is None


# ============================================================================
# Test validation canonique dans _parse_llm_response (A3)
# ============================================================================

class TestParseWithCanonical:
    """Tests pour _parse_llm_response avec candidate_ids et canonical."""

    def _make_profile_with_canonical(self):
        vc = ValueCandidate(
            candidate_id="VC:named_version:abc",
            raw_value="Edition 2025",
            value_type="named_version",
            unit_ids=["EU:0:0"],
            frequency=1,
            in_title=True,
        )
        vc.canonical_value = "2025"
        return CandidateProfile(
            doc_id="test",
            title="Test Doc",
            total_units=1,
            total_chars=100,
            value_candidates=[vc],
        )

    def test_candidate_ids_anchor_with_canonical(self):
        """Quand candidate_ids sont valides et le candidat a canonical_value, utiliser canonical."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = self._make_profile_with_canonical()

        response = json.dumps({
            "fields": [{
                "field_name": "release_id",
                "value_normalized": "Edition 2025",
                "display_label": "edition",
                "evidence_unit_ids": ["EU:0:0"],
                "candidate_ids": ["VC:named_version:abc"],
                "confidence": "high",
                "reasoning": "Found in title",
            }],
            "unknowns": [],
        })

        frame = builder._parse_llm_response(response, profile)
        assert len(frame.fields) == 1
        # La valeur doit être la canonical
        assert frame.fields[0].value_normalized == "2025"

    def test_fallback_raw_value_match(self):
        """Sans candidate_ids valides, fallback sur raw_value match."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = self._make_profile_with_canonical()

        response = json.dumps({
            "fields": [{
                "field_name": "release_id",
                "value_normalized": "Edition 2025",
                "display_label": "edition",
                "evidence_unit_ids": ["EU:0:0"],
                "candidate_ids": [],
                "confidence": "high",
                "reasoning": "Found in title",
            }],
            "unknowns": [],
        })

        frame = builder._parse_llm_response(response, profile)
        assert len(frame.fields) == 1
        assert frame.fields[0].value_normalized == "Edition 2025"

    def test_fallback_canonical_match(self):
        """Le LLM retourne la forme canonique → match via canonical_to_candidates."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = self._make_profile_with_canonical()

        response = json.dumps({
            "fields": [{
                "field_name": "release_id",
                "value_normalized": "2025",
                "display_label": "edition",
                "evidence_unit_ids": ["EU:0:0"],
                "candidate_ids": [],
                "confidence": "high",
                "reasoning": "Found in title",
            }],
            "unknowns": [],
        })

        frame = builder._parse_llm_response(response, profile)
        assert len(frame.fields) == 1
        assert frame.fields[0].value_normalized == "2025"

    def test_invented_value_rejected(self):
        """Valeur véritablement inventée → rejetée."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = self._make_profile_with_canonical()

        response = json.dumps({
            "fields": [{
                "field_name": "release_id",
                "value_normalized": "2024",
                "display_label": "edition",
                "evidence_unit_ids": ["EU:0:0"],
                "candidate_ids": [],
                "confidence": "high",
                "reasoning": "Guessed",
            }],
            "unknowns": [],
        })

        frame = builder._parse_llm_response(response, profile)
        assert len(frame.fields) == 0

    def test_abstain_low_confidence_no_anchor(self):
        """confidence=low + pas de candidate_ids valides → skip."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = self._make_profile_with_canonical()

        response = json.dumps({
            "fields": [{
                "field_name": "release_id",
                "value_normalized": "Edition 2025",
                "display_label": "edition",
                "evidence_unit_ids": ["EU:0:0"],
                "candidate_ids": [],
                "confidence": "low",
                "reasoning": "Weak signal",
            }],
            "unknowns": [],
        })

        frame = builder._parse_llm_response(response, profile)
        assert len(frame.fields) == 0


# ============================================================================
# Test FrameAdapter canonical persistence (A4)
# ============================================================================

class TestFrameAdapterCanonical:
    """Tests pour FrameAdapter avec canonical_value via candidate_ids."""

    def _make_profile_with_canonical(self):
        vc = ValueCandidate(
            candidate_id="VC:named_version:abc",
            raw_value="Release 2023",
            value_type="named_version",
            unit_ids=["EU:0:0"],
            frequency=1,
        )
        vc.canonical_value = "2023"
        return CandidateProfile(
            doc_id="test",
            title="Test",
            total_units=1,
            total_chars=100,
            value_candidates=[vc],
        )

    def test_update_doc_context_with_canonical(self):
        """update_document_context utilise canonical_value quand profile est fourni."""
        adapter = FrameAdapter()
        profile = self._make_profile_with_canonical()

        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[FrameField(
                field_name="release_id",
                value_normalized="Release 2023",
                display_label="release",
                evidence_unit_ids=["EU:0:0"],
                candidate_ids=["VC:named_version:abc"],
                confidence=FrameFieldConfidence.HIGH,
            )],
        )

        doc_context = MagicMock()
        doc_context.axis_values = {}
        doc_context.applicable_axes = []

        adapter.update_document_context(frame, doc_context, profile=profile)

        assert doc_context.axis_values["release_id"]["scalar_value"] == "2023"
        assert doc_context.axis_values["release_id"]["display_value"] == "Release 2023"

    def test_update_doc_context_without_profile(self):
        """Sans profile, utilise value_normalized directement."""
        adapter = FrameAdapter()

        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[FrameField(
                field_name="release_id",
                value_normalized="2023",
                display_label="release",
                evidence_unit_ids=["EU:0:0"],
                confidence=FrameFieldConfidence.HIGH,
            )],
        )

        doc_context = MagicMock()
        doc_context.axis_values = {}
        doc_context.applicable_axes = []

        adapter.update_document_context(frame, doc_context)

        assert doc_context.axis_values["release_id"]["scalar_value"] == "2023"
        assert doc_context.axis_values["release_id"]["display_value"] is None

    def test_frame_to_observations_with_canonical(self):
        """frame_to_observations utilise canonical_value quand profile est fourni."""
        adapter = FrameAdapter()
        profile = self._make_profile_with_canonical()

        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[FrameField(
                field_name="release_id",
                value_normalized="Release 2023",
                display_label="release",
                evidence_unit_ids=["EU:0:0"],
                candidate_ids=["VC:named_version:abc"],
                confidence=FrameFieldConfidence.HIGH,
            )],
        )

        observations = adapter.frame_to_observations(frame, profile=profile)
        assert len(observations) == 1
        assert observations[0].values_extracted == ["2023"]

    def test_frame_to_observations_without_canonical(self):
        """Sans canonical, utilise value_normalized."""
        adapter = FrameAdapter()

        vc = ValueCandidate(
            candidate_id="VC:numeric:abc",
            raw_value="2023",
            value_type="numeric_identifier",
            unit_ids=["EU:0:0"],
        )
        profile = CandidateProfile(
            doc_id="test", title="Test", total_units=1, total_chars=100,
            value_candidates=[vc],
        )

        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[FrameField(
                field_name="release_id",
                value_normalized="2023",
                evidence_unit_ids=["EU:0:0"],
                candidate_ids=["VC:numeric:abc"],
                confidence=FrameFieldConfidence.HIGH,
            )],
        )

        observations = adapter.frame_to_observations(frame, profile=profile)
        assert observations[0].values_extracted == ["2023"]


# ============================================================================
# Test PlausibilityValidator (A5)
# ============================================================================

class TestPlausibilityValidator:
    """Tests pour PlausibilityValidator."""

    def _make_units(self):
        return [
            EvidenceUnit(unit_id="EU:0:0", text="Active status.", passage_idx=0, sentence_idx=0),
        ]

    def _make_profile(self):
        return CandidateProfile(doc_id="test", total_units=1, total_chars=50)

    def test_rejects_iso_date_as_lifecycle_status(self):
        """lifecycle_status = '2024-01-15' → rejeté (date ISO n'est pas un statut)."""
        validator = PlausibilityValidator()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[FrameField(
                field_name="lifecycle_status",
                value_normalized="2024-01-15",
                evidence_unit_ids=["EU:0:0"],
                confidence=FrameFieldConfidence.HIGH,
            )],
        )

        result = validator.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 0
        assert any("Plausibility" in n for n in result.validation_notes)

    def test_keeps_valid_lifecycle_status(self):
        """lifecycle_status = 'active' → gardé."""
        validator = PlausibilityValidator()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[FrameField(
                field_name="lifecycle_status",
                value_normalized="active",
                evidence_unit_ids=["EU:0:0"],
                confidence=FrameFieldConfidence.HIGH,
            )],
        )

        result = validator.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 1

    def test_keeps_other_fields_untouched(self):
        """Les champs non-lifecycle_status ne sont pas affectés."""
        validator = PlausibilityValidator()
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[FrameField(
                field_name="release_id",
                value_normalized="2024-01-15",
                evidence_unit_ids=["EU:0:0"],
                confidence=FrameFieldConfidence.HIGH,
            )],
        )

        result = validator.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 1


# ============================================================================
# Test PolicyValidator (B3)
# ============================================================================

class TestPolicyValidator:
    """Tests pour PolicyValidator avec mock du DomainContext store."""

    def _make_units(self):
        return [
            EvidenceUnit(unit_id="EU:0:0", text="Test text.", passage_idx=0, sentence_idx=0),
        ]

    def _make_profile(self):
        return CandidateProfile(doc_id="test", total_units=1, total_chars=50)

    def _make_validator_with_policy(self, policy: dict) -> PolicyValidator:
        """Crée un PolicyValidator avec une policy pré-chargée (bypass DB)."""
        v = PolicyValidator(tenant_id="test")
        v._policy = policy
        return v

    def test_no_policy_passes_through(self):
        """Sans policy, tous les champs passent."""
        v = self._make_validator_with_policy({})
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[FrameField(
                field_name="release_id",
                value_normalized="2023",
                evidence_unit_ids=["EU:0:0"],
                confidence=FrameFieldConfidence.HIGH,
            )],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 1

    def test_excluded_axes_hard_reject(self):
        """excluded_axes → hard reject."""
        v = self._make_validator_with_policy({
            "excluded_axes": ["trial_phase", "model_generation"],
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="release_id", value_normalized="2023",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
                FrameField(field_name="trial_phase", value_normalized="Phase III",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 1
        assert result.fields[0].field_name == "release_id"
        assert any("REJECTED 'trial_phase'" in n for n in result.validation_notes)

    def test_expected_axes_soft_mode_keeps(self):
        """expected_axes en soft mode (défaut) → garde les axes hors expected avec note."""
        v = self._make_validator_with_policy({
            "expected_axes": ["release_id"],
            "strict_expected": False,
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="edition", value_normalized="Enterprise",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 1  # Gardé en soft mode
        assert any("NOTE 'edition'" in n for n in result.validation_notes)

    def test_expected_axes_strict_mode_rejects(self):
        """expected_axes en strict mode → rejette les axes hors expected."""
        v = self._make_validator_with_policy({
            "expected_axes": ["release_id"],
            "strict_expected": True,
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="edition", value_normalized="Enterprise",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 0
        assert any("REJECTED 'edition'" in n for n in result.validation_notes)

    def test_year_range_rejects_out_of_bounds(self):
        """year_range rejette les années hors bornes."""
        v = self._make_validator_with_policy({
            "year_range": {"min": 1990, "max_relative": 2},
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="publication_year", value_normalized="1918",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 0
        assert any("year 1918 outside" in n for n in result.validation_notes)

    def test_year_range_keeps_valid_year(self):
        """year_range garde les années dans les bornes."""
        v = self._make_validator_with_policy({
            "year_range": {"min": 1990, "max_relative": 2},
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="publication_year", value_normalized="2023",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 1

    def test_reject_patterns(self):
        """plausibility_overrides reject_patterns → rejète si match."""
        v = self._make_validator_with_policy({
            "plausibility_overrides": {
                "lifecycle_status": {
                    "reject_patterns": [r"^\d{4}-\d{2}-\d{2}$"],
                },
            },
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="lifecycle_status", value_normalized="2024-01-15",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 0

    def test_accept_patterns_rejects_non_matching(self):
        """accept_patterns: si définis ET aucun ne match → rejeter."""
        v = self._make_validator_with_policy({
            "plausibility_overrides": {
                "lifecycle_status": {
                    "accept_patterns": [r"^(active|deprecated|end_of_life)$"],
                },
            },
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="lifecycle_status", value_normalized="something_weird",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 0

    def test_accept_patterns_keeps_matching(self):
        """accept_patterns: si un pattern match → garder."""
        v = self._make_validator_with_policy({
            "plausibility_overrides": {
                "lifecycle_status": {
                    "accept_patterns": [r"^(active|deprecated|end_of_life)$"],
                },
            },
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="lifecycle_status", value_normalized="active",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 1

    def test_year_range_on_date_field_with_iso(self):
        """year_range s'applique aux champs _date si format ISO."""
        v = self._make_validator_with_policy({
            "year_range": {"min": 1990, "max_relative": 2},
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="effective_date", value_normalized="1850-01-01",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 0

    def test_year_range_does_not_apply_to_non_year_fields(self):
        """year_range ne s'applique pas aux champs non-year/non-date."""
        v = self._make_validator_with_policy({
            "year_range": {"min": 1990, "max_relative": 2},
        })
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(field_name="release_id", value_normalized="1809",
                           evidence_unit_ids=["EU:0:0"], confidence=FrameFieldConfidence.HIGH),
            ],
        )

        result = v.validate(frame, self._make_units(), self._make_profile())
        assert len(result.fields) == 1  # release_id n'est pas un champ year


# ============================================================================
# Test FRAME_BUILDER_SCHEMA (A1)
# ============================================================================

class TestFrameBuilderSchema:
    """Vérifie que le schema JSON est bien défini."""

    def test_schema_is_valid_json_schema(self):
        """Le schema est un dict JSON valide avec les clés required."""
        from knowbase.claimfirst.applicability.frame_builder import FRAME_BUILDER_SCHEMA

        assert isinstance(FRAME_BUILDER_SCHEMA, dict)
        assert FRAME_BUILDER_SCHEMA["type"] == "object"
        assert "fields" in FRAME_BUILDER_SCHEMA["properties"]
        assert "unknowns" in FRAME_BUILDER_SCHEMA["properties"]
        assert FRAME_BUILDER_SCHEMA["required"] == ["fields", "unknowns"]

    def test_field_item_schema(self):
        """Chaque field item a les bonnes propriétés required."""
        from knowbase.claimfirst.applicability.frame_builder import FRAME_BUILDER_SCHEMA

        field_schema = FRAME_BUILDER_SCHEMA["properties"]["fields"]["items"]
        assert "field_name" in field_schema["properties"]
        assert "candidate_ids" in field_schema["properties"]
        assert "confidence" in field_schema["properties"]
        assert field_schema["properties"]["confidence"]["enum"] == ["high", "medium", "low"]
