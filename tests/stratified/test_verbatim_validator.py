"""
Tests pour le validateur verbatim (Volet A).
Vérifie que les assertions reformulées par le LLM sont détectées et rejetées.
"""

import pytest
from knowbase.stratified.pass1.verbatim_validator import (
    validate_assertion_verbatim,
    validate_assertions_batch,
    VerbatimStatus,
    BatchValidationStats,
    normalize_whitespace,
)


class TestNormalizeWhitespace:
    """Tests pour la normalisation des espaces."""

    def test_basic_normalization(self):
        assert normalize_whitespace("hello  world") == "hello world"
        assert normalize_whitespace("hello\nworld") == "hello world"
        assert normalize_whitespace("  hello  world  ") == "hello world"

    def test_tabs_and_newlines(self):
        assert normalize_whitespace("hello\t\tworld") == "hello world"
        assert normalize_whitespace("hello\n\n\nworld") == "hello world"


class TestValidateAssertionVerbatim:
    """Tests pour la validation d'une assertion unique."""

    def test_exact_match(self):
        """Texte identique = VALID."""
        source = "This is a test sentence with some content."
        assertion = "This is a test sentence with some content."

        result = validate_assertion_verbatim(assertion, source)

        assert result.is_valid
        assert result.status == VerbatimStatus.VALID
        assert result.match_type == "exact"

    def test_exact_substring(self):
        """Substring exact = VALID."""
        source = "The document contains this important fact. And some more text."
        assertion = "this important fact"

        result = validate_assertion_verbatim(assertion, source)

        assert result.is_valid
        assert result.status == VerbatimStatus.VALID
        assert result.corrected_start == 22
        assert result.corrected_end == 41

    def test_normalized_match(self):
        """Match après normalisation whitespace = VALID_NORMALIZED."""
        source = "This is a test\n  sentence with   some content."
        assertion = "This is a test sentence with some content."

        result = validate_assertion_verbatim(assertion, source)

        assert result.is_valid
        assert result.status == VerbatimStatus.VALID_NORMALIZED
        assert result.match_type == "normalized"

    def test_reformulated_text(self):
        """Texte reformulé = ABSTAIN_NOT_SUBSTRING."""
        source = "Customer manages configuration, implementation, integration."
        assertion = "The customer is responsible for managing configuration and implementation."

        result = validate_assertion_verbatim(assertion, source)

        assert not result.is_valid
        assert result.status == VerbatimStatus.ABSTAIN_NOT_SUBSTRING

    def test_too_short(self):
        """Texte trop court = ABSTAIN_TOO_SHORT."""
        source = "This is a long source text with many words."
        assertion = "short"

        result = validate_assertion_verbatim(assertion, source)

        assert not result.is_valid
        assert result.status == VerbatimStatus.ABSTAIN_TOO_SHORT

    def test_too_long(self):
        """Texte trop long = ABSTAIN_TOO_LONG."""
        source = "x" * 2000
        assertion = "y" * 1001

        result = validate_assertion_verbatim(assertion, source, max_length=1000)

        assert not result.is_valid
        assert result.status == VerbatimStatus.ABSTAIN_TOO_LONG

    def test_span_correction(self):
        """Spans incorrects mais texte trouvé = corrige les spans."""
        source = "Start text. The important assertion here. End text."
        assertion = "The important assertion here"

        # Spans incorrects
        result = validate_assertion_verbatim(
            assertion, source,
            claimed_start=0,
            claimed_end=10
        )

        assert result.is_valid
        assert result.corrected_start == 12  # Position réelle
        assert result.corrected_end == 40

    def test_span_misaligned_with_reformulation(self):
        """Spans valides mais texte différent = reformulation détectée."""
        source = "The original text is here."
        assertion = "Modified text is here"

        result = validate_assertion_verbatim(
            assertion, source,
            claimed_start=4,
            claimed_end=21
        )

        assert not result.is_valid
        assert result.status == VerbatimStatus.ABSTAIN_SPAN_MISALIGNED


class TestValidateAssertionsBatch:
    """Tests pour la validation batch."""

    def test_batch_validation(self):
        """Test validation de plusieurs assertions."""
        assertions = [
            {
                "chunk_id": "chunk1",
                "text": "This is verbatim text",
                "start_char": 0,
                "end_char": 21
            },
            {
                "chunk_id": "chunk1",
                "text": "This has been reformulated by the LLM",
                "start_char": 30,
                "end_char": 50  # Span exists but text differs = span_misaligned
            },
            {
                "chunk_id": "chunk2",
                "text": "Another exact match here",
                "start_char": 0,
                "end_char": 24
            }
        ]

        source_texts = {
            "chunk1": "This is verbatim text. Some other content follows.",
            "chunk2": "Another exact match here with more text."
        }

        valid, abstained, stats = validate_assertions_batch(assertions, source_texts)

        assert len(valid) == 2
        assert len(abstained) == 1
        assert stats.valid_exact == 2
        # Le texte reformulé a un span valide mais texte différent = span_misaligned
        assert stats.abstain_span_misaligned == 1

    def test_empty_batch(self):
        """Batch vide = stats à zéro."""
        valid, abstained, stats = validate_assertions_batch([], {})

        assert len(valid) == 0
        assert len(abstained) == 0
        assert stats.total == 0

    def test_missing_source_text(self):
        """Source manquante = abstain."""
        assertions = [
            {"chunk_id": "unknown", "text": "Some text here", "start_char": 0, "end_char": 14}
        ]

        valid, abstained, stats = validate_assertions_batch(assertions, {})

        assert len(valid) == 0
        assert len(abstained) == 1
        assert stats.abstain_not_substring == 1


class TestBatchValidationStats:
    """Tests pour les statistiques."""

    def test_verbatim_rate(self):
        stats = BatchValidationStats(total=100, valid_exact=50, valid_normalized=10)
        assert stats.verbatim_rate == 0.6  # 60/100

    def test_reformulation_rate(self):
        stats = BatchValidationStats(total=100, abstain_not_substring=20)
        assert stats.reformulation_rate == 0.2  # 20%

    def test_zero_total(self):
        stats = BatchValidationStats(total=0)
        assert stats.verbatim_rate == 0.0
        assert stats.reformulation_rate == 0.0


class TestLLMSchemas:
    """Tests pour les schemas Pydantic (Volet B)."""

    def test_assertion_schema_generation(self):
        """Vérifie que le schema JSON est généré correctement."""
        from knowbase.stratified.pass1.llm_schemas import (
            AssertionExtractionResponse,
            get_schema_for_phase,
        )

        schema = get_schema_for_phase("assertion_extraction")

        assert "properties" in schema
        assert "assertions" in schema["properties"]
        assert schema["properties"]["assertions"]["type"] == "array"

    def test_vllm_response_format(self):
        """Vérifie le format response_format pour vLLM."""
        from knowbase.stratified.pass1.llm_schemas import get_vllm_response_format

        response_format = get_vllm_response_format("assertion_extraction")

        assert response_format["type"] == "json_schema"
        assert "json_schema" in response_format
        assert response_format["json_schema"]["strict"] is True

    def test_parse_with_schema(self):
        """Vérifie le parsing avec validation schema."""
        from knowbase.stratified.pass1.llm_schemas import parse_with_schema

        valid_json = '''{"assertions": [
            {"text": "Test assertion text here", "type": "factual",
             "start_char": 0, "end_char": 24, "confidence": 0.9, "language": "en"}
        ]}'''

        result = parse_with_schema(valid_json, "assertion_extraction")

        assert result is not None
        assert len(result.assertions) == 1
        assert result.assertions[0].text == "Test assertion text here"

    def test_parse_invalid_json(self):
        """JSON invalide retourne None."""
        from knowbase.stratified.pass1.llm_schemas import parse_with_schema

        result = parse_with_schema("not valid json", "assertion_extraction")
        assert result is None
