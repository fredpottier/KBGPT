# tests/claimfirst/applicability/test_numeric_identifier.py
"""Tests pour le fix Level 3: numeric_identifier + identification_semantics."""

import json
from unittest.mock import MagicMock, patch

import pytest

from knowbase.claimfirst.applicability.candidate_miner import CandidateMiner
from knowbase.claimfirst.applicability.frame_builder import (
    FRAME_BUILDER_PROMPT,
    FrameBuilder,
)
from knowbase.claimfirst.applicability.models import (
    CandidateProfile,
    EvidenceUnit,
    FrameField,
    FrameFieldConfidence,
    ValueCandidate,
)


def _make_unit(text: str, p_idx: int = 0, s_idx: int = 0) -> EvidenceUnit:
    return EvidenceUnit(
        unit_id=f"EU:{p_idx}:{s_idx}",
        text=text,
        passage_idx=p_idx,
        sentence_idx=s_idx,
    )


# ============================================================================
# Test 1: CandidateMiner produit numeric_identifier, pas year
# ============================================================================

class TestCandidateMinerNumericIdentifier:

    def test_produces_numeric_identifier_not_year(self):
        """CandidateMiner étiquette les 4-digit numbers comme numeric_identifier."""
        miner = CandidateMiner()
        units = [_make_unit("S/4HANA 2023 Security Guide features.")]
        profile = miner.mine(units, "doc1")

        numeric = profile.get_candidates_by_type("numeric_identifier")
        years = profile.get_candidates_by_type("year")

        assert len(numeric) == 1
        assert numeric[0].raw_value == "2023"
        assert len(years) == 0  # Plus de type "year"

    def test_copyright_filter_still_works(self):
        """Le filtre copyright fonctionne toujours avec numeric_identifier."""
        miner = CandidateMiner()
        units = [_make_unit("Copyright © 2023 SAP SE. All rights reserved.")]
        profile = miner.mine(units, "doc1")

        numeric = profile.get_candidates_by_type("numeric_identifier")
        assert len(numeric) == 0  # Filtré par copyright


# ============================================================================
# Test 3: Mode déterministe — numeric_identifier → unknowns
# ============================================================================

class TestDeterministicNumericIdentifier:

    def test_numeric_identifier_without_subject_goes_to_unknowns(self):
        """numeric_identifier dans le titre SANS co-occurrence sujet → unknowns."""
        profile = CandidateProfile(
            doc_id="test",
            total_units=1,
            total_chars=50,
            value_candidates=[
                ValueCandidate(
                    candidate_id="VC:numeric_identifier:abc",
                    raw_value="2023",
                    value_type="numeric_identifier",
                    unit_ids=["EU:0:0"],
                    frequency=1,
                    in_title=True,
                    cooccurs_with_subject=False,
                ),
            ],
        )

        builder = FrameBuilder(llm_client=None, use_llm=False)
        units = [_make_unit("S/4HANA 2023 Guide")]
        frame = builder.build(profile, units)

        assert frame.method == "deterministic_fallback"
        assert "numeric_identifier_ambiguous" in frame.unknowns
        assert frame.get_field("year") is None

    def test_numeric_identifier_title_plus_subject_blocked_by_authority_contract(self):
        """numeric_identifier dans le titre + co-occurrence sujet → rejeté par contrat d'autorité.

        Depuis le contrat d'autorité (ResolverPriorStatus), en mode ABSENT
        (pas de resolver prior), un numeric_identifier nu ne peut plus devenir
        release_id. Seul un named_version avec in_title ou frequency >= 3 passe.
        """
        profile = CandidateProfile(
            doc_id="test",
            total_units=1,
            total_chars=50,
            value_candidates=[
                ValueCandidate(
                    candidate_id="VC:numeric_identifier:abc",
                    raw_value="2023",
                    value_type="numeric_identifier",
                    unit_ids=["EU:0:0"],
                    frequency=3,
                    in_title=True,
                    cooccurs_with_subject=True,
                ),
            ],
        )

        builder = FrameBuilder(llm_client=None, use_llm=False)
        units = [_make_unit("S/4HANA 2023 Guide")]
        frame = builder.build(profile, units)

        assert frame.method == "deterministic_fallback"
        release = frame.get_field("release_id")
        # Contrat d'autorité: sans resolver prior, numeric_identifier seul → rejeté
        assert release is None
        assert any("AuthorityContract: rejected" in n for n in frame.validation_notes)

    def test_named_version_still_becomes_release_id(self):
        """named_version → release_id inchangé en mode déterministe."""
        profile = CandidateProfile(
            doc_id="test",
            total_units=1,
            total_chars=50,
            value_candidates=[
                ValueCandidate(
                    candidate_id="VC:named_version:abc",
                    raw_value="Version 2023",
                    value_type="named_version",
                    unit_ids=["EU:0:0"],
                    frequency=1,
                    in_title=True,
                ),
            ],
        )

        builder = FrameBuilder(llm_client=None, use_llm=False)
        units = [_make_unit("Version 2023 is available.")]
        frame = builder.build(profile, units)

        release = frame.get_field("release_id")
        assert release is not None
        assert release.value_normalized == "Version 2023"


# ============================================================================
# Test 5-6: Prompt template
# ============================================================================

class TestPromptTemplate:

    def test_prompt_contains_numeric_identifier_rules(self):
        """Le prompt contient les règles pour numeric_identifier."""
        assert "numeric_identifier" in FRAME_BUILDER_PROMPT
        assert "AMBIGUOUS" in FRAME_BUILDER_PROMPT

    def test_prompt_no_hardcoded_year_rule(self):
        """Le prompt ne contient plus de règle hardcodée 'For year:'."""
        assert 'For "year"' not in FRAME_BUILDER_PROMPT

    def test_prompt_forbids_value_type_as_field_name(self):
        """Le prompt interdit d'utiliser value_type comme field_name."""
        assert "NEVER use value_type" in FRAME_BUILDER_PROMPT


class TestFieldNameValidation:

    def test_rejects_numeric_identifier_as_field_name(self):
        """Le LLM ne peut pas utiliser 'numeric_identifier' comme field_name."""
        llm_response = json.dumps({
            "fields": [
                {
                    "field_name": "numeric_identifier",
                    "value_normalized": "2023",
                    "evidence_unit_ids": ["EU:0:0"],
                    "candidate_ids": ["VC:numeric_identifier:abc"],
                    "confidence": "medium",
                    "reasoning": "Ambiguous number"
                },
                {
                    "field_name": "release_id",
                    "value_normalized": "2023",
                    "evidence_unit_ids": ["EU:0:0"],
                    "candidate_ids": ["VC:numeric_identifier:abc"],
                    "confidence": "high",
                    "reasoning": "Main release identifier"
                }
            ],
            "unknowns": []
        })

        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = CandidateProfile(
            doc_id="test",
            total_units=1,
            total_chars=50,
            value_candidates=[
                ValueCandidate(
                    candidate_id="VC:numeric_identifier:abc",
                    raw_value="2023",
                    value_type="numeric_identifier",
                    unit_ids=["EU:0:0"],
                    frequency=1,
                ),
            ],
        )
        frame = builder._parse_llm_response(llm_response, profile)

        # numeric_identifier rejeté, release_id gardé
        assert frame.get_field("numeric_identifier") is None
        assert frame.get_field("release_id") is not None


# ============================================================================
# Test 7-8: DomainContextInjector + identification_semantics
# ============================================================================

class TestIdentificationSemantics:
    """Tests d'injection identification_semantics.

    Note: On reproduit la logique _build_context_section() ici pour éviter
    l'import de knowbase.ontology (dépendance neo4j non disponible localement).
    """

    @staticmethod
    def _build_context_section_logic(profile) -> str:
        """Reproduction de DomainContextInjector._build_context_section()."""
        acronyms_text = ""
        if profile.common_acronyms:
            acronyms_list = [
                f"- {a}: {e}"
                for a, e in list(profile.common_acronyms.items())[:15]
            ]
            acronyms_text = "\n".join(acronyms_list)

        concepts_text = ""
        if profile.key_concepts:
            concepts_text = ", ".join(profile.key_concepts[:10])

        section = f"""[DOMAIN CONTEXT - Priority: {profile.context_priority.upper()}]
{profile.llm_injection_prompt}"""

        if acronyms_text:
            section += f"\n\nCommon acronyms in this domain:\n{acronyms_text}"
        if concepts_text:
            section += f"\n\nKey concepts to recognize:\n{concepts_text}"
        if getattr(profile, 'versioning_hints', '') and profile.versioning_hints.strip():
            section += f"\n\nVersioning conventions for this domain:\n{profile.versioning_hints}"
        if getattr(profile, 'identification_semantics', '') and profile.identification_semantics.strip():
            section += f"\n\nIdentification semantics for this domain:\n{profile.identification_semantics}"
        section += "\n[END DOMAIN CONTEXT]"
        return section

    def test_injector_includes_identification_semantics(self):
        """DomainContextInjector inclut identification_semantics si présent."""
        mock_profile = MagicMock()
        mock_profile.context_priority = "high"
        mock_profile.llm_injection_prompt = "Test domain context"
        mock_profile.common_acronyms = {}
        mock_profile.key_concepts = []
        mock_profile.versioning_hints = ""
        mock_profile.identification_semantics = (
            "Rule: 4-digit number after product name → release_id."
        )

        section = self._build_context_section_logic(mock_profile)

        assert "Identification semantics" in section
        assert "release_id" in section

    def test_empty_identification_semantics_no_section(self):
        """identification_semantics vide → pas de section ajoutée."""
        mock_profile = MagicMock()
        mock_profile.context_priority = "high"
        mock_profile.llm_injection_prompt = "Test domain context"
        mock_profile.common_acronyms = {}
        mock_profile.key_concepts = []
        mock_profile.versioning_hints = ""
        mock_profile.identification_semantics = ""

        section = self._build_context_section_logic(mock_profile)

        assert "Identification semantics" not in section


# ============================================================================
# Test 9-10: Confidence gate — year sans marqueur temporel
# ============================================================================

class TestConfidenceGate:

    def _make_profile_with_candidates(self, context_snippets=None):
        return CandidateProfile(
            doc_id="test",
            total_units=1,
            total_chars=50,
            value_candidates=[
                ValueCandidate(
                    candidate_id="VC:numeric_identifier:abc",
                    raw_value="2023",
                    value_type="numeric_identifier",
                    unit_ids=["EU:0:0"],
                    frequency=1,
                    context_snippets=context_snippets or [],
                ),
            ],
        )

    def test_year_without_temporal_marker_degraded_to_low(self):
        """LLM choisit 'year' sans marqueur temporel → confidence LOW."""
        llm_response = json.dumps({
            "fields": [
                {
                    "field_name": "year",
                    "value_normalized": "2023",
                    "evidence_unit_ids": ["EU:0:0"],
                    "candidate_ids": ["VC:numeric_identifier:abc"],
                    "confidence": "high",
                    "reasoning": "Found in title of document"
                }
            ],
            "unknowns": []
        })

        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = self._make_profile_with_candidates(
            context_snippets=["S/4HANA 2023 Security Guide"]
        )
        frame = builder._parse_llm_response(llm_response, profile)

        year_field = frame.get_field("year")
        assert year_field is not None
        assert year_field.confidence == FrameFieldConfidence.LOW

    def test_publication_year_with_copyright_preserves_confidence(self):
        """LLM choisit 'publication_year' avec 'copyright' → confiance préservée."""
        llm_response = json.dumps({
            "fields": [
                {
                    "field_name": "publication_year",
                    "value_normalized": "2023",
                    "evidence_unit_ids": ["EU:0:0"],
                    "candidate_ids": ["VC:numeric_identifier:abc"],
                    "confidence": "high",
                    "reasoning": "Copyright 2023, this is the publication year"
                }
            ],
            "unknowns": []
        })

        builder = FrameBuilder(llm_client=None, use_llm=False)
        profile = self._make_profile_with_candidates(
            context_snippets=["Copyright 2023 SAP SE"]
        )
        frame = builder._parse_llm_response(llm_response, profile)

        pub_year_field = frame.get_field("publication_year")
        assert pub_year_field is not None
        assert pub_year_field.confidence == FrameFieldConfidence.HIGH
