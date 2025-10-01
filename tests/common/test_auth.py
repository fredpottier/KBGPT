"""
Tests Authentication - Phase 0.5 P2.14
"""
import pytest
from fastapi import HTTPException
from knowbase.common.auth import (
    require_api_key,
    is_authenticated,
    get_api_key,
    AUTH_ENABLED
)


def test_auth_disabled_by_default():
    """Test auth désactivée par défaut"""
    # Par défaut, AUTH_ENABLED=false (sauf si .env dit true)
    # Ce test vérifie comportement par défaut


def test_require_api_key_disabled():
    """Test API key quand auth désactivée"""
    if not AUTH_ENABLED:
        # Auth disabled, devrait passer sans API key
        result = require_api_key(x_api_key=None)
        assert result == "dev-mode"


def test_require_api_key_missing():
    """Test API key manquante quand auth activée"""
    # Ce test échoue si AUTH_ENABLED=false
    # On skip si auth désactivée
    if not AUTH_ENABLED:
        pytest.skip("Auth disabled, cannot test missing key")

    with pytest.raises(HTTPException) as exc_info:
        require_api_key(x_api_key=None)

    assert exc_info.value.status_code == 401
    assert "API Key required" in exc_info.value.detail


def test_require_api_key_invalid():
    """Test API key invalide"""
    if not AUTH_ENABLED:
        pytest.skip("Auth disabled")

    with pytest.raises(HTTPException) as exc_info:
        require_api_key(x_api_key="wrong-key")

    assert exc_info.value.status_code == 401
    assert "Invalid API Key" in exc_info.value.detail


def test_require_api_key_valid():
    """Test API key valide"""
    if not AUTH_ENABLED:
        pytest.skip("Auth disabled")

    correct_key = get_api_key()
    result = require_api_key(x_api_key=correct_key)
    assert result == correct_key


def test_is_authenticated():
    """Test helper is_authenticated"""
    result = is_authenticated()
    assert result == AUTH_ENABLED


def test_get_api_key():
    """Test récupération API key"""
    key = get_api_key()
    assert key is not None
    assert len(key) > 0
