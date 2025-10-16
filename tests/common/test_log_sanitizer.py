"""
Tests pour log sanitization.

Phase 0 - Security Hardening - Semaine 2.3
"""
import pytest

from knowbase.common.log_sanitizer import (
    sanitize_for_log,
    sanitize_dict_for_log,
    sanitize_sensitive_fields,
    safe_log_message,
    sanitize_exception_for_log,
)


# ============================================================
# Tests sanitize_for_log (15 tests)
# ============================================================

def test_sanitize_for_log_normal_string():
    """Test sanitization string normale."""
    assert sanitize_for_log("Hello World") == "Hello World"


def test_sanitize_for_log_newline():
    """Test sanitization avec newline (log injection)."""
    result = sanitize_for_log("User admin\nWARNING: Fake log entry")
    assert result == "User admin\\nWARNING: Fake log entry"
    assert '\n' not in result  # Pas de vrai newline


def test_sanitize_for_log_carriage_return():
    """Test sanitization avec carriage return."""
    result = sanitize_for_log("Line 1\rLine 2")
    assert result == "Line 1\\rLine 2"


def test_sanitize_for_log_tab():
    """Test sanitization avec tab."""
    result = sanitize_for_log("Column1\tColumn2")
    assert result == "Column1\\tColumn2"


def test_sanitize_for_log_null_byte():
    """Test sanitization avec null byte."""
    result = sanitize_for_log("User\x00Admin")
    assert result == "User[CTRL]Admin"


def test_sanitize_for_log_control_chars():
    """Test sanitization avec caractères de contrôle."""
    result = sanitize_for_log("Text\x01\x02\x03More")
    assert result == "Text[CTRL][CTRL][CTRL]More"


def test_sanitize_for_log_bell_char():
    """Test sanitization avec bell character."""
    result = sanitize_for_log("Alert\x07Message")
    assert result == "Alert[CTRL]Message"


def test_sanitize_for_log_mixed_injection():
    """Test sanitization avec injection complexe."""
    malicious = "admin\nINFO: Success\r\nERROR: Fake error\t[SYSTEM]"
    result = sanitize_for_log(malicious)
    expected = "admin\\nINFO: Success\\r\\nERROR: Fake error\\t[SYSTEM]"
    assert result == expected


def test_sanitize_for_log_truncate_long():
    """Test sanitization tronque les longues valeurs."""
    long_text = "A" * 1000
    result = sanitize_for_log(long_text, max_length=100)
    assert len(result) < 150  # ~100 + message truncation
    assert "truncated" in result.lower()


def test_sanitize_for_log_none_value():
    """Test sanitization avec None."""
    assert sanitize_for_log(None) == "None"


def test_sanitize_for_log_number():
    """Test sanitization avec nombre."""
    assert sanitize_for_log(12345) == "12345"
    assert sanitize_for_log(3.14159) == "3.14159"


def test_sanitize_for_log_boolean():
    """Test sanitization avec boolean."""
    assert sanitize_for_log(True) == "True"
    assert sanitize_for_log(False) == "False"


def test_sanitize_for_log_list():
    """Test sanitization avec liste."""
    result = sanitize_for_log([1, 2, 3])
    assert "[1, 2, 3]" in result


def test_sanitize_for_log_unicode():
    """Test sanitization avec Unicode (OK)."""
    assert sanitize_for_log("Société Générale") == "Société Générale"
    assert sanitize_for_log("北京") == "北京"


def test_sanitize_for_log_empty_string():
    """Test sanitization avec string vide."""
    assert sanitize_for_log("") == ""


# ============================================================
# Tests sanitize_dict_for_log (5 tests)
# ============================================================

def test_sanitize_dict_for_log_simple():
    """Test sanitization dict simple."""
    data = {"user": "admin", "action": "login"}
    result = sanitize_dict_for_log(data)
    assert result == {"user": "admin", "action": "login"}


def test_sanitize_dict_for_log_with_newlines():
    """Test sanitization dict avec newlines."""
    data = {"user": "admin\nFAKE", "message": "Test\nInjection"}
    result = sanitize_dict_for_log(data)
    assert result["user"] == "admin\\nFAKE"
    assert result["message"] == "Test\\nInjection"


def test_sanitize_dict_for_log_nested():
    """Test sanitization dict imbriqué."""
    data = {
        "user": "admin",
        "metadata": {
            "ip": "127.0.0.1\nFAKE",
            "agent": "Browser\nMalicious"
        }
    }
    result = sanitize_dict_for_log(data)
    assert result["metadata"]["ip"] == "127.0.0.1\\nFAKE"
    assert result["metadata"]["agent"] == "Browser\\nMalicious"


def test_sanitize_dict_for_log_with_list():
    """Test sanitization dict avec liste."""
    data = {"tags": ["tag1\nFAKE", "tag2\rINJECT", "tag3"]}
    result = sanitize_dict_for_log(data)
    assert result["tags"][0] == "tag1\\nFAKE"
    assert result["tags"][1] == "tag2\\rINJECT"
    assert result["tags"][2] == "tag3"


def test_sanitize_dict_for_log_key_injection():
    """Test sanitization dict avec injection dans la clé."""
    data = {"user\nFAKE": "admin"}
    result = sanitize_dict_for_log(data)
    assert "user\\nFAKE" in result


# ============================================================
# Tests sanitize_sensitive_fields (5 tests)
# ============================================================

def test_sanitize_sensitive_fields_password():
    """Test masquage password."""
    data = {"username": "admin", "password": "secret123"}
    result = sanitize_sensitive_fields(data)
    assert result["username"] == "admin"
    assert result["password"] == "***REDACTED***"


def test_sanitize_sensitive_fields_tokens():
    """Test masquage tokens."""
    data = {
        "access_token": "eyJhbGc...",
        "refresh_token": "eyJhbGc...",
        "user": "admin"
    }
    result = sanitize_sensitive_fields(data)
    assert result["access_token"] == "***REDACTED***"
    assert result["refresh_token"] == "***REDACTED***"
    assert result["user"] == "admin"


def test_sanitize_sensitive_fields_api_key():
    """Test masquage API key."""
    data = {"api_key": "sk-1234567890", "endpoint": "/api/test"}
    result = sanitize_sensitive_fields(data)
    assert result["api_key"] == "***REDACTED***"
    assert result["endpoint"] == "/api/test"


def test_sanitize_sensitive_fields_nested():
    """Test masquage dans dict imbriqué."""
    data = {
        "user": "admin",
        "credentials": {
            "password": "secret",
            "token": "abc123"
        }
    }
    result = sanitize_sensitive_fields(data)
    assert result["user"] == "admin"
    assert result["credentials"]["password"] == "***REDACTED***"
    assert result["credentials"]["token"] == "***REDACTED***"


def test_sanitize_sensitive_fields_case_insensitive():
    """Test masquage case-insensitive."""
    data = {"PASSWORD": "secret", "Api_Key": "key123"}
    result = sanitize_sensitive_fields(data)
    assert result["PASSWORD"] == "***REDACTED***"
    assert result["Api_Key"] == "***REDACTED***"


# ============================================================
# Tests safe_log_message (5 tests)
# ============================================================

def test_safe_log_message_simple():
    """Test safe_log_message simple."""
    result = safe_log_message("User {user} logged in", user="admin")
    assert result == "User admin logged in"


def test_safe_log_message_with_injection():
    """Test safe_log_message avec injection."""
    result = safe_log_message(
        "User {user} performed {action}",
        user="admin\nFAKE_LOG",
        action="login\rINJECT"
    )
    assert result == "User admin\\nFAKE_LOG performed login\\rINJECT"


def test_safe_log_message_multiple_params():
    """Test safe_log_message avec plusieurs params."""
    result = safe_log_message(
        "User {user} from {ip} action {action}",
        user="admin",
        ip="127.0.0.1",
        action="login"
    )
    assert "admin" in result
    assert "127.0.0.1" in result
    assert "login" in result


def test_safe_log_message_with_numbers():
    """Test safe_log_message avec nombres."""
    result = safe_log_message(
        "Processed {count} items in {duration}s",
        count=100,
        duration=3.14
    )
    assert "100" in result
    assert "3.14" in result


def test_safe_log_message_invalid_template():
    """Test safe_log_message avec template invalide."""
    result = safe_log_message(
        "User {user} action {missing}",  # {missing} pas dans kwargs
        user="admin"
    )
    # Devrait retourner un fallback au lieu de planter
    assert "LOG ERROR" in result or "admin" in result


# ============================================================
# Tests sanitize_exception_for_log (5 tests)
# ============================================================

def test_sanitize_exception_for_log_simple():
    """Test sanitization exception simple."""
    try:
        raise ValueError("Test error")
    except ValueError as e:
        result = sanitize_exception_for_log(e)

    assert result["type"] == "ValueError"
    assert "Test error" in result["message"]
    assert "traceback" not in result  # Par défaut pas de traceback


def test_sanitize_exception_for_log_with_traceback():
    """Test sanitization exception avec traceback."""
    try:
        raise RuntimeError("Runtime error")
    except RuntimeError as e:
        result = sanitize_exception_for_log(e, include_traceback=True)

    assert result["type"] == "RuntimeError"
    assert "Runtime error" in result["message"]
    assert "traceback" in result
    assert "RuntimeError" in result["traceback"]


def test_sanitize_exception_for_log_with_injection():
    """Test sanitization exception avec injection dans message."""
    try:
        raise ValueError("Error\nFAKE_LOG: Success")
    except ValueError as e:
        result = sanitize_exception_for_log(e)

    assert "Error\\nFAKE_LOG: Success" in result["message"]


def test_sanitize_exception_for_log_long_message():
    """Test sanitization exception avec message long."""
    long_msg = "Error: " + "A" * 2000
    try:
        raise ValueError(long_msg)
    except ValueError as e:
        result = sanitize_exception_for_log(e)

    # Message tronqué à max 1000 chars
    assert len(result["message"]) < 1100
    assert "truncated" in result["message"].lower()


def test_sanitize_exception_for_log_unicode():
    """Test sanitization exception avec Unicode."""
    try:
        raise ValueError("Erreur système 北京")
    except ValueError as e:
        result = sanitize_exception_for_log(e)

    assert "Erreur système 北京" in result["message"]
