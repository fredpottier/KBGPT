# tests/claimfirst/test_qs_llm_gate.py
"""Tests Phase 3 — LLM Comparability Gate."""

import pytest
from knowbase.claimfirst.extractors.qs_llm_extractor import _parse_gate_response


class TestParseGateResponse:

    def test_comparable_fact(self):
        assert _parse_gate_response('{"label": "COMPARABLE_FACT"}') == "COMPARABLE_FACT"

    def test_non_comparable_fact(self):
        assert _parse_gate_response('{"label": "NON_COMPARABLE_FACT"}') == "NON_COMPARABLE_FACT"

    def test_abstain(self):
        assert _parse_gate_response('{"label": "ABSTAIN"}') == "ABSTAIN"

    def test_invalid_label(self):
        assert _parse_gate_response('{"label": "MAYBE"}') == "ABSTAIN"

    def test_invalid_json(self):
        assert _parse_gate_response("not json") == "ABSTAIN"

    def test_empty_response(self):
        assert _parse_gate_response("{}") == "ABSTAIN"

    def test_case_insensitive(self):
        assert _parse_gate_response('{"label": "comparable_fact"}') == "COMPARABLE_FACT"

    def test_with_whitespace(self):
        assert _parse_gate_response('{"label": " COMPARABLE_FACT "}') == "COMPARABLE_FACT"
