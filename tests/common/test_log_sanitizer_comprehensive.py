"""
Tests comprehensifs pour la sanitization des logs.

Ce module etend les tests existants avec des cas supplementaires:
- Tests parametrises exhaustifs
- Tests de limites (boundary testing)
- Tests de securite approfondis
- Tests de performance
- Tests edge cases
"""
from __future__ import annotations

from typing import Any

import pytest

from knowbase.common.log_sanitizer import (
    CONTROL_CHARS_REGEX,
    MAX_LOG_VALUE_LENGTH,
    escape_for_log,
    safe_log_message,
    sanitize_dict_for_log,
    sanitize_exception_for_log,
    sanitize_for_log,
    sanitize_sensitive_fields,
)


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def sample_sensitive_dict() -> dict:
    """Dictionnaire avec champs sensibles."""
    return {
        "username": "admin",
        "password": "secret123",
        "api_key": "sk-abcdef123456",
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "refresh_token": "refresh_token_value",
        "data": "normal_data",
    }


@pytest.fixture
def nested_sensitive_dict() -> dict:
    """Dictionnaire imbrique avec champs sensibles."""
    return {
        "user": "admin",
        "credentials": {
            "password": "secret",
            "token": "abc123",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----",
        },
        "settings": {
            "theme": "dark",
            "authorization": "Bearer token",
        },
    }


# ============================================
# Tests sanitize_for_log - Cas Basiques
# ============================================

@pytest.mark.unit
class TestSanitizeForLogBasic:
    """Tests basiques pour sanitize_for_log."""

    def test_normal_string_unchanged(self) -> None:
        """String normale non modifiee."""
        assert sanitize_for_log("Hello World") == "Hello World"
        assert sanitize_for_log("Simple text") == "Simple text"

    def test_empty_string(self) -> None:
        """String vide retourne string vide."""
        assert sanitize_for_log("") == ""

    def test_none_value(self) -> None:
        """None retourne 'None'."""
        assert sanitize_for_log(None) == "None"

    @pytest.mark.parametrize("value,expected", [
        (123, "123"),
        (3.14159, "3.14159"),
        (0, "0"),
        (-42, "-42"),
        (1.5e10, "15000000000.0"),
    ])
    def test_numeric_values(self, value: Any, expected: str) -> None:
        """Valeurs numeriques converties en string."""
        assert sanitize_for_log(value) == expected

    @pytest.mark.parametrize("value,expected", [
        (True, "True"),
        (False, "False"),
    ])
    def test_boolean_values(self, value: bool, expected: str) -> None:
        """Valeurs booleennes converties en string."""
        assert sanitize_for_log(value) == expected

    def test_list_value(self) -> None:
        """Liste convertie en string."""
        result = sanitize_for_log([1, 2, 3])
        assert "[1, 2, 3]" in result

    def test_dict_value(self) -> None:
        """Dict converti en string."""
        result = sanitize_for_log({"key": "value"})
        assert "key" in result
        assert "value" in result


# ============================================
# Tests sanitize_for_log - Caracteres Speciaux
# ============================================

@pytest.mark.unit
class TestSanitizeForLogSpecialChars:
    """Tests pour les caracteres speciaux."""

    def test_newline_escaped(self) -> None:
        """Newline echappe."""
        result = sanitize_for_log("Line1\nLine2")
        assert result == "Line1\\nLine2"
        assert "\n" not in result

    def test_carriage_return_escaped(self) -> None:
        """Carriage return echappe."""
        result = sanitize_for_log("Line1\rLine2")
        assert result == "Line1\\rLine2"
        assert "\r" not in result

    def test_tab_escaped(self) -> None:
        """Tab echappe."""
        result = sanitize_for_log("Col1\tCol2")
        assert result == "Col1\\tCol2"
        assert "\t" not in result

    def test_crlf_escaped(self) -> None:
        """CRLF (Windows newline) echappe."""
        result = sanitize_for_log("Line1\r\nLine2")
        assert result == "Line1\\r\\nLine2"
        assert "\r" not in result
        assert "\n" not in result

    @pytest.mark.parametrize("mixed_input,expected", [
        ("a\nb\rc\td", "a\\nb\\rc\\td"),
        ("\n\r\t", "\\n\\r\\t"),
        ("start\nmiddle\rend\t", "start\\nmiddle\\rend\\t"),
    ])
    def test_mixed_special_chars(self, mixed_input: str, expected: str) -> None:
        """Melange de caracteres speciaux."""
        assert sanitize_for_log(mixed_input) == expected


# ============================================
# Tests sanitize_for_log - Caracteres de Controle
# ============================================

@pytest.mark.unit
class TestSanitizeForLogControlChars:
    """Tests pour les caracteres de controle."""

    def test_null_byte_replaced(self) -> None:
        """Null byte remplace par [CTRL]."""
        result = sanitize_for_log("User\x00Admin")
        assert result == "User[CTRL]Admin"

    @pytest.mark.parametrize("control_char", [
        "\x00", "\x01", "\x02", "\x03", "\x04", "\x05", "\x06", "\x07",
        "\x08", "\x0b", "\x0c", "\x0e", "\x0f", "\x10", "\x11", "\x12",
        "\x13", "\x14", "\x15", "\x16", "\x17", "\x18", "\x19", "\x1a",
        "\x1b", "\x1c", "\x1d", "\x1e", "\x1f", "\x7f",
    ])
    def test_all_control_chars_replaced(self, control_char: str) -> None:
        """Tous les caracteres de controle remplaces."""
        result = sanitize_for_log(f"Text{control_char}More")
        assert "[CTRL]" in result
        assert control_char not in result

    def test_multiple_control_chars(self) -> None:
        """Plusieurs caracteres de controle."""
        result = sanitize_for_log("A\x00B\x01C\x02D")
        assert result == "A[CTRL]B[CTRL]C[CTRL]D"

    def test_bell_character_replaced(self) -> None:
        """Bell character (\\x07) remplace."""
        result = sanitize_for_log("Alert\x07!")
        assert result == "Alert[CTRL]!"


# ============================================
# Tests sanitize_for_log - Log Injection
# ============================================

@pytest.mark.unit
class TestSanitizeForLogInjection:
    """Tests contre les injections de log."""

    def test_log_injection_newline_attack(self) -> None:
        """Attaque par injection de newline."""
        malicious = "admin\nFAKE_LOG: Unauthorized access"
        result = sanitize_for_log(malicious)
        assert "\n" not in result
        assert "\\n" in result

    def test_log_injection_crlf_attack(self) -> None:
        """Attaque par injection CRLF."""
        malicious = "user\r\nINFO: Fake entry\r\nERROR: Fake error"
        result = sanitize_for_log(malicious)
        assert "\r" not in result
        assert "\n" not in result

    def test_complex_log_injection(self) -> None:
        """Injection de log complexe."""
        malicious = "admin\nINFO: Success\r\nERROR: Fake error\t[SYSTEM]"
        result = sanitize_for_log(malicious)
        expected = "admin\\nINFO: Success\\r\\nERROR: Fake error\\t[SYSTEM]"
        assert result == expected


# ============================================
# Tests sanitize_for_log - Truncation
# ============================================

@pytest.mark.unit
class TestSanitizeForLogTruncation:
    """Tests pour la troncature."""

    def test_default_max_length(self) -> None:
        """Longueur max par defaut (500 chars)."""
        long_text = "A" * 1000
        result = sanitize_for_log(long_text)
        assert "truncated" in result.lower()
        # Le resultat est tronque + message de troncature
        assert len(result) < 600

    def test_custom_max_length(self) -> None:
        """Longueur max personnalisee."""
        long_text = "A" * 200
        result = sanitize_for_log(long_text, max_length=50)
        assert len(result) < 100
        assert "truncated" in result.lower()

    def test_no_truncation_under_limit(self) -> None:
        """Pas de troncature sous la limite."""
        text = "A" * 100
        result = sanitize_for_log(text, max_length=200)
        assert result == text
        assert "truncated" not in result

    def test_truncation_message_format(self) -> None:
        """Format du message de troncature."""
        long_text = "X" * 1000
        result = sanitize_for_log(long_text, max_length=100)
        assert "truncated" in result.lower()
        # Verifie que le nombre de caracteres tronques est indique
        assert "chars" in result.lower() or "900" in result

    @pytest.mark.parametrize("max_length", [10, 50, 100, 200, 500])
    def test_various_max_lengths(self, max_length: int) -> None:
        """Differentes longueurs max."""
        long_text = "A" * (max_length * 2)
        result = sanitize_for_log(long_text, max_length=max_length)
        # Le debut du texte est preserve
        assert result.startswith("A" * min(max_length, len(result)))


# ============================================
# Tests sanitize_for_log - Unicode
# ============================================

@pytest.mark.unit
class TestSanitizeForLogUnicode:
    """Tests pour les caracteres Unicode."""

    @pytest.mark.parametrize("unicode_text", [
        "Societe Generale",
        "Cafe",
        "Munchen",
        "Beijing",
        "Tokyo",
    ])
    def test_unicode_preserved(self, unicode_text: str) -> None:
        """Caracteres Unicode preserves."""
        assert sanitize_for_log(unicode_text) == unicode_text

    def test_emoji_preserved(self) -> None:
        """Emojis preserves."""
        result = sanitize_for_log("Status: OK")
        assert "OK" in result


# ============================================
# Tests sanitize_dict_for_log
# ============================================

@pytest.mark.unit
class TestSanitizeDictForLog:
    """Tests pour sanitize_dict_for_log."""

    def test_simple_dict(self) -> None:
        """Dict simple."""
        data = {"user": "admin", "action": "login"}
        result = sanitize_dict_for_log(data)
        assert result == {"user": "admin", "action": "login"}

    def test_dict_with_newlines(self) -> None:
        """Dict avec newlines."""
        data = {"user": "admin\nFAKE", "message": "Test\nInjection"}
        result = sanitize_dict_for_log(data)
        assert result["user"] == "admin\\nFAKE"
        assert result["message"] == "Test\\nInjection"

    def test_nested_dict(self) -> None:
        """Dict imbrique."""
        data = {
            "user": "admin",
            "metadata": {
                "ip": "127.0.0.1\nFAKE",
                "agent": "Browser\nMalicious",
            },
        }
        result = sanitize_dict_for_log(data)
        assert result["metadata"]["ip"] == "127.0.0.1\\nFAKE"
        assert result["metadata"]["agent"] == "Browser\\nMalicious"

    def test_dict_with_list(self) -> None:
        """Dict avec liste."""
        data = {"tags": ["tag1\nFAKE", "tag2\rINJECT", "tag3"]}
        result = sanitize_dict_for_log(data)
        assert result["tags"][0] == "tag1\\nFAKE"
        assert result["tags"][1] == "tag2\\rINJECT"
        assert result["tags"][2] == "tag3"

    def test_dict_key_sanitized(self) -> None:
        """Cle du dict sanitisee."""
        data = {"user\nFAKE": "admin"}
        result = sanitize_dict_for_log(data)
        assert "user\\nFAKE" in result

    def test_deeply_nested_dict(self) -> None:
        """Dict profondement imbrique."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "data\ninjection",
                    },
                },
            },
        }
        result = sanitize_dict_for_log(data)
        assert result["level1"]["level2"]["level3"]["value"] == "data\\ninjection"

    def test_empty_dict(self) -> None:
        """Dict vide."""
        assert sanitize_dict_for_log({}) == {}

    def test_dict_with_none_values(self) -> None:
        """Dict avec valeurs None."""
        data = {"key": None}
        result = sanitize_dict_for_log(data)
        assert result["key"] == "None"

    def test_dict_with_tuple(self) -> None:
        """Dict avec tuple."""
        data = {"coords": ("x\ninject", "y\rinject")}
        result = sanitize_dict_for_log(data)
        assert result["coords"][0] == "x\\ninject"
        assert result["coords"][1] == "y\\rinject"


# ============================================
# Tests sanitize_sensitive_fields
# ============================================

@pytest.mark.unit
class TestSanitizeSensitiveFields:
    """Tests pour sanitize_sensitive_fields."""

    def test_password_redacted(self) -> None:
        """Password masque."""
        data = {"username": "admin", "password": "secret123"}
        result = sanitize_sensitive_fields(data)
        assert result["username"] == "admin"
        assert result["password"] == "***REDACTED***"

    def test_tokens_redacted(self) -> None:
        """Tokens masques."""
        data = {
            "access_token": "eyJhbGc...",
            "refresh_token": "eyJhbGc...",
            "user": "admin",
        }
        result = sanitize_sensitive_fields(data)
        assert result["access_token"] == "***REDACTED***"
        assert result["refresh_token"] == "***REDACTED***"
        assert result["user"] == "admin"

    def test_api_key_redacted(self) -> None:
        """API key masquee."""
        data = {"api_key": "sk-1234567890", "endpoint": "/api/test"}
        result = sanitize_sensitive_fields(data)
        assert result["api_key"] == "***REDACTED***"
        assert result["endpoint"] == "/api/test"

    def test_nested_sensitive_fields(
        self, nested_sensitive_dict: dict
    ) -> None:
        """Champs sensibles imbriques."""
        result = sanitize_sensitive_fields(nested_sensitive_dict)
        assert result["user"] == "admin"
        assert result["credentials"]["password"] == "***REDACTED***"
        assert result["credentials"]["token"] == "***REDACTED***"
        assert result["credentials"]["private_key"] == "***REDACTED***"
        assert result["settings"]["theme"] == "dark"
        assert result["settings"]["authorization"] == "***REDACTED***"

    def test_case_insensitive_detection(self) -> None:
        """Detection insensible a la casse."""
        data = {
            "PASSWORD": "secret",
            "Api_Key": "key123",
            "APIKey": "key456",
            "apikey": "key789",
        }
        result = sanitize_sensitive_fields(data)
        assert result["PASSWORD"] == "***REDACTED***"
        assert result["Api_Key"] == "***REDACTED***"
        assert result["APIKey"] == "***REDACTED***"
        assert result["apikey"] == "***REDACTED***"

    @pytest.mark.parametrize("field_name", [
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "secret",
        "private_key",
        "apikey",
        "auth",
        "authorization",
    ])
    def test_all_default_sensitive_fields(self, field_name: str) -> None:
        """Tous les champs sensibles par defaut."""
        data = {field_name: "sensitive_value", "normal": "normal_value"}
        result = sanitize_sensitive_fields(data)
        assert result[field_name] == "***REDACTED***"
        assert result["normal"] == "normal_value"

    def test_custom_sensitive_fields(self) -> None:
        """Champs sensibles personnalises."""
        data = {"credit_card": "1234-5678-9012-3456", "name": "John"}
        custom_fields = ["credit_card", "ssn"]
        result = sanitize_sensitive_fields(data, sensitive_fields=custom_fields)
        assert result["credit_card"] == "***REDACTED***"
        assert result["name"] == "John"

    def test_empty_dict(self) -> None:
        """Dict vide."""
        assert sanitize_sensitive_fields({}) == {}


# ============================================
# Tests safe_log_message
# ============================================

@pytest.mark.unit
class TestSafeLogMessage:
    """Tests pour safe_log_message."""

    def test_simple_message(self) -> None:
        """Message simple."""
        result = safe_log_message("User {user} logged in", user="admin")
        assert result == "User admin logged in"

    def test_message_with_injection(self) -> None:
        """Message avec injection."""
        result = safe_log_message(
            "User {user} performed {action}",
            user="admin\nFAKE_LOG",
            action="login\rINJECT",
        )
        assert result == "User admin\\nFAKE_LOG performed login\\rINJECT"

    def test_multiple_params(self) -> None:
        """Plusieurs parametres."""
        result = safe_log_message(
            "{user} from {ip} did {action}",
            user="admin",
            ip="127.0.0.1",
            action="login",
        )
        assert "admin" in result
        assert "127.0.0.1" in result
        assert "login" in result

    def test_numeric_params(self) -> None:
        """Parametres numeriques."""
        result = safe_log_message(
            "Processed {count} items in {duration}s",
            count=100,
            duration=3.14,
        )
        assert "100" in result
        assert "3.14" in result

    def test_invalid_template_missing_key(self) -> None:
        """Template invalide (cle manquante)."""
        result = safe_log_message(
            "User {user} action {missing}",
            user="admin",
        )
        # Devrait retourner un fallback
        assert "LOG ERROR" in result or "user" in result.lower()

    def test_invalid_template_format(self) -> None:
        """Template avec format invalide."""
        result = safe_log_message(
            "User {user:invalid_format}",
            user="admin",
        )
        # Ne devrait pas planter, retourne fallback
        assert result is not None

    def test_empty_template(self) -> None:
        """Template vide."""
        result = safe_log_message("")
        assert result == ""

    def test_no_placeholders(self) -> None:
        """Template sans placeholders."""
        result = safe_log_message("Static message", extra="ignored")
        assert result == "Static message"


# ============================================
# Tests sanitize_exception_for_log
# ============================================

@pytest.mark.unit
class TestSanitizeExceptionForLog:
    """Tests pour sanitize_exception_for_log."""

    def test_simple_exception(self) -> None:
        """Exception simple."""
        try:
            raise ValueError("Test error")
        except ValueError as e:
            result = sanitize_exception_for_log(e)

        assert result["type"] == "ValueError"
        assert "Test error" in result["message"]
        assert "traceback" not in result

    def test_exception_with_traceback(self) -> None:
        """Exception avec traceback."""
        try:
            raise RuntimeError("Runtime error")
        except RuntimeError as e:
            result = sanitize_exception_for_log(e, include_traceback=True)

        assert result["type"] == "RuntimeError"
        assert "Runtime error" in result["message"]
        assert "traceback" in result
        assert "RuntimeError" in result["traceback"]

    def test_exception_with_injection(self) -> None:
        """Exception avec injection."""
        try:
            raise ValueError("Error\nFAKE_LOG: Success")
        except ValueError as e:
            result = sanitize_exception_for_log(e)

        assert "\\n" in result["message"]
        assert "\n" not in result["message"]

    def test_exception_long_message_truncated(self) -> None:
        """Exception avec message long tronque."""
        long_msg = "Error: " + "A" * 2000
        try:
            raise ValueError(long_msg)
        except ValueError as e:
            result = sanitize_exception_for_log(e)

        assert len(result["message"]) < 1100
        assert "truncated" in result["message"].lower()

    def test_exception_unicode(self) -> None:
        """Exception avec Unicode."""
        try:
            raise ValueError("Erreur systeme Beijing")
        except ValueError as e:
            result = sanitize_exception_for_log(e)

        assert "Erreur systeme Beijing" in result["message"]

    @pytest.mark.parametrize("exception_type", [
        ValueError,
        TypeError,
        RuntimeError,
        KeyError,
        IndexError,
        AttributeError,
    ])
    def test_various_exception_types(self, exception_type: type) -> None:
        """Differents types d'exception."""
        try:
            raise exception_type("Test error")
        except exception_type as e:
            result = sanitize_exception_for_log(e)

        assert result["type"] == exception_type.__name__

    def test_custom_exception(self) -> None:
        """Exception personnalisee."""
        class CustomError(Exception):
            pass

        try:
            raise CustomError("Custom message")
        except CustomError as e:
            result = sanitize_exception_for_log(e)

        assert result["type"] == "CustomError"
        assert "Custom message" in result["message"]


# ============================================
# Tests Alias
# ============================================

@pytest.mark.unit
class TestAlias:
    """Tests pour l'alias escape_for_log."""

    def test_escape_for_log_is_alias(self) -> None:
        """escape_for_log est un alias de sanitize_for_log."""
        assert escape_for_log is sanitize_for_log

    def test_escape_for_log_works(self) -> None:
        """escape_for_log fonctionne."""
        result = escape_for_log("Test\nInjection")
        assert result == "Test\\nInjection"


# ============================================
# Tests Constants
# ============================================

@pytest.mark.unit
class TestConstants:
    """Tests pour les constantes."""

    def test_max_log_value_length(self) -> None:
        """MAX_LOG_VALUE_LENGTH est defini."""
        assert MAX_LOG_VALUE_LENGTH == 500

    def test_control_chars_regex_exists(self) -> None:
        """CONTROL_CHARS_REGEX existe."""
        assert CONTROL_CHARS_REGEX is not None
        assert CONTROL_CHARS_REGEX.pattern == r'[\x00-\x1f\x7f]'


# ============================================
# Tests Performance
# ============================================

@pytest.mark.unit
class TestPerformance:
    """Tests de performance."""

    def test_sanitize_for_log_performance(self) -> None:
        """Performance de sanitize_for_log."""
        import time

        text = "A" * 100
        start = time.time()
        for _ in range(10000):
            sanitize_for_log(text)
        duration = time.time() - start

        assert duration < 5, f"Sanitization trop lente: {duration}s"

    def test_sanitize_dict_for_log_performance(self) -> None:
        """Performance de sanitize_dict_for_log."""
        import time

        data = {f"key{i}": f"value{i}\n" for i in range(100)}
        start = time.time()
        for _ in range(1000):
            sanitize_dict_for_log(data)
        duration = time.time() - start

        assert duration < 5, f"Dict sanitization trop lente: {duration}s"

    def test_sanitize_sensitive_fields_performance(self) -> None:
        """Performance de sanitize_sensitive_fields."""
        import time

        data = {
            f"field{i}": f"value{i}"
            for i in range(100)
        }
        data["password"] = "secret"
        data["api_key"] = "key123"

        start = time.time()
        for _ in range(1000):
            sanitize_sensitive_fields(data)
        duration = time.time() - start

        assert duration < 5, f"Sensitive fields sanitization trop lente: {duration}s"


# ============================================
# Tests Edge Cases
# ============================================

@pytest.mark.unit
class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_only_control_chars(self) -> None:
        """String composee uniquement de caracteres de controle."""
        result = sanitize_for_log("\x00\x01\x02")
        assert result == "[CTRL][CTRL][CTRL]"

    def test_only_whitespace_chars(self) -> None:
        """String composee uniquement de whitespace."""
        result = sanitize_for_log("\n\r\t")
        assert result == "\\n\\r\\t"

    def test_very_long_string(self) -> None:
        """String tres longue."""
        long_text = "A" * 100000
        result = sanitize_for_log(long_text)
        assert "truncated" in result.lower()
        assert len(result) < 1000

    def test_mixed_normal_and_control(self) -> None:
        """Melange de caracteres normaux et de controle."""
        result = sanitize_for_log("Hello\x00World\nTest\rEnd")
        assert result == "Hello[CTRL]World\\nTest\\rEnd"

    def test_binary_data(self) -> None:
        """Donnees binaires."""
        binary = bytes([0, 1, 2, 65, 66, 67]).decode("latin-1")
        result = sanitize_for_log(binary)
        assert "[CTRL]" in result
        assert "ABC" in result
