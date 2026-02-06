# tests/claimfirst/applicability/test_frame_builder.py
"""Tests pour FrameBuilder (Layer C)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from knowbase.claimfirst.applicability.frame_builder import FrameBuilder
from knowbase.claimfirst.applicability.models import (
    CandidateProfile,
    EvidenceUnit,
    FrameFieldConfidence,
    ValueCandidate,
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
                candidate_id="VC:year:def",
                raw_value="2023",
                value_type="year",
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

    def test_deterministic_year_separate_from_release(self):
        """Le year est séparé du release_id si valeurs différentes."""
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
                    candidate_id="VC:year:def",
                    raw_value="2023",
                    value_type="year",
                    unit_ids=["EU:0:1"],
                    frequency=1,
                    in_header_zone=True,
                ),
            ],
        )

        builder = FrameBuilder(llm_client=None, use_llm=False)
        frame = builder.build(profile, _make_units())

        release = frame.get_field("release_id")
        year = frame.get_field("year")
        assert release is not None
        assert release.value_normalized == "Release 1809"
        assert year is not None
        assert year.value_normalized == "2023"


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
                    "candidate_ids": ["VC:year:def"],
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
                    "candidate_ids": ["VC:year:def"],
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
