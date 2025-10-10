"""
Tests unitaires pour AuthService.

Phase 0 - Security Hardening
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, mock_open
import jwt

from knowbase.api.services.auth_service import AuthService, get_auth_service
from fastapi import HTTPException


@pytest.fixture
def mock_rsa_keys():
    """Mock des clés RSA pour tests."""
    private_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAw5VJhfF9L8RQ+H9QGvf4xJ8F5mH7x7Z8nQqH7J8F5mH7x7Z8
nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8
nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8
nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8
nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8
nQIDAQABAoIBABKl5P8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH
7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH
7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH
-----END RSA PRIVATE KEY-----"""

    public_key = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAw5VJhfF9L8RQ+H9QGvf4
xJ8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH
7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH7J8F5mH7x7Z8nQqH
-----END PUBLIC KEY-----"""

    return private_key, public_key


@pytest.fixture
def auth_service(mock_rsa_keys):
    """Fixture AuthService avec clés mockées."""
    private_key, public_key = mock_rsa_keys

    # Utiliser les vraies clés générées pour les tests
    # Car les clés mockées ci-dessus sont invalides
    import os
    private_key_path = os.path.join("config", "keys", "jwt_private.pem")
    public_key_path = os.path.join("config", "keys", "jwt_public.pem")

    if os.path.exists(private_key_path) and os.path.exists(public_key_path):
        with open(private_key_path, "r") as f:
            private_key = f.read()
        with open(public_key_path, "r") as f:
            public_key = f.read()

    with patch.object(AuthService, '_load_private_key', return_value=private_key):
        with patch.object(AuthService, '_load_public_key', return_value=public_key):
            service = AuthService()
            return service


def test_hash_password(auth_service):
    """Test hashing de mot de passe."""
    password = "TestPassword123!"
    hashed = auth_service.hash_password(password)

    assert hashed is not None
    assert hashed != password
    assert hashed.startswith("$2b$")  # bcrypt prefix


def test_verify_password_success(auth_service):
    """Test vérification mot de passe valide."""
    password = "TestPassword123!"
    hashed = auth_service.hash_password(password)

    assert auth_service.verify_password(password, hashed) is True


def test_verify_password_failure(auth_service):
    """Test vérification mot de passe invalide."""
    password = "TestPassword123!"
    hashed = auth_service.hash_password(password)

    assert auth_service.verify_password("WrongPassword", hashed) is False


def test_generate_access_token(auth_service):
    """Test génération access token."""
    user_id = "user-123"
    email = "test@example.com"
    role = "admin"
    tenant_id = "tenant-1"

    token = auth_service.generate_access_token(
        user_id=user_id,
        email=email,
        role=role,
        tenant_id=tenant_id
    )

    assert token is not None
    assert isinstance(token, str)
    assert len(token) > 100  # JWT tokens are long


def test_generate_refresh_token(auth_service):
    """Test génération refresh token."""
    user_id = "user-123"
    email = "test@example.com"

    token = auth_service.generate_refresh_token(
        user_id=user_id,
        email=email
    )

    assert token is not None
    assert isinstance(token, str)
    assert len(token) > 100


def test_verify_access_token_valid(auth_service):
    """Test vérification access token valide."""
    user_id = "user-123"
    email = "test@example.com"
    role = "editor"
    tenant_id = "tenant-1"

    token = auth_service.generate_access_token(
        user_id=user_id,
        email=email,
        role=role,
        tenant_id=tenant_id
    )

    claims = auth_service.verify_access_token(token)

    assert claims["sub"] == user_id
    assert claims["email"] == email
    assert claims["role"] == role
    assert claims["tenant_id"] == tenant_id
    assert claims["type"] == "access"


def test_verify_refresh_token_valid(auth_service):
    """Test vérification refresh token valide."""
    user_id = "user-123"
    email = "test@example.com"

    token = auth_service.generate_refresh_token(
        user_id=user_id,
        email=email
    )

    claims = auth_service.verify_refresh_token(token)

    assert claims["sub"] == user_id
    assert claims["email"] == email
    assert claims["type"] == "refresh"


def test_verify_expired_token(auth_service):
    """Test vérification token expiré."""
    user_id = "user-123"
    email = "test@example.com"

    # Générer token avec expiration immédiate
    token = auth_service.generate_access_token(
        user_id=user_id,
        email=email,
        role="viewer",
        tenant_id="tenant-1",
        expires_delta=timedelta(seconds=-1)  # Déjà expiré
    )

    with pytest.raises(HTTPException) as exc_info:
        auth_service.verify_access_token(token)

    assert exc_info.value.status_code == 401
    assert "expiré" in exc_info.value.detail.lower()


def test_verify_invalid_token(auth_service):
    """Test vérification token invalide."""
    invalid_token = "invalid.jwt.token"

    with pytest.raises(HTTPException) as exc_info:
        auth_service.verify_access_token(invalid_token)

    assert exc_info.value.status_code == 401
    assert "invalide" in exc_info.value.detail.lower()


def test_verify_access_token_with_refresh_token(auth_service):
    """Test vérification access token quand c'est un refresh token."""
    user_id = "user-123"
    email = "test@example.com"

    # Générer refresh token
    refresh_token = auth_service.generate_refresh_token(
        user_id=user_id,
        email=email
    )

    # Essayer de le vérifier comme access token
    with pytest.raises(HTTPException) as exc_info:
        auth_service.verify_access_token(refresh_token)

    assert exc_info.value.status_code == 401
    assert "type incorrect" in exc_info.value.detail.lower()


def test_verify_refresh_token_with_access_token(auth_service):
    """Test vérification refresh token quand c'est un access token."""
    user_id = "user-123"
    email = "test@example.com"

    # Générer access token
    access_token = auth_service.generate_access_token(
        user_id=user_id,
        email=email,
        role="admin",
        tenant_id="tenant-1"
    )

    # Essayer de le vérifier comme refresh token
    with pytest.raises(HTTPException) as exc_info:
        auth_service.verify_refresh_token(access_token)

    assert exc_info.value.status_code == 401
    assert "type incorrect" in exc_info.value.detail.lower()


def test_get_auth_service_singleton():
    """Test que get_auth_service retourne toujours la même instance."""
    service1 = get_auth_service()
    service2 = get_auth_service()

    assert service1 is service2


def test_token_expiration_times(auth_service):
    """Test que les tokens ont les bonnes durées d'expiration."""
    user_id = "user-123"
    email = "test@example.com"

    # Access token
    access_token = auth_service.generate_access_token(
        user_id=user_id,
        email=email,
        role="admin",
        tenant_id="tenant-1"
    )

    access_claims = auth_service.verify_access_token(access_token)
    access_exp = datetime.fromtimestamp(access_claims["exp"], tz=timezone.utc)
    access_iat = datetime.fromtimestamp(access_claims["iat"], tz=timezone.utc)
    access_duration = (access_exp - access_iat).total_seconds()

    # Devrait être environ 3600 secondes (1 heure)
    assert 3590 <= access_duration <= 3610

    # Refresh token
    refresh_token = auth_service.generate_refresh_token(
        user_id=user_id,
        email=email
    )

    refresh_claims = auth_service.verify_refresh_token(refresh_token)
    refresh_exp = datetime.fromtimestamp(refresh_claims["exp"], tz=timezone.utc)
    refresh_iat = datetime.fromtimestamp(refresh_claims["iat"], tz=timezone.utc)
    refresh_duration = (refresh_exp - refresh_iat).total_seconds()

    # Devrait être environ 604800 secondes (7 jours)
    assert 604700 <= refresh_duration <= 604900
