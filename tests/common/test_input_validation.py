"""
Tests Input Validation - Phase 0.5 P2.15
"""
import pytest
from fastapi import HTTPException
from knowbase.common.input_validation import (
    validate_string_length,
    validate_array_length,
    validate_candidates,
    validate_text_input,
    validate_batch_size
)


def test_validate_string_length_ok():
    """Test string valide"""
    text = "a" * 100
    length = validate_string_length(text, max_length=1000)
    assert length == 100


def test_validate_string_length_too_long():
    """Test string trop longue"""
    text = "a" * 1001
    with pytest.raises(HTTPException) as exc_info:
        validate_string_length(text, max_length=1000)

    assert exc_info.value.status_code == 400
    assert "too long" in exc_info.value.detail.lower()


def test_validate_array_length_ok():
    """Test array valide"""
    items = list(range(100))
    length = validate_array_length(items, max_length=1000)
    assert length == 100


def test_validate_array_length_too_large():
    """Test array trop grande"""
    items = list(range(1001))
    with pytest.raises(HTTPException) as exc_info:
        validate_array_length(items, max_length=1000)

    assert exc_info.value.status_code == 400
    assert "too large" in exc_info.value.detail.lower()


def test_validate_candidates_ok():
    """Test candidates valides"""
    candidates = [f"cand_{i}" for i in range(50)]
    length = validate_candidates(candidates)
    assert length == 50


def test_validate_candidates_too_many():
    """Test trop de candidates"""
    candidates = [f"cand_{i}" for i in range(101)]
    with pytest.raises(HTTPException) as exc_info:
        validate_candidates(candidates)

    assert exc_info.value.status_code == 400
    assert "candidates" in exc_info.value.detail.lower()


def test_validate_text_input_ok():
    """Test texte utilisateur valide"""
    text = "Question utilisateur ?"
    length = validate_text_input(text)
    assert length == len(text)


def test_validate_text_input_too_long():
    """Test texte utilisateur trop long"""
    text = "a" * 50_001
    with pytest.raises(HTTPException) as exc_info:
        validate_text_input(text)

    assert exc_info.value.status_code == 400


def test_validate_batch_size_ok():
    """Test batch valide"""
    items = list(range(500))
    length = validate_batch_size(items, max_size=1000)
    assert length == 500


def test_validate_batch_size_too_large():
    """Test batch trop grand"""
    items = list(range(1001))
    with pytest.raises(HTTPException) as exc_info:
        validate_batch_size(items, max_size=1000)

    assert exc_info.value.status_code == 400
    assert "batch" in exc_info.value.detail.lower()
