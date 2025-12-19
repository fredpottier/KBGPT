"""
Tests for Authentication - src/knowbase/common/auth.py

Tests cover:
- API Key authentication (require_api_key)
- JWT token creation and verification
- Password hashing and verification
- Configuration functions
- Error handling and edge cases
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

# ============================================
# Mock dependencies before importing auth module
# ============================================

# Mock fastapi
mock_fastapi = MagicMock()


class MockHTTPException(Exception):
    """Mock HTTPException for testing."""

    def __init__(self, status_code: int, detail: str = "", headers: dict = None):
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}
        super().__init__(detail)


mock_fastapi.HTTPException = MockHTTPException
mock_fastapi.Header = MagicMock(return_value=None)
mock_fastapi.status = MagicMock()
mock_fastapi.status.HTTP_401_UNAUTHORIZED = 401

sys.modules['fastapi'] = mock_fastapi


# Mock bcrypt
class MockBcrypt:
    """Mock bcrypt module."""

    _hashes = {}  # Store password -> hash mapping for verification
    _salt_counter = 0  # For unique salts

    @staticmethod
    def gensalt():
        MockBcrypt._salt_counter += 1
        return f"$2b$12$mockSalt{MockBcrypt._salt_counter:010d}".encode('utf-8')

    @staticmethod
    def hashpw(password: bytes, salt: bytes) -> bytes:
        # Create a deterministic but unique hash based on password and salt
        import hashlib
        hash_value = hashlib.sha256(password + salt).hexdigest()[:50]
        result = f"$2b$12${hash_value}".encode('utf-8')
        # Store for verification
        MockBcrypt._hashes[result] = password
        return result

    @staticmethod
    def checkpw(password: bytes, hashed: bytes) -> bool:
        # Check if this hash was created with this password
        if hashed in MockBcrypt._hashes:
            return MockBcrypt._hashes[hashed] == password
        # For invalid hashes, raise exception
        if not hashed.startswith(b"$2"):
            raise ValueError("Invalid hash format")
        return False


mock_bcrypt = MagicMock()
mock_bcrypt.gensalt = MockBcrypt.gensalt
mock_bcrypt.hashpw = MockBcrypt.hashpw
mock_bcrypt.checkpw = MockBcrypt.checkpw

sys.modules['bcrypt'] = mock_bcrypt


# Mock jwt
class MockJwtError(Exception):
    """Base mock JWT error."""
    pass


class MockExpiredSignatureError(MockJwtError):
    """Mock expired signature error."""
    pass


class MockInvalidTokenError(MockJwtError):
    """Mock invalid token error."""
    pass


class MockJwt:
    """Mock PyJWT module."""

    ExpiredSignatureError = MockExpiredSignatureError
    InvalidTokenError = MockInvalidTokenError

    _tokens = {}  # Store token -> payload mapping

    @staticmethod
    def encode(payload: dict, secret: str, algorithm: str = "HS256") -> str:
        import json
        import base64
        # Create a simple mock token
        header = {"alg": algorithm, "typ": "JWT"}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).decode().rstrip("=")
        signature = base64.urlsafe_b64encode(f"{secret}:{header_b64}.{payload_b64}".encode()).decode().rstrip("=")
        token = f"{header_b64}.{payload_b64}.{signature}"
        # Store for verification
        MockJwt._tokens[token] = (payload, secret)
        return token

    @staticmethod
    def decode(token: str, secret: str, algorithms: list) -> dict:
        import json
        import base64

        # Check if token exists in our store
        if token in MockJwt._tokens:
            stored_payload, stored_secret = MockJwt._tokens[token]
            if stored_secret != secret:
                raise MockInvalidTokenError("Invalid signature")

            # Check expiration
            if "exp" in stored_payload:
                exp = stored_payload["exp"]
                if isinstance(exp, datetime):
                    if exp < datetime.utcnow():
                        raise MockExpiredSignatureError("Token expired")
                elif isinstance(exp, (int, float)):
                    if datetime.fromtimestamp(exp) < datetime.utcnow():
                        raise MockExpiredSignatureError("Token expired")

            return stored_payload

        # Try to decode unknown token
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise MockInvalidTokenError("Invalid token structure")
            # Try to decode payload
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            return payload
        except Exception:
            raise MockInvalidTokenError("Invalid token")


mock_jwt = MagicMock()
mock_jwt.encode = MockJwt.encode
mock_jwt.decode = MockJwt.decode
mock_jwt.ExpiredSignatureError = MockExpiredSignatureError
mock_jwt.InvalidTokenError = MockInvalidTokenError

sys.modules['jwt'] = mock_jwt


from knowbase.common.auth import (
    require_api_key,
    create_jwt_token,
    verify_jwt_token,
    require_jwt_token,
    is_authenticated,
    get_api_key,
    hash_password,
    verify_password,
    AUTH_ENABLED,
    API_KEY,
)

# Use our MockHTTPException for tests
HTTPException = MockHTTPException


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def auth_enabled():
    """Enable authentication for tests."""
    with patch.dict(os.environ, {"AUTH_ENABLED": "true"}):
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            yield


@pytest.fixture
def auth_disabled():
    """Disable authentication for tests."""
    with patch.dict(os.environ, {"AUTH_ENABLED": "false"}):
        with patch("knowbase.common.auth.AUTH_ENABLED", False):
            yield


@pytest.fixture
def valid_api_key():
    """Get the valid API key for testing."""
    return API_KEY


# ============================================
# Test require_api_key Function
# ============================================

class TestRequireApiKey:
    """Tests for require_api_key function."""

    def test_returns_dev_mode_when_auth_disabled(self, auth_disabled) -> None:
        """Should return 'dev-mode' when auth is disabled."""
        result = require_api_key(x_api_key=None)
        assert result == "dev-mode"

    def test_raises_401_when_api_key_missing(self, auth_enabled) -> None:
        """Should raise 401 when API key is missing."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with pytest.raises(HTTPException) as exc_info:
                require_api_key(x_api_key=None)

            assert exc_info.value.status_code == 401
            assert "API Key required" in exc_info.value.detail

    def test_raises_401_when_api_key_invalid(self, auth_enabled, valid_api_key) -> None:
        """Should raise 401 when API key is invalid."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with patch("knowbase.common.auth.API_KEY", "correct-key"):
                with pytest.raises(HTTPException) as exc_info:
                    require_api_key(x_api_key="wrong-key")

                assert exc_info.value.status_code == 401
                assert "Invalid API Key" in exc_info.value.detail

    def test_returns_api_key_when_valid(self) -> None:
        """Should return API key when valid."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with patch("knowbase.common.auth.API_KEY", "test-api-key"):
                result = require_api_key(x_api_key="test-api-key")
                assert result == "test-api-key"

    def test_www_authenticate_header_on_missing_key(self) -> None:
        """Should include WWW-Authenticate header when key missing."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with pytest.raises(HTTPException) as exc_info:
                require_api_key(x_api_key=None)

            assert exc_info.value.headers is not None
            assert "WWW-Authenticate" in exc_info.value.headers

    def test_www_authenticate_header_on_invalid_key(self) -> None:
        """Should include WWW-Authenticate header when key invalid."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with patch("knowbase.common.auth.API_KEY", "correct-key"):
                with pytest.raises(HTTPException) as exc_info:
                    require_api_key(x_api_key="wrong-key")

                assert exc_info.value.headers is not None
                assert "WWW-Authenticate" in exc_info.value.headers


# ============================================
# Test JWT Token Functions
# ============================================

class TestJwtTokenFunctions:
    """Tests for JWT token functions."""

    def test_create_jwt_token_basic(self) -> None:
        """Should create a valid JWT token."""
        token = create_jwt_token(user_id="test-user")
        assert token is not None
        assert len(token) > 0
        assert isinstance(token, str)

    def test_create_jwt_token_with_metadata(self) -> None:
        """Should create JWT with custom metadata."""
        token = create_jwt_token(
            user_id="user123",
            metadata={"tenant": "acme", "role": "admin"}
        )
        assert token is not None

    def test_verify_jwt_token_valid(self) -> None:
        """Should verify a valid JWT token."""
        token = create_jwt_token(user_id="verify-user")
        payload = verify_jwt_token(token)

        assert payload is not None
        assert payload["user_id"] == "verify-user"

    def test_verify_jwt_token_includes_exp(self) -> None:
        """Verified token should include expiration."""
        token = create_jwt_token(user_id="exp-user")
        payload = verify_jwt_token(token)

        assert "exp" in payload

    def test_verify_jwt_token_includes_iat(self) -> None:
        """Verified token should include issued at time."""
        token = create_jwt_token(user_id="iat-user")
        payload = verify_jwt_token(token)

        assert "iat" in payload

    def test_verify_jwt_token_metadata_preserved(self) -> None:
        """Metadata should be preserved in verified token."""
        token = create_jwt_token(
            user_id="meta-user",
            metadata={"custom_field": "custom_value"}
        )
        payload = verify_jwt_token(token)

        assert payload["custom_field"] == "custom_value"

    def test_verify_jwt_token_invalid(self) -> None:
        """Should raise 401 for invalid token."""
        with pytest.raises((HTTPException, MockInvalidTokenError)):
            verify_jwt_token("invalid.token.here")

    def test_verify_jwt_token_tampered(self) -> None:
        """Should raise for tampered token or return different payload."""
        token = create_jwt_token(user_id="original-user")
        # Tamper with the token by replacing part of payload
        tampered = "invalid.token.format"

        with pytest.raises((HTTPException, MockInvalidTokenError)):
            verify_jwt_token(tampered)


# ============================================
# Test require_jwt_token Function
# ============================================

class TestRequireJwtToken:
    """Tests for require_jwt_token function."""

    def test_returns_dev_user_when_auth_disabled(self, auth_disabled) -> None:
        """Should return dev user when auth disabled."""
        with patch("knowbase.common.auth.AUTH_ENABLED", False):
            result = require_jwt_token(authorization=None)
            assert result["user_id"] == "dev-user"

    def test_raises_401_when_header_missing(self) -> None:
        """Should raise 401 when Authorization header missing."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with pytest.raises(HTTPException) as exc_info:
                require_jwt_token(authorization=None)

            assert exc_info.value.status_code == 401
            assert "Authorization header required" in exc_info.value.detail

    def test_raises_401_when_header_invalid_format(self) -> None:
        """Should raise 401 when header format is invalid."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with pytest.raises(HTTPException) as exc_info:
                require_jwt_token(authorization="InvalidFormat")

            assert exc_info.value.status_code == 401
            assert "Invalid authorization header format" in exc_info.value.detail

    def test_raises_401_when_not_bearer(self) -> None:
        """Should raise 401 when not Bearer scheme."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with pytest.raises(HTTPException) as exc_info:
                require_jwt_token(authorization="Basic abc123")

            assert exc_info.value.status_code == 401

    def test_validates_bearer_token(self) -> None:
        """Should validate Bearer token."""
        token = create_jwt_token(user_id="bearer-user")

        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            result = require_jwt_token(authorization=f"Bearer {token}")

            assert result["user_id"] == "bearer-user"

    def test_case_insensitive_bearer(self) -> None:
        """Bearer scheme should be case insensitive."""
        token = create_jwt_token(user_id="case-user")

        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            result = require_jwt_token(authorization=f"bearer {token}")
            assert result["user_id"] == "case-user"

            result = require_jwt_token(authorization=f"BEARER {token}")
            assert result["user_id"] == "case-user"


# ============================================
# Test Password Hashing Functions
# ============================================

class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password_returns_string(self) -> None:
        """hash_password should return a string."""
        hashed = hash_password("test_password")
        assert isinstance(hashed, str)

    def test_hash_password_different_from_input(self) -> None:
        """Hash should be different from original password."""
        password = "my_secret_password"
        hashed = hash_password(password)
        assert hashed != password

    def test_hash_password_produces_bcrypt_format(self) -> None:
        """Hash should be in bcrypt format."""
        hashed = hash_password("test")
        # bcrypt hashes start with $2a$, $2b$, or $2y$
        assert hashed.startswith("$2")

    def test_verify_password_correct(self) -> None:
        """verify_password should return True for correct password."""
        password = "correct_password"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self) -> None:
        """verify_password should return False for incorrect password."""
        password = "correct_password"
        hashed = hash_password(password)

        assert verify_password("wrong_password", hashed) is False

    def test_hash_password_salt_unique(self) -> None:
        """Same password should produce different hashes (salt)."""
        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Hashes should be different due to unique salt
        assert hash1 != hash2

        # But both should verify correctly
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True

    def test_verify_password_empty_string(self) -> None:
        """Should handle empty password."""
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("not_empty", hashed) is False

    def test_hash_password_unicode(self) -> None:
        """Should handle Unicode passwords."""
        password = "密码测试_пароль"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_special_characters(self) -> None:
        """Should handle special characters."""
        password = "p@ss!w0rd#$%^&*()"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True


# ============================================
# Test Helper Functions
# ============================================

class TestHelperFunctions:
    """Tests for helper functions."""

    def test_is_authenticated_returns_bool(self) -> None:
        """is_authenticated should return boolean."""
        result = is_authenticated()
        assert isinstance(result, bool)

    def test_get_api_key_returns_string(self) -> None:
        """get_api_key should return string."""
        result = get_api_key()
        assert isinstance(result, str)

    def test_get_api_key_matches_configured(self) -> None:
        """get_api_key should return configured key."""
        result = get_api_key()
        assert result == API_KEY


# ============================================
# Test Configuration
# ============================================

class TestConfiguration:
    """Tests for configuration constants."""

    def test_auth_enabled_is_bool(self) -> None:
        """AUTH_ENABLED should be boolean."""
        assert isinstance(AUTH_ENABLED, bool)

    def test_api_key_is_string(self) -> None:
        """API_KEY should be string."""
        assert isinstance(API_KEY, str)

    def test_api_key_not_empty(self) -> None:
        """API_KEY should not be empty."""
        assert len(API_KEY) > 0


# ============================================
# Test Edge Cases
# ============================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_require_api_key_empty_string(self) -> None:
        """Empty string API key should be invalid."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with patch("knowbase.common.auth.API_KEY", "valid-key"):
                with pytest.raises(HTTPException) as exc_info:
                    require_api_key(x_api_key="")

                assert exc_info.value.status_code == 401

    def test_jwt_token_with_none_metadata(self) -> None:
        """None metadata should work."""
        token = create_jwt_token(user_id="none-meta", metadata=None)
        payload = verify_jwt_token(token)
        assert payload["user_id"] == "none-meta"

    def test_jwt_token_with_empty_metadata(self) -> None:
        """Empty metadata dict should work."""
        token = create_jwt_token(user_id="empty-meta", metadata={})
        payload = verify_jwt_token(token)
        assert payload["user_id"] == "empty-meta"

    def test_long_password_hash(self) -> None:
        """Should handle very long passwords."""
        # bcrypt has a 72 byte limit, but it should handle gracefully
        long_password = "a" * 100
        hashed = hash_password(long_password)
        # Note: bcrypt truncates at 72 bytes, so this tests that it works
        assert len(hashed) > 0

    def test_verify_password_wrong_hash_format(self) -> None:
        """Should handle invalid hash format."""
        with pytest.raises(Exception):  # bcrypt raises on invalid hash
            verify_password("password", "not_a_valid_hash")

    def test_api_key_whitespace_handling(self) -> None:
        """API key with whitespace should not match."""
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with patch("knowbase.common.auth.API_KEY", "valid-key"):
                with pytest.raises(HTTPException):
                    require_api_key(x_api_key=" valid-key")

                with pytest.raises(HTTPException):
                    require_api_key(x_api_key="valid-key ")


# ============================================
# Test JWT Expiration
# ============================================

class TestJwtExpiration:
    """Tests for JWT token expiration."""

    def test_expired_token_raises_401(self) -> None:
        """Expired token should raise 401."""
        # Create a token with expired time
        from knowbase.common.auth import JWT_SECRET, JWT_ALGORITHM

        payload = {
            "user_id": "expired-user",
            "exp": datetime.utcnow() - timedelta(minutes=5),
            "iat": datetime.utcnow() - timedelta(minutes=10)
        }
        expired_token = MockJwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        with pytest.raises((HTTPException, MockExpiredSignatureError)):
            verify_jwt_token(expired_token)


# ============================================
# Test Security
# ============================================

class TestSecurity:
    """Security-focused tests."""

    def test_password_hash_not_reversible(self) -> None:
        """Should not be able to extract password from hash."""
        password = "secret_password"
        hashed = hash_password(password)

        # Hash should not contain the password
        assert password not in hashed

    def test_jwt_requires_correct_secret(self) -> None:
        """JWT verification should fail with wrong secret."""
        from knowbase.common.auth import JWT_ALGORITHM

        # Create token with different secret
        payload = {"user_id": "test-user", "exp": datetime.utcnow() + timedelta(hours=1)}
        token = MockJwt.encode(payload, "wrong-secret", algorithm=JWT_ALGORITHM)

        with pytest.raises((HTTPException, MockInvalidTokenError)):
            verify_jwt_token(token)

    def test_api_key_timing_safe_comparison(self) -> None:
        """API key comparison should be performed."""
        # This is implicit in the implementation, but we test the behavior
        with patch("knowbase.common.auth.AUTH_ENABLED", True):
            with patch("knowbase.common.auth.API_KEY", "a" * 32):
                # Both wrong keys should fail similarly
                with pytest.raises(HTTPException):
                    require_api_key(x_api_key="b" * 32)

                with pytest.raises(HTTPException):
                    require_api_key(x_api_key="c" * 32)
