# tests/claimfirst/test_qs_llm_extraction.py
"""Tests Phase 4 — LLM Extraction structurée."""

import pytest
from knowbase.claimfirst.extractors.qs_llm_extractor import _parse_extraction_response


class TestParseExtractionResponse:

    def test_valid_extraction(self):
        response = '''{
            "candidate_question": "What is the retention period?",
            "candidate_dimension_key": "data_retention_period",
            "value_type": "number",
            "value_raw": "90 days",
            "value_normalized": "90",
            "operator": "=",
            "scope_evidence": "Enterprise Edition",
            "scope_basis": "claim_explicit",
            "confidence": 0.9,
            "abstain_reason": null
        }'''
        result = _parse_extraction_response(response, "c1", "d1", {})
        assert result is not None
        assert result.is_valid()
        assert result.candidate_dimension_key == "data_retention_period"
        assert result.value_type == "number"
        assert result.operator == "="

    def test_invalid_value_type_dropped(self):
        response = '''{
            "candidate_question": "Q?",
            "candidate_dimension_key": "k",
            "value_type": "INVALID_TYPE",
            "value_raw": "x",
            "operator": "="
        }'''
        result = _parse_extraction_response(response, "c1", "d1", {})
        assert result is not None
        assert not result.is_valid()
        assert result.abstain_reason == "invalid_value_type"

    def test_invalid_operator_dropped(self):
        response = '''{
            "candidate_question": "Q?",
            "candidate_dimension_key": "k",
            "value_type": "number",
            "value_raw": "5",
            "operator": "~="
        }'''
        result = _parse_extraction_response(response, "c1", "d1", {})
        assert result is not None
        assert not result.is_valid()
        assert result.abstain_reason == "invalid_operator"

    def test_missing_required_fields(self):
        response = '{"candidate_question": "Q?"}'
        result = _parse_extraction_response(response, "c1", "d1", {})
        assert result is None

    def test_invalid_json(self):
        result = _parse_extraction_response("not json", "c1", "d1", {})
        assert result is None

    def test_gating_info_propagated(self):
        response = '''{
            "candidate_question": "Q?",
            "candidate_dimension_key": "k",
            "value_type": "boolean",
            "value_raw": "enabled",
            "operator": "="
        }'''
        gating = {"c1": ("COMPARABLE_FACT", ["strong:version"])}
        result = _parse_extraction_response(response, "c1", "d1", gating)
        assert result is not None
        assert result.gate_label == "COMPARABLE_FACT"
        assert result.gating_signals == ["strong:version"]

    def test_abstain_reason_from_llm(self):
        response = '''{
            "candidate_question": "Q?",
            "candidate_dimension_key": "k",
            "value_type": "string",
            "value_raw": "x",
            "operator": "=",
            "abstain_reason": "too vague"
        }'''
        result = _parse_extraction_response(response, "c1", "d1", {})
        assert result is not None
        assert not result.is_valid()
