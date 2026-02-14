# tests/claimfirst/applicability/test_frame_builder.py
"""Tests pour FrameBuilder (Layer C)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from knowbase.claimfirst.applicability.frame_builder import (
    FrameBuilder,
    ResolverPriorStatus,
    ROLE_TO_FIELD,
)
from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrame,
    CandidateProfile,
    EvidenceUnit,
    FrameField,
    FrameFieldConfidence,
    ValueCandidate,
)
from knowbase.claimfirst.models.subject_resolver_output import (
    AxisValueOutput,
    DiscriminatingRole,
    SupportEvidence,
)


def _make_units() -> list:
    """Crée des EvidenceUnits de test."""
    return [
        EvidenceUnit(unit_id="EU:0:0", text="Version 2023 is now available.", passage_idx=0, sentence_idx=0),
        EvidenceUnit(unit_id="EU:0:1", text="Release notes for 2023.", passage_idx=0, sentence_idx=1),
        EvidenceUnit(unit_id="EU:1:0", text="The Enterprise Edition is recommended.", passage_idx=1, sentence_idx=0),
    ]


def _make_profile() -> CandidateProfile:
    """Crée un CandidateProfile de test."""
    return CandidateProfile(
        doc_id="test_doc",
        title="Product Guide 2023",
        primary_subject="TestProduct",
        total_units=3,
        total_chars=200,
        value_candidates=[
            ValueCandidate(
                candidate_id="VC:named_version:abc",
                raw_value="Version 2023",
                value_type="named_version",
                unit_ids=["EU:0:0"],
                frequency=1,
                in_title=True,
                in_header_zone=True,
            ),
            ValueCandidate(
                candidate_id="VC:numeric_identifier:def",
                raw_value="2023",
                value_type="numeric_identifier",
                unit_ids=["EU:0:0", "EU:0:1"],
                frequency=2,
                in_title=True,
                in_header_zone=True,
            ),
        ],
        markers_by_category={"reference": 2},
    )


class TestFrameBuilderDeterministic:
    """Tests pour le fallback déterministe."""

    def test_deterministic_picks_best_candidate(self):
        """Le fallback déterministe choisit le meilleur candidat."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = _make_profile()
        units = _make_units()

        frame = builder.build(profile, units)

        assert frame.method == "deterministic_fallback"
        assert len(frame.fields) >= 1

        # Doit avoir release_id basé sur named_version (in_title)
        release = frame.get_field("release_id")
        assert release is not None
        assert release.value_normalized == "Version 2023"
        assert release.confidence == FrameFieldConfidence.HIGH

    def test_deterministic_empty_candidates(self):
        """Le fallback déterministe gère l'absence de candidats."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = CandidateProfile(doc_id="test", total_units=3, total_chars=100)
        units = _make_units()

        frame = builder.build(profile, units)

        assert frame.method == "no_candidates"
        assert len(frame.fields) == 0
        assert len(frame.unknowns) >= 1

    def test_deterministic_version_not_promoted_to_release(self):
        """version nue (ex: '2.0') n'est PAS promue en release_id sans LLM."""
        profile = CandidateProfile(
            doc_id="test",
            total_units=3,
            total_chars=200,
            value_candidates=[
                ValueCandidate(
                    candidate_id="VC:version:abc",
                    raw_value="2.0",
                    value_type="version",
                    unit_ids=["EU:0:0"],
                    frequency=3,
                    in_title=True,
                    cooccurs_with_subject=True,
                ),
            ],
        )

        builder = FrameBuilder(llm_client=None, use_llm=False)
        frame = builder.build(profile, _make_units())

        release = frame.get_field("release_id")
        # "2.0" est trop ambigu sans LLM → NE DOIT PAS devenir release_id
        assert release is None
        assert "version_ambiguous" in frame.unknowns

    def test_deterministic_numeric_identifier_goes_to_unknowns(self):
        """numeric_identifier est ambigu → unknowns en mode déterministe."""
        profile = CandidateProfile(
            doc_id="test",
            total_units=3,
            total_chars=200,
            value_candidates=[
                ValueCandidate(
                    candidate_id="VC:named_version:abc",
                    raw_value="Release 1809",
                    value_type="named_version",
                    unit_ids=["EU:0:0"],
                    frequency=1,
                    in_title=True,
                ),
                ValueCandidate(
                    candidate_id="VC:numeric_identifier:def",
                    raw_value="2023",
                    value_type="numeric_identifier",
                    unit_ids=["EU:0:1"],
                    frequency=1,
                    in_header_zone=True,
                ),
            ],
        )

        builder = FrameBuilder(llm_client=None, use_llm=False)
        frame = builder.build(profile, _make_units())

        release = frame.get_field("release_id")
        assert release is not None
        assert release.value_normalized == "Release 1809"
        # numeric_identifier ne crée pas de champ year en déterministe
        assert "numeric_identifier_ambiguous" in frame.unknowns


class TestFrameBuilderLLM:
    """Tests pour la construction LLM (via _parse_llm_response)."""

    def test_llm_valid_response(self):
        """Parse correctement une réponse LLM valide."""
        llm_response = json.dumps({
            "fields": [
                {
                    "field_name": "release_id",
                    "value_normalized": "2023",
                    "display_label": "version",
                    "evidence_unit_ids": ["EU:0:0", "EU:0:1"],
                    "candidate_ids": ["VC:numeric_identifier:def"],
                    "confidence": "high",
                    "reasoning": "Most frequent year in title and header"
                }
            ],
            "unknowns": ["edition"]
        })

        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = _make_profile()

        frame = builder._parse_llm_response(llm_response, profile)

        assert len(frame.fields) == 1
        assert frame.fields[0].value_normalized == "2023"
        assert frame.fields[0].field_name == "release_id"
        assert frame.unknowns == ["edition"]

    def test_llm_invented_value_rejected(self):
        """Les valeurs inventées par le LLM sont rejetées dans le parsing."""
        llm_response = json.dumps({
            "fields": [
                {
                    "field_name": "release_id",
                    "value_normalized": "2025",  # N'existe pas dans les candidats
                    "evidence_unit_ids": ["EU:0:0"],
                    "candidate_ids": ["VC:year:invented"],
                    "confidence": "high",
                }
            ],
            "unknowns": []
        })

        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = _make_profile()

        frame = builder._parse_llm_response(llm_response, profile)

        # La valeur "2025" n'est pas dans les candidats → rejetée
        assert len(frame.fields) == 0

    def test_llm_failure_falls_back_to_deterministic(self):
        """Si _build_with_llm lève une exception, fallback déterministe."""
        builder = FrameBuilder(llm_client=MagicMock(), use_llm=True)

        # Mock _build_with_llm pour simuler une erreur
        builder._build_with_llm = MagicMock(side_effect=Exception("API error"))

        profile = _make_profile()
        units = _make_units()

        frame = builder.build(profile, units)

        assert frame.method == "deterministic_fallback"
        assert len(frame.fields) >= 1

    def test_llm_invalid_json_falls_back(self):
        """Si le LLM retourne du JSON invalide, fallback via _parse_llm_response."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = _make_profile()

        frame = builder._parse_llm_response("This is not JSON", profile)

        assert frame.method == "llm_parse_error"
        assert len(frame.fields) == 0

    def test_llm_empty_frame_triggers_fallback(self):
        """Si le LLM retourne un frame vide, fallback déterministe."""
        builder = FrameBuilder(llm_client=MagicMock(), use_llm=True)

        # Mock _build_with_llm pour retourner un frame vide
        from knowbase.claimfirst.applicability.models import ApplicabilityFrame
        empty_frame = ApplicabilityFrame(
            doc_id="test_doc",
            fields=[],
            method="llm_evidence_locked",
        )
        builder._build_with_llm = MagicMock(return_value=empty_frame)

        profile = _make_profile()
        units = _make_units()

        frame = builder.build(profile, units)

        # Frame vide → fallback déterministe
        assert frame.method == "deterministic_fallback"
        assert len(frame.fields) >= 1

    def test_llm_response_with_markdown_fences(self):
        """Parse correctement si le LLM encapsule en markdown."""
        llm_response = "```json\n" + json.dumps({
            "fields": [
                {
                    "field_name": "year",
                    "value_normalized": "2023",
                    "evidence_unit_ids": ["EU:0:0"],
                    "candidate_ids": ["VC:numeric_identifier:def"],
                    "confidence": "medium",
                }
            ],
            "unknowns": []
        }) + "\n```"

        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = _make_profile()

        frame = builder._parse_llm_response(llm_response, profile)

        assert len(frame.fields) == 1
        assert frame.fields[0].value_normalized == "2023"


# ============================================================================
# Tests pour le contrat d'autorité (resolver priors)
# ============================================================================

def _make_axis_value(
    value_raw: str,
    role: DiscriminatingRole,
    confidence: float = 0.9,
    rationale: str = "test rationale",
) -> AxisValueOutput:
    """Helper pour créer un AxisValueOutput de test."""
    return AxisValueOutput(
        value_raw=value_raw,
        discriminating_role=role,
        confidence=confidence,
        rationale=rationale,
        support=SupportEvidence(),
    )


class TestResolverPriors:
    """Tests pour le contrat d'autorité SubjectResolver → FrameBuilder."""

    def test_resolver_revision_creates_release_id(self):
        """axis_value revision conf=0.9 → FrameField release_id HIGH."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        axis_values = [
            _make_axis_value("2023", DiscriminatingRole.REVISION, confidence=0.9),
        ]

        prior_fields, status = builder._resolve_priors(axis_values)

        assert status == ResolverPriorStatus.CONFIRMED
        assert len(prior_fields) == 1
        assert prior_fields[0].field_name == "release_id"
        assert prior_fields[0].value_normalized == "2023"
        assert prior_fields[0].confidence == FrameFieldConfidence.HIGH

    def test_resolver_temporal_creates_doc_year_not_release(self):
        """temporal → doc_year, PAS release_id."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        axis_values = [
            _make_axis_value("2023", DiscriminatingRole.TEMPORAL, confidence=0.85),
        ]

        prior_fields, status = builder._resolve_priors(axis_values)

        # Temporal seul ne produit pas CONFIRMED (pas de revision)
        assert status == ResolverPriorStatus.ABSENT
        assert len(prior_fields) == 1
        assert prior_fields[0].field_name == "doc_year"
        # Ne doit PAS produire release_id
        field_names = [f.field_name for f in prior_fields]
        assert "release_id" not in field_names

    def test_no_resolver_values_status_absent(self):
        """Pas d'axis_values → status ABSENT."""
        builder = FrameBuilder(llm_client=None, use_llm=False)

        prior_fields, status = builder._resolve_priors(None)
        assert status == ResolverPriorStatus.ABSENT
        assert prior_fields == []

        prior_fields2, status2 = builder._resolve_priors([])
        assert status2 == ResolverPriorStatus.ABSENT
        assert prior_fields2 == []

    def test_resolver_low_confidence_ignored(self):
        """axis_value conf=0.5 → ignoré (sous le seuil 0.7)."""
        builder = FrameBuilder(llm_client=None, use_llm=False)
        axis_values = [
            _make_axis_value("2023", DiscriminatingRole.REVISION, confidence=0.5),
        ]

        prior_fields, status = builder._resolve_priors(axis_values)

        assert status == ResolverPriorStatus.ABSENT
        assert len(prior_fields) == 0

    def test_absent_status_blocks_llm_release_id(self):
        """LLM produit release_id mais status ABSENT → rejeté."""
        builder = FrameBuilder(llm_client=None, use_llm=False)

        # Simuler un frame LLM qui a produit un release_id
        frame = ApplicabilityFrame(
            doc_id="test_doc",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="3.0",
                    confidence=FrameFieldConfidence.MEDIUM,
                    reasoning="bare decimal version found",
                ),
            ],
            method="llm_evidence_locked",
        )

        # Merge avec status ABSENT et pas de priors
        result = builder._merge_with_priors(
            frame, [], ResolverPriorStatus.ABSENT,
        )

        # Le release_id doit avoir été rejeté (pas de named_version/in_title)
        assert result.get_field("release_id") is None
        assert any("AuthorityContract: rejected" in n for n in result.validation_notes)

    def test_confirmed_prior_survives_llm_override_no_evidence(self):
        """LLM override sans evidence → rejeté, prior conservé."""
        builder = FrameBuilder(llm_client=None, use_llm=False)

        prior_fields = [
            FrameField(
                field_name="release_id",
                value_normalized="2023",
                display_label="revision",
                confidence=FrameFieldConfidence.HIGH,
                reasoning="SubjectResolver prior (revision, conf=0.90): from title",
            ),
        ]

        # Frame LLM qui essaie d'overrider avec une valeur différente SANS evidence
        frame = ApplicabilityFrame(
            doc_id="test_doc",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="2024",
                    confidence=FrameFieldConfidence.HIGH,
                    evidence_unit_ids=[],  # Pas d'evidence !
                    reasoning="LLM thinks 2024",
                ),
            ],
            method="llm_evidence_locked",
        )

        result = builder._merge_with_priors(
            frame, prior_fields, ResolverPriorStatus.CONFIRMED,
        )

        # Le prior doit survivre
        release = result.get_field("release_id")
        assert release is not None
        assert release.value_normalized == "2023"
        assert release.confidence == FrameFieldConfidence.HIGH
        assert any("rejected override" in n for n in result.validation_notes)

    def test_llm_override_with_evidence_accepted(self):
        """LLM override avec evidence_unit_ids → accepté MEDIUM."""
        builder = FrameBuilder(llm_client=None, use_llm=False)

        prior_fields = [
            FrameField(
                field_name="release_id",
                value_normalized="2023",
                display_label="revision",
                confidence=FrameFieldConfidence.HIGH,
                reasoning="SubjectResolver prior (revision, conf=0.90): from title",
            ),
        ]

        # Frame LLM qui override AVEC evidence
        frame = ApplicabilityFrame(
            doc_id="test_doc",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="2024",
                    confidence=FrameFieldConfidence.HIGH,
                    evidence_unit_ids=["EU:0:0", "EU:1:0"],  # Evidence fournie
                    reasoning="Found 2024 in body with strong context",
                ),
            ],
            method="llm_evidence_locked",
        )

        result = builder._merge_with_priors(
            frame, prior_fields, ResolverPriorStatus.CONFIRMED,
        )

        # L'override doit être accepté mais dégradé à MEDIUM
        release = result.get_field("release_id")
        assert release is not None
        assert release.value_normalized == "2024"
        assert release.confidence == FrameFieldConfidence.MEDIUM
        assert "resolver_disagreed" in release.reasoning
        assert any("resolver_disagreed" in n for n in result.validation_notes)

    def test_duplicate_revision_priors_deduped_by_evidence(self):
        """Deux revisions (ex: "2021" et "9.0") → celle avec le plus d'evidence gagne.

        Cas réel: "Document Version: 9.0" vs "SAP S/4HANA 2021" (208 mentions).
        """
        builder = FrameBuilder(llm_client=None, use_llm=False)

        # Le resolver retourne deux revisions
        axis_values = [
            _make_axis_value("2021", DiscriminatingRole.REVISION, confidence=1.0,
                             rationale="SAP S/4HANA 2021 in title"),
            _make_axis_value("9.0", DiscriminatingRole.REVISION, confidence=1.0,
                             rationale="Document Version: 9.0 in header"),
        ]

        # Units avec "2021" beaucoup plus fréquent que "9.0"
        units = [
            EvidenceUnit(unit_id="EU:0:0", text="Operations Guide for SAP S/4HANA 2021",
                         passage_idx=0, sentence_idx=0),
            EvidenceUnit(unit_id="EU:0:1", text="Document Version: 9.0 2025-07-23",
                         passage_idx=0, sentence_idx=1),
            EvidenceUnit(unit_id="EU:1:0", text="This guide describes SAP S/4HANA 2021 operations.",
                         passage_idx=1, sentence_idx=0),
            EvidenceUnit(unit_id="EU:2:0", text="SAP S/4HANA 2021 supports new features.",
                         passage_idx=2, sentence_idx=0),
            EvidenceUnit(unit_id="EU:3:0", text="Version for SAP S/4HANA 2021 SPS07",
                         passage_idx=3, sentence_idx=0),
        ]

        profile = CandidateProfile(
            doc_id="test_doc",
            title="Operations Guide for SAP S/4HANA 2021",
            primary_subject="SAP S/4HANA",
            total_units=5,
            total_chars=500,
            value_candidates=[
                ValueCandidate(
                    candidate_id="VC:numeric_identifier:2021",
                    raw_value="2021",
                    value_type="numeric_identifier",
                    unit_ids=["EU:0:0", "EU:1:0", "EU:2:0", "EU:3:0"],
                    frequency=208,
                    in_title=True,
                    cooccurs_with_subject=True,
                ),
                ValueCandidate(
                    candidate_id="VC:version:90",
                    raw_value="9.0",
                    value_type="version",
                    unit_ids=["EU:0:1"],
                    frequency=2,
                    in_header_zone=True,
                ),
            ],
        )

        prior_fields, status = builder._resolve_priors(axis_values)
        assert status == ResolverPriorStatus.CONFIRMED
        # Avant dedup: 2 priors release_id
        assert len(prior_fields) == 2

        # Link evidence
        builder._link_priors_to_evidence(prior_fields, units, profile)

        # "2021" doit avoir plus d'evidence que "9.0"
        field_2021 = [f for f in prior_fields if f.value_normalized == "2021"][0]
        field_90 = [f for f in prior_fields if f.value_normalized == "9.0"][0]
        assert len(field_2021.evidence_unit_ids) > len(field_90.evidence_unit_ids)

        # Après dedup: 1 seul prior release_id, c'est "2021"
        deduped = builder._deduplicate_priors(prior_fields)
        assert len(deduped) == 1
        assert deduped[0].value_normalized == "2021"
        assert deduped[0].field_name == "release_id"
