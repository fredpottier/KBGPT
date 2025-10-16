"""
Tests pour les dependencies auth FastAPI.

Phase 0 - Security Hardening
"""
import pytest
from fastapi import HTTPException
from unittest.mock import Mock

from knowbase.api.dependencies import (
    get_current_user,
    require_admin,
    require_editor,
    get_tenant_id
)
from knowbase.api.services.auth_service import get_auth_service


@pytest.fixture
def auth_service():
    """Fixture AuthService."""
    return get_auth_service()


@pytest.fixture
def valid_admin_token(auth_service):
    """Génère un token admin valide."""
    return auth_service.generate_access_token(
        user_id="admin-123",
        email="admin@example.com",
        role="admin",
        tenant_id="tenant-1"
    )


@pytest.fixture
def valid_editor_token(auth_service):
    """Génère un token editor valide."""
    return auth_service.generate_access_token(
        user_id="editor-123",
        email="editor@example.com",
        role="editor",
        tenant_id="tenant-1"
    )


@pytest.fixture
def valid_viewer_token(auth_service):
    """Génère un token viewer valide."""
    return auth_service.generate_access_token(
        user_id="viewer-123",
        email="viewer@example.com",
        role="viewer",
        tenant_id="tenant-1"
    )


def test_get_current_user_valid_token(valid_admin_token):
    """Test get_current_user avec token valide."""
    # Mock credentials
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=valid_admin_token
    )

    claims = get_current_user(credentials)

    assert claims["sub"] == "admin-123"
    assert claims["email"] == "admin@example.com"
    assert claims["role"] == "admin"
    assert claims["tenant_id"] == "tenant-1"


def test_get_current_user_invalid_token():
    """Test get_current_user avec token invalide."""
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="invalid.token.here"
    )

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials)

    assert exc_info.value.status_code == 401


def test_require_admin_with_admin_token(valid_admin_token):
    """Test require_admin avec token admin."""
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=valid_admin_token
    )

    current_user = get_current_user(credentials)
    result = require_admin(current_user)

    assert result["role"] == "admin"


def test_require_admin_with_editor_token(valid_editor_token):
    """Test require_admin avec token editor (devrait échouer)."""
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=valid_editor_token
    )

    current_user = get_current_user(credentials)

    with pytest.raises(HTTPException) as exc_info:
        require_admin(current_user)

    assert exc_info.value.status_code == 403
    assert "administrateur" in exc_info.value.detail.lower()


def test_require_admin_with_viewer_token(valid_viewer_token):
    """Test require_admin avec token viewer (devrait échouer)."""
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=valid_viewer_token
    )

    current_user = get_current_user(credentials)

    with pytest.raises(HTTPException) as exc_info:
        require_admin(current_user)

    assert exc_info.value.status_code == 403


def test_require_editor_with_admin_token(valid_admin_token):
    """Test require_editor avec token admin (devrait passer)."""
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=valid_admin_token
    )

    current_user = get_current_user(credentials)
    result = require_editor(current_user)

    assert result["role"] == "admin"


def test_require_editor_with_editor_token(valid_editor_token):
    """Test require_editor avec token editor."""
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=valid_editor_token
    )

    current_user = get_current_user(credentials)
    result = require_editor(current_user)

    assert result["role"] == "editor"


def test_require_editor_with_viewer_token(valid_viewer_token):
    """Test require_editor avec token viewer (devrait échouer)."""
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=valid_viewer_token
    )

    current_user = get_current_user(credentials)

    with pytest.raises(HTTPException) as exc_info:
        require_editor(current_user)

    assert exc_info.value.status_code == 403
    assert "editor" in exc_info.value.detail.lower()


def test_get_tenant_id_from_jwt(valid_admin_token):
    """Test extraction tenant_id depuis JWT."""
    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=valid_admin_token
    )

    current_user = get_current_user(credentials)
    tenant_id = get_tenant_id(current_user)

    assert tenant_id == "tenant-1"


def test_get_tenant_id_missing_in_token(auth_service):
    """Test get_tenant_id quand tenant_id manque dans token."""
    # Créer un token sans tenant_id (en mockant)
    from datetime import datetime, timedelta, timezone
    import jwt

    claims = {
        "sub": "user-123",
        "email": "test@example.com",
        "role": "admin",
        # Pas de tenant_id !
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }

    token = jwt.encode(claims, auth_service.private_key, algorithm="RS256")

    from fastapi.security import HTTPAuthorizationCredentials
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=token
    )

    current_user = get_current_user(credentials)

    with pytest.raises(HTTPException) as exc_info:
        get_tenant_id(current_user)

    assert exc_info.value.status_code == 401
    assert "tenant_id manquant" in exc_info.value.detail.lower()
