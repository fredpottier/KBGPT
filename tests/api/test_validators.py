"""
Tests pour validators d'input validation.

Phase 0 - Security Hardening - Semaine 2
"""
import pytest
from pydantic import ValidationError

from knowbase.api.validators import (
    validate_entity_type,
    validate_entity_name,
    validate_relation_type,
    EntityTypeValidator,
    EntityNameValidator,
    RelationTypeValidator,
)


# ============================================================
# Tests entity_type validation (15 tests)
# ============================================================

def test_validate_entity_type_valid():
    """Test entity_type valide."""
    assert validate_entity_type("PERSON") == "PERSON"
    assert validate_entity_type("ORGANIZATION") == "ORGANIZATION"
    assert validate_entity_type("SAP_MODULE") == "SAP_MODULE"
    assert validate_entity_type("A") == "A"  # 1 char OK
    assert validate_entity_type("A" * 50) == "A" * 50  # Max 50 chars


def test_validate_entity_type_with_numbers():
    """Test entity_type avec chiffres."""
    assert validate_entity_type("S4HANA") == "S4HANA"
    assert validate_entity_type("SAP2000") == "SAP2000"
    assert validate_entity_type("MODULE123") == "MODULE123"


def test_validate_entity_type_empty():
    """Test entity_type vide."""
    with pytest.raises(ValueError, match="ne peut pas être vide"):
        validate_entity_type("")


def test_validate_entity_type_lowercase_start():
    """Test entity_type commence par minuscule."""
    with pytest.raises(ValueError, match="doit commencer par une majuscule"):
        validate_entity_type("person")


def test_validate_entity_type_lowercase_middle():
    """Test entity_type avec minuscule au milieu."""
    with pytest.raises(ValueError, match="doit commencer par une majuscule"):
        validate_entity_type("PERson")


def test_validate_entity_type_special_chars():
    """Test entity_type avec caractères spéciaux."""
    with pytest.raises(ValueError, match="doit commencer par une majuscule"):
        validate_entity_type("PERSON-TYPE")

    with pytest.raises(ValueError, match="doit commencer par une majuscule"):
        validate_entity_type("PERSON.TYPE")

    with pytest.raises(ValueError, match="doit commencer par une majuscule"):
        validate_entity_type("PERSON TYPE")  # Espace


def test_validate_entity_type_too_long():
    """Test entity_type trop long (>50 chars)."""
    long_type = "A" * 51
    with pytest.raises(ValueError, match="doit commencer par une majuscule"):
        validate_entity_type(long_type)


def test_validate_entity_type_starts_with_underscore():
    """Test entity_type commence par underscore (système)."""
    with pytest.raises(ValueError, match="types système avec préfixe '_'"):
        validate_entity_type("_INTERNAL")


def test_validate_entity_type_starts_with_system():
    """Test entity_type commence par SYSTEM_ (système)."""
    with pytest.raises(ValueError, match="types système avec préfixe 'SYSTEM_'"):
        validate_entity_type("SYSTEM_CONFIG")


def test_validate_entity_type_starts_with_internal():
    """Test entity_type commence par INTERNAL_ (système)."""
    with pytest.raises(ValueError, match="types système avec préfixe 'INTERNAL_'"):
        validate_entity_type("INTERNAL_DATA")


def test_validate_entity_type_starts_with_double_underscore():
    """Test entity_type commence par __ (Python internals)."""
    with pytest.raises(ValueError, match="types système avec préfixe '__'"):
        validate_entity_type("__BUILTIN__")


def test_validate_entity_type_numbers_only():
    """Test entity_type commence par chiffre."""
    with pytest.raises(ValueError, match="doit commencer par une majuscule"):
        validate_entity_type("123TYPE")


def test_validate_entity_type_pydantic_model():
    """Test EntityTypeValidator avec Pydantic."""
    # Valid
    model = EntityTypeValidator(entity_type="PERSON")
    assert model.entity_type == "PERSON"

    # Invalid - lowercase
    with pytest.raises(ValidationError):
        EntityTypeValidator(entity_type="person")

    # Invalid - système
    with pytest.raises(ValidationError):
        EntityTypeValidator(entity_type="_INTERNAL")


def test_validate_entity_type_sql_injection_attempt():
    """Test entity_type avec tentative SQL injection."""
    with pytest.raises(ValueError):
        validate_entity_type("PERSON'; DROP TABLE users--")


def test_validate_entity_type_xss_attempt():
    """Test entity_type avec tentative XSS."""
    with pytest.raises(ValueError):
        validate_entity_type("PERSON<script>alert('xss')</script>")


# ============================================================
# Tests entity.name validation (15 tests)
# ============================================================

def test_validate_entity_name_valid():
    """Test entity.name valide."""
    assert validate_entity_name("John Doe") == "John Doe"
    assert validate_entity_name("SAP S/4HANA") == "SAP S/4HANA"
    assert validate_entity_name("Module-123") == "Module-123"
    assert validate_entity_name("Test (v2.0)") == "Test (v2.0)"


def test_validate_entity_name_empty():
    """Test entity.name vide."""
    with pytest.raises(ValueError, match="ne peut pas être vide"):
        validate_entity_name("")


def test_validate_entity_name_too_long():
    """Test entity.name trop long (>200 chars)."""
    long_name = "A" * 201
    with pytest.raises(ValueError, match="trop long"):
        validate_entity_name(long_name)


def test_validate_entity_name_max_length():
    """Test entity.name exactement 200 chars (OK)."""
    name = "A" * 200
    assert validate_entity_name(name) == name


def test_validate_entity_name_xss_angle_brackets():
    """Test entity.name avec < > (XSS)."""
    with pytest.raises(ValueError, match="prévention XSS"):
        validate_entity_name("User<script>")

    with pytest.raises(ValueError, match="prévention XSS"):
        validate_entity_name("User>script")


def test_validate_entity_name_xss_quotes():
    """Test entity.name avec quotes (XSS)."""
    with pytest.raises(ValueError, match="prévention XSS"):
        validate_entity_name('User"script')

    with pytest.raises(ValueError, match="prévention XSS"):
        validate_entity_name("User'script")


def test_validate_entity_name_path_traversal_unix():
    """Test entity.name avec path traversal Unix."""
    with pytest.raises(ValueError, match="path traversal"):
        validate_entity_name("../../etc/passwd")

    with pytest.raises(ValueError, match="path traversal"):
        validate_entity_name("User/../admin")


def test_validate_entity_name_path_traversal_windows():
    """Test entity.name avec path traversal Windows."""
    with pytest.raises(ValueError, match="path traversal"):
        validate_entity_name("..\\..\\windows\\system32")

    with pytest.raises(ValueError, match="path traversal"):
        validate_entity_name("User\\..\\admin")


def test_validate_entity_name_null_byte():
    """Test entity.name avec null byte."""
    with pytest.raises(ValueError, match="null byte"):
        validate_entity_name("User\x00Admin")


def test_validate_entity_name_strips_whitespace():
    """Test entity.name strip les espaces."""
    assert validate_entity_name("  User  ") == "User"
    assert validate_entity_name("\tUser\t") == "User"


def test_validate_entity_name_unicode():
    """Test entity.name avec Unicode (OK)."""
    assert validate_entity_name("Société Générale") == "Société Générale"
    assert validate_entity_name("北京") == "北京"


def test_validate_entity_name_pydantic_model():
    """Test EntityNameValidator avec Pydantic."""
    # Valid
    model = EntityNameValidator(name="John Doe")
    assert model.name == "John Doe"

    # Invalid - XSS
    with pytest.raises(ValidationError):
        EntityNameValidator(name="User<script>")

    # Invalid - path traversal
    with pytest.raises(ValidationError):
        EntityNameValidator(name="../../etc/passwd")


def test_validate_entity_name_sql_injection():
    """Test entity.name avec SQL injection (OK - pas de quotes)."""
    # Les quotes sont bloquées, donc SQL injection difficile
    with pytest.raises(ValueError, match="prévention XSS"):
        validate_entity_name("Admin' OR '1'='1")


def test_validate_entity_name_newlines():
    """Test entity.name avec newlines (OK)."""
    # Newlines sont autorisés (seront sanitizés dans logs)
    assert validate_entity_name("Line 1\nLine 2") == "Line 1\nLine 2"


def test_validate_entity_name_special_chars_allowed():
    """Test entity.name avec caractères spéciaux autorisés."""
    assert validate_entity_name("User-123") == "User-123"
    assert validate_entity_name("User@Email") == "User@Email"
    assert validate_entity_name("User & Co.") == "User & Co."
    assert validate_entity_name("User (Test)") == "User (Test)"


# ============================================================
# Tests relation_type validation (2 tests)
# ============================================================

def test_validate_relation_type_valid():
    """Test relation_type valide."""
    assert validate_relation_type("WORKS_AT") == "WORKS_AT"
    assert validate_relation_type("MANAGES") == "MANAGES"


def test_validate_relation_type_pydantic_model():
    """Test RelationTypeValidator avec Pydantic."""
    model = RelationTypeValidator(relation_type="WORKS_AT")
    assert model.relation_type == "WORKS_AT"

    with pytest.raises(ValidationError):
        RelationTypeValidator(relation_type="works_at")


# ============================================================
# Tests fuzzing (5 tests supplémentaires)
# ============================================================

def test_fuzzing_entity_type_random_chars():
    """Test fuzzing entity_type avec caractères aléatoires."""
    invalid_types = [
        "!@#$%",
        "PERSON\n\r\t",
        "PERSON\x00",
        "PER!SON",
        "PER$ON",
    ]

    for invalid_type in invalid_types:
        with pytest.raises(ValueError):
            validate_entity_type(invalid_type)


def test_fuzzing_entity_name_injection_attempts():
    """Test fuzzing entity.name avec tentatives d'injection."""
    injection_attempts = [
        "<img src=x onerror=alert(1)>",     # <> interdits
        "<svg/onload=alert(1)>",            # <> interdits
        "';DROP TABLE entities--",          # ' interdit
        "../../../../../../etc/shadow",     # ../ interdit
        '"><script>alert(1)</script>',      # " et <> interdits
    ]

    for attempt in injection_attempts:
        with pytest.raises(ValueError):
            validate_entity_name(attempt)


def test_fuzzing_entity_type_unicode_variants():
    """Test fuzzing entity_type avec Unicode variants."""
    # Unicode lookalikes (homoglyphs)
    invalid_types = [
        "ΡERSON",  # Greek rho au lieu de P
        "РERSON",  # Cyrillic P
        "ᏢERSON",  # Cherokee P
    ]

    for invalid_type in invalid_types:
        with pytest.raises(ValueError):
            validate_entity_type(invalid_type)


def test_fuzzing_entity_name_control_chars():
    """Test fuzzing entity.name avec control chars."""
    control_chars = [
        "User\x01Admin",
        "User\x02Admin",
        "User\x1fAdmin",
    ]

    # Control chars sont autorisés (seront sanitizés dans logs)
    # Sauf null byte qui est bloqué
    for name in control_chars:
        result = validate_entity_name(name)
        assert result is not None


def test_fuzzing_mixed_scripts():
    """Test fuzzing avec scripts mixtes (homograph attack)."""
    # Tentative homograph attack avec scripts mixtes
    with pytest.raises(ValueError):
        validate_entity_type("РERSON")  # P cyrillique au lieu de latin
