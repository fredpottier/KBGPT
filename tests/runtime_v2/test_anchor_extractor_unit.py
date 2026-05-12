"""Tests unitaires AnchorExtractor — validator evidence-locked + parsing."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from knowbase.anchor.anchor_extractor import AnchorExtractor
from knowbase.anchor.models import AnchorType


@pytest.fixture
def extractor():
    return AnchorExtractor(vllm_url="http://test-vllm:8000")


def _mock_response(content: str):
    """Mock httpx response."""
    mock = MagicMock()
    mock.json.return_value = {"choices": [{"message": {"content": content}}]}
    mock.raise_for_status = MagicMock()
    return mock


def test_current_default_extraction(extractor):
    """Question sans anchor explicite → CURRENT_DEFAULT."""
    fake_json = '{"anchor_type":"current_default","scope":{"extraction_evidence":null},"confidence":1.0,"reasoning":"no temporal hint"}'
    with patch.object(extractor, "_call_llm", return_value=fake_json):
        a = extractor.extract("What is the encryption mode of S/4HANA?")
    assert a.anchor_type == AnchorType.CURRENT_DEFAULT
    assert a.scope.extraction_evidence is None


def test_point_extraction_with_version(extractor):
    """POINT avec version explicite → conserve l'evidence si substring."""
    q = "What does Regulation (EU) 2021/821 say about brokering?"
    fake_json = (
        '{"anchor_type":"point","scope":{"version":"Regulation (EU) 2021/821",'
        '"extraction_evidence":"Regulation (EU) 2021/821"},"confidence":1.0,"reasoning":"x"}'
    )
    with patch.object(extractor, "_call_llm", return_value=fake_json):
        a = extractor.extract(q)
    assert a.anchor_type == AnchorType.POINT
    assert a.scope.version == "Regulation (EU) 2021/821"
    assert a.scope.extraction_evidence == "Regulation (EU) 2021/821"


def test_validator_rejects_evidence_not_in_question(extractor):
    """Si LLM hallucine une evidence pas dans la question → degraded en CURRENT_DEFAULT."""
    q = "What is encryption of S/4HANA?"
    # LLM invente une evidence absente de la question
    fake_json = (
        '{"anchor_type":"point","scope":{"version":"hallucinated",'
        '"extraction_evidence":"this text is not in the question"},"confidence":1.0,"reasoning":"x"}'
    )
    with patch.object(extractor, "_call_llm", return_value=fake_json):
        a = extractor.extract(q)
    assert a.anchor_type == AnchorType.CURRENT_DEFAULT
    assert a.confidence == 0.0
    assert "rejected" in a.extraction_method


def test_range_extraction_with_bounds(extractor):
    q = "How did encryption evolve between 2018 and 2024?"
    fake_json = (
        '{"anchor_type":"range","scope":{"range_start":"2018","range_end":"2024",'
        '"extraction_evidence":"between 2018 and 2024"},"confidence":1.0,"reasoning":"x"}'
    )
    with patch.object(extractor, "_call_llm", return_value=fake_json):
        a = extractor.extract(q)
    assert a.anchor_type == AnchorType.RANGE
    assert a.scope.range_start == "2018"
    assert a.scope.range_end == "2024"


def test_invalid_json_fallback(extractor):
    fake_json = "not a valid json"
    with patch.object(extractor, "_call_llm", return_value=fake_json):
        a = extractor.extract("question")
    assert a.anchor_type == AnchorType.CURRENT_DEFAULT
    assert a.confidence == 0.0


def test_normalize_collapses_whitespace(extractor):
    """_normalize doit collapse whitespace + lowercase."""
    n = extractor._normalize("  Hello\n\tWORLD  ")
    assert n == "hello world"


def test_validator_clears_evidence_on_current_default(extractor):
    """Pour CURRENT_DEFAULT, extraction_evidence DOIT être null (clear if not)."""
    q = "What is X?"
    fake_json = (
        '{"anchor_type":"current_default","scope":{"extraction_evidence":"is X"},'
        '"confidence":1.0,"reasoning":"x"}'
    )
    with patch.object(extractor, "_call_llm", return_value=fake_json):
        a = extractor.extract(q)
    # Should be cleared
    assert a.scope.extraction_evidence is None
