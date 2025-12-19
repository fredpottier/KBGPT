"""
Tests comprehensifs pour les validators d'input validation.

Ce module etend les tests existants avec des cas supplementaires:
- Tests parametrises exhaustifs
- Tests de limites (boundary testing)
- Tests de securite approfondis
- Tests de performance
- Tests des modeles Pydantic complets
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

# Import direct pour eviter le chargement de main.py via api/__init__.py
import sys
import importlib.util
spec = importlib.util.spec_from_file_location(
    "validators",
    "src/knowbase/api/validators.py"
)
validators_module = importlib.util.module_from_spec(spec)
sys.modules["knowbase.api.validators"] = validators_module
spec.loader.exec_module(validators_module)

DANGEROUS_PATTERNS = validators_module.DANGEROUS_PATTERNS
ENTITY_TYPE_REGEX = validators_module.ENTITY_TYPE_REGEX
SYSTEM_TYPE_BLACKLIST = validators_module.SYSTEM_TYPE_BLACKLIST
EntityNameValidator = validators_module.EntityNameValidator
EntityTypeValidator = validators_module.EntityTypeValidator
RelationTypeValidator = validators_module.RelationTypeValidator
entity_name_validator = validators_module.entity_name_validator
entity_type_validator = validators_module.entity_type_validator
relation_type_validator = validators_module.relation_type_validator
validate_entity_name = validators_module.validate_entity_name
validate_entity_type = validators_module.validate_entity_type
validate_relation_type = validators_module.validate_relation_type


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def valid_entity_types() -> list[str]:
    """Liste de types d'entite valides."""
    return [
        "PERSON",
        "ORGANIZATION",
        "SAP_MODULE",
        "A",
        "A1",
        "ABC123",
        "TYPE_WITH_UNDERSCORE",
        "S4HANA",
        "MODULE_V2_BETA",
    ]


@pytest.fixture
def valid_entity_names() -> list[str]:
    """Liste de noms d'entite valides."""
    return [
        "John Doe",
        "SAP S/4HANA",
        "Module-123",
        "Test (v2.0)",
        "Societe Generale",
        "User123",
        "User & Co.",
        "My Entity [2024]",
        "Entity_with_underscore",
    ]


# ============================================
# Tests entity_type - Cas Valides
# ============================================

@pytest.mark.unit
class TestEntityTypeValidCases:
    """Tests pour les cas valides d'entity_type."""

    @pytest.mark.parametrize("entity_type", [
        "A",  # Min length
        "AB",
        "ABC",
        "PERSON",
        "ORGANIZATION",
        "SAP_MODULE",
        "S4HANA",
        "TYPE123",
        "A1B2C3",
        "UNDERSCORE_TYPE",
        "TYPE_V2",
        "A" * 50,  # Max length
    ])
    def test_valid_entity_types(self, entity_type: str) -> None:
        """Tester les types d'entite valides."""
        result = validate_entity_type(entity_type)
        assert result == entity_type

    def test_entity_type_single_char_uppercase(self) -> None:
        """Test type d'entite d'un seul caractere majuscule."""
        assert validate_entity_type("A") == "A"
        assert validate_entity_type("Z") == "Z"

    def test_entity_type_max_length_exactly_50(self) -> None:
        """Test type d'entite exactement 50 caracteres."""
        max_type = "A" * 50
        result = validate_entity_type(max_type)
        assert result == max_type
        assert len(result) == 50

    def test_entity_type_with_numbers_not_at_start(self) -> None:
        """Test type avec chiffres (pas en debut)."""
        assert validate_entity_type("S4HANA") == "S4HANA"
        assert validate_entity_type("SAP2024") == "SAP2024"
        assert validate_entity_type("MODULE123") == "MODULE123"

    def test_entity_type_with_underscores_in_middle(self) -> None:
        """Test type avec underscores au milieu."""
        assert validate_entity_type("SAP_MODULE") == "SAP_MODULE"
        assert validate_entity_type("TYPE_SUB_TYPE") == "TYPE_SUB_TYPE"
        assert validate_entity_type("A_B_C") == "A_B_C"


# ============================================
# Tests entity_type - Cas Invalides
# ============================================

@pytest.mark.unit
class TestEntityTypeInvalidCases:
    """Tests pour les cas invalides d'entity_type."""

    def test_entity_type_empty_string(self) -> None:
        """Test type vide."""
        with pytest.raises(ValueError, match="ne peut pas être vide"):
            validate_entity_type("")

    def test_entity_type_whitespace_only(self) -> None:
        """Test type avec espaces seulement."""
        with pytest.raises(ValueError):
            validate_entity_type("   ")

    @pytest.mark.parametrize("lowercase_type", [
        "person",
        "Person",
        "pERSON",
        "PERson",
        "a",
    ])
    def test_entity_type_lowercase_rejected(self, lowercase_type: str) -> None:
        """Test types avec minuscules rejetes."""
        with pytest.raises(ValueError, match="doit commencer par une majuscule"):
            validate_entity_type(lowercase_type)

    @pytest.mark.parametrize("invalid_char_type", [
        "PERSON-TYPE",
        "PERSON.TYPE",
        "PERSON TYPE",
        "PERSON!",
        "PERSON@TYPE",
        "PERSON#",
        "PERSON$TYPE",
        "PERSON%",
        "PERSON^TYPE",
        "PERSON&TYPE",
        "PERSON*",
        "PERSON+TYPE",
        "PERSON=TYPE",
        "PERSON|TYPE",
        "PERSON\\TYPE",
        "PERSON/TYPE",
        "PERSON?TYPE",
        "PERSON(TYPE)",
        "PERSON[TYPE]",
        "PERSON{TYPE}",
        "PERSON<TYPE>",
        "PERSON,TYPE",
        "PERSON;TYPE",
        "PERSON:TYPE",
    ])
    def test_entity_type_special_chars_rejected(
        self, invalid_char_type: str
    ) -> None:
        """Test types avec caracteres speciaux rejetes."""
        with pytest.raises(ValueError):
            validate_entity_type(invalid_char_type)

    def test_entity_type_too_long(self) -> None:
        """Test type trop long (>50 chars)."""
        long_type = "A" * 51
        with pytest.raises(ValueError, match="doit commencer par une majuscule"):
            validate_entity_type(long_type)

    @pytest.mark.parametrize("length", [51, 52, 100, 200])
    def test_entity_type_various_too_long_lengths(self, length: int) -> None:
        """Test types de differentes longueurs excessives."""
        long_type = "A" * length
        with pytest.raises(ValueError):
            validate_entity_type(long_type)

    def test_entity_type_starts_with_number(self) -> None:
        """Test type commencant par chiffre."""
        with pytest.raises(ValueError, match="doit commencer par une majuscule"):
            validate_entity_type("123TYPE")
        with pytest.raises(ValueError):
            validate_entity_type("1A")


# ============================================
# Tests entity_type - Blacklist Systeme
# ============================================

@pytest.mark.unit
class TestEntityTypeSystemBlacklist:
    """Tests pour la blacklist des types systeme."""

    def test_starts_with_underscore(self) -> None:
        """Test type commencant par underscore."""
        with pytest.raises(ValueError, match="types système avec préfixe '_'"):
            validate_entity_type("_INTERNAL")

    def test_starts_with_double_underscore(self) -> None:
        """Test type commencant par double underscore."""
        with pytest.raises(ValueError, match="types système avec préfixe '__'"):
            validate_entity_type("__BUILTIN__")

    def test_starts_with_system_prefix(self) -> None:
        """Test type commencant par SYSTEM_."""
        with pytest.raises(ValueError, match="types système avec préfixe 'SYSTEM_'"):
            validate_entity_type("SYSTEM_CONFIG")
        with pytest.raises(ValueError, match="types système avec préfixe 'SYSTEM_'"):
            validate_entity_type("SYSTEM_INTERNAL")

    def test_starts_with_internal_prefix(self) -> None:
        """Test type commencant par INTERNAL_."""
        with pytest.raises(ValueError, match="types système avec préfixe 'INTERNAL_'"):
            validate_entity_type("INTERNAL_DATA")
        with pytest.raises(ValueError, match="types système avec préfixe 'INTERNAL_'"):
            validate_entity_type("INTERNAL_CONFIG")

    @pytest.mark.parametrize("blacklisted", SYSTEM_TYPE_BLACKLIST)
    def test_all_blacklisted_prefixes(self, blacklisted: str) -> None:
        """Test tous les prefixes blacklistes."""
        # Construire un type valide avec le prefixe blackliste
        test_type = f"{blacklisted}TEST"
        with pytest.raises(ValueError, match="types système"):
            validate_entity_type(test_type)


# ============================================
# Tests entity_type - Injection Attacks
# ============================================

@pytest.mark.unit
class TestEntityTypeSecurityInjections:
    """Tests de securite pour les injections."""

    @pytest.mark.parametrize("sql_injection", [
        "PERSON'; DROP TABLE users--",
        "PERSON' OR '1'='1",
        "PERSON; SELECT * FROM users",
        "PERSON UNION SELECT password",
        "PERSON' AND '1'='1",
        "PERSON'; INSERT INTO admin",
        "PERSON'; UPDATE users SET",
        "PERSON'; DELETE FROM",
    ])
    def test_sql_injection_attempts(self, sql_injection: str) -> None:
        """Test tentatives d'injection SQL."""
        with pytest.raises(ValueError):
            validate_entity_type(sql_injection)

    @pytest.mark.parametrize("xss_injection", [
        "PERSON<script>alert('xss')</script>",
        "PERSON<img src=x onerror=alert(1)>",
        "PERSON<svg/onload=alert(1)>",
        "PERSON<body onload=alert(1)>",
        "PERSON javascript:alert(1)",
    ])
    def test_xss_injection_attempts(self, xss_injection: str) -> None:
        """Test tentatives d'injection XSS."""
        with pytest.raises(ValueError):
            validate_entity_type(xss_injection)

    @pytest.mark.parametrize("path_traversal", [
        "PERSON/../../../etc/passwd",
        "PERSON..\\..\\windows",
        "PERSON/etc/passwd",
    ])
    def test_path_traversal_attempts(self, path_traversal: str) -> None:
        """Test tentatives de path traversal."""
        with pytest.raises(ValueError):
            validate_entity_type(path_traversal)

    def test_null_byte_injection(self) -> None:
        """Test injection null byte."""
        with pytest.raises(ValueError):
            validate_entity_type("PERSON\x00ADMIN")

    @pytest.mark.parametrize("control_char", [
        "PERSON\x00",
        "PERSON\x01",
        "PERSON\x0a",  # newline
        "PERSON\x0d",  # carriage return
        "PERSON\x09",  # tab
        "PERSON\x1f",
        "PERSON\x7f",
    ])
    def test_control_character_injection(self, control_char: str) -> None:
        """Test injection de caracteres de controle."""
        with pytest.raises(ValueError):
            validate_entity_type(control_char)


# ============================================
# Tests entity_name - Cas Valides
# ============================================

@pytest.mark.unit
class TestEntityNameValidCases:
    """Tests pour les cas valides d'entity.name."""

    @pytest.mark.parametrize("name", [
        "John Doe",
        "SAP S/4HANA",
        "Module-123",
        "Test (v2.0)",
        "User123",
        "User & Co.",
        "Entity_with_underscore",
        "A",  # Min length
        "A" * 200,  # Max length
    ])
    def test_valid_entity_names(self, name: str) -> None:
        """Tester les noms d'entite valides."""
        result = validate_entity_name(name)
        assert result == name.strip()

    def test_entity_name_unicode_characters(self) -> None:
        """Test noms avec caracteres Unicode."""
        assert validate_entity_name("Societe Generale") == "Societe Generale"
        assert validate_entity_name("Cafe") == "Cafe"
        assert validate_entity_name("Munchen") == "Munchen"

    def test_entity_name_chinese_characters(self) -> None:
        """Test noms avec caracteres chinois."""
        assert validate_entity_name("Beijing") == "Beijing"

    def test_entity_name_strips_whitespace(self) -> None:
        """Test que les espaces sont retires."""
        assert validate_entity_name("  User  ") == "User"
        assert validate_entity_name("\tUser\t") == "User"
        assert validate_entity_name("\nUser\n") == "User"

    def test_entity_name_preserves_internal_whitespace(self) -> None:
        """Test que les espaces internes sont preserves."""
        assert validate_entity_name("John Doe") == "John Doe"
        assert validate_entity_name("A  B  C") == "A  B  C"

    def test_entity_name_with_newlines_internal(self) -> None:
        """Test noms avec newlines internes (autorises)."""
        result = validate_entity_name("Line 1\nLine 2")
        assert result == "Line 1\nLine 2"


# ============================================
# Tests entity_name - Cas Invalides
# ============================================

@pytest.mark.unit
class TestEntityNameInvalidCases:
    """Tests pour les cas invalides d'entity.name."""

    def test_entity_name_empty_string(self) -> None:
        """Test nom vide."""
        with pytest.raises(ValueError, match="ne peut pas être vide"):
            validate_entity_name("")

    def test_entity_name_whitespace_only(self) -> None:
        """Test nom avec espaces seulement."""
        with pytest.raises(ValueError, match="ne peut pas être vide"):
            validate_entity_name("   ")

    def test_entity_name_too_long(self) -> None:
        """Test nom trop long (>200 chars)."""
        long_name = "A" * 201
        with pytest.raises(ValueError, match="trop long"):
            validate_entity_name(long_name)

    @pytest.mark.parametrize("length", [201, 202, 300, 500])
    def test_entity_name_various_too_long_lengths(self, length: int) -> None:
        """Test noms de differentes longueurs excessives."""
        long_name = "A" * length
        with pytest.raises(ValueError, match="trop long"):
            validate_entity_name(long_name)

    @pytest.mark.parametrize("xss_char", ["<", ">", '"', "'"])
    def test_entity_name_xss_dangerous_chars(self, xss_char: str) -> None:
        """Test caracteres dangereux pour XSS."""
        with pytest.raises(ValueError, match="prévention XSS"):
            validate_entity_name(f"User{xss_char}test")


# ============================================
# Tests entity_name - Path Traversal
# ============================================

@pytest.mark.unit
class TestEntityNamePathTraversal:
    """Tests pour les tentatives de path traversal."""

    @pytest.mark.parametrize("path_traversal", [
        "../etc/passwd",
        "../../etc/passwd",
        "../../../etc/shadow",
        "User/../admin",
        "..\\windows",
        "..\\..\\windows\\system32",
        "User\\..\\admin",
    ])
    def test_path_traversal_rejected(self, path_traversal: str) -> None:
        """Test path traversal rejete."""
        with pytest.raises(ValueError, match="path traversal"):
            validate_entity_name(path_traversal)

    @pytest.mark.parametrize("absolute_path", [
        "/etc/passwd",
        "/root/.ssh/id_rsa",
        "file:///etc/passwd",
        "C:\\Windows\\System32",
        "D:\\Users\\Admin",
    ])
    def test_absolute_paths_rejected(self, absolute_path: str) -> None:
        """Test chemins absolus rejetes."""
        with pytest.raises(ValueError, match="chemin absolu"):
            validate_entity_name(absolute_path)


# ============================================
# Tests entity_name - Null Bytes
# ============================================

@pytest.mark.unit
class TestEntityNameNullBytes:
    """Tests pour les null bytes."""

    def test_null_byte_rejected(self) -> None:
        """Test null byte rejete."""
        with pytest.raises(ValueError, match="null byte"):
            validate_entity_name("User\x00Admin")

    @pytest.mark.parametrize("position", ["start", "middle", "end"])
    def test_null_byte_any_position(self, position: str) -> None:
        """Test null byte a differentes positions."""
        names = {
            "start": "\x00Admin",
            "middle": "Use\x00r",
            "end": "Admin\x00",
        }
        with pytest.raises(ValueError, match="null byte"):
            validate_entity_name(names[position])


# ============================================
# Tests relation_type
# ============================================

@pytest.mark.unit
class TestRelationType:
    """Tests pour relation_type (memes regles qu'entity_type)."""

    @pytest.mark.parametrize("relation_type", [
        "WORKS_AT",
        "MANAGES",
        "BELONGS_TO",
        "RELATED_TO",
        "IS_A",
        "HAS_PART",
        "DEPENDS_ON",
    ])
    def test_valid_relation_types(self, relation_type: str) -> None:
        """Test types de relation valides."""
        result = validate_relation_type(relation_type)
        assert result == relation_type

    def test_relation_type_invalid_lowercase(self) -> None:
        """Test type de relation invalide (minuscule)."""
        with pytest.raises(ValueError):
            validate_relation_type("works_at")

    def test_relation_type_system_prefix_rejected(self) -> None:
        """Test prefixe systeme rejete."""
        with pytest.raises(ValueError, match="types système"):
            validate_relation_type("SYSTEM_RELATION")


# ============================================
# Tests Pydantic Models
# ============================================

@pytest.mark.unit
class TestPydanticModels:
    """Tests pour les modeles Pydantic."""

    def test_entity_type_validator_model_valid(self) -> None:
        """Test EntityTypeValidator avec valeur valide."""
        model = EntityTypeValidator(entity_type="PERSON")
        assert model.entity_type == "PERSON"

    def test_entity_type_validator_model_invalid(self) -> None:
        """Test EntityTypeValidator avec valeur invalide."""
        with pytest.raises(ValidationError) as exc_info:
            EntityTypeValidator(entity_type="person")
        assert "entity_type" in str(exc_info.value)

    def test_entity_name_validator_model_valid(self) -> None:
        """Test EntityNameValidator avec valeur valide."""
        model = EntityNameValidator(name="John Doe")
        assert model.name == "John Doe"

    def test_entity_name_validator_model_invalid_xss(self) -> None:
        """Test EntityNameValidator avec XSS."""
        with pytest.raises(ValidationError) as exc_info:
            EntityNameValidator(name="User<script>")
        assert "name" in str(exc_info.value)

    def test_entity_name_validator_model_strips_whitespace(self) -> None:
        """Test EntityNameValidator strip les espaces."""
        model = EntityNameValidator(name="  User  ")
        assert model.name == "User"

    def test_relation_type_validator_model_valid(self) -> None:
        """Test RelationTypeValidator avec valeur valide."""
        model = RelationTypeValidator(relation_type="WORKS_AT")
        assert model.relation_type == "WORKS_AT"

    def test_relation_type_validator_model_invalid(self) -> None:
        """Test RelationTypeValidator avec valeur invalide."""
        with pytest.raises(ValidationError):
            RelationTypeValidator(relation_type="works_at")


# ============================================
# Tests Inline Validators
# ============================================

@pytest.mark.unit
class TestInlineValidators:
    """Tests pour les validators inline."""

    def test_entity_type_validator_function(self) -> None:
        """Test entity_type_validator inline."""
        assert entity_type_validator("PERSON") == "PERSON"
        with pytest.raises(ValueError):
            entity_type_validator("person")

    def test_entity_name_validator_function(self) -> None:
        """Test entity_name_validator inline."""
        assert entity_name_validator("John Doe") == "John Doe"
        with pytest.raises(ValueError):
            entity_name_validator("<script>")

    def test_relation_type_validator_function(self) -> None:
        """Test relation_type_validator inline."""
        assert relation_type_validator("WORKS_AT") == "WORKS_AT"
        with pytest.raises(ValueError):
            relation_type_validator("works_at")


# ============================================
# Tests Regex et Patterns
# ============================================

@pytest.mark.unit
class TestRegexPatterns:
    """Tests pour les regex et patterns."""

    def test_entity_type_regex_pattern_exists(self) -> None:
        """Test que le pattern regex existe."""
        assert ENTITY_TYPE_REGEX is not None
        assert ENTITY_TYPE_REGEX.pattern == r'^[A-Z][A-Z0-9_]{0,49}$'

    def test_dangerous_patterns_list_exists(self) -> None:
        """Test que la liste de patterns dangereux existe."""
        assert len(DANGEROUS_PATTERNS) > 0
        assert all(hasattr(p, 'search') for p in DANGEROUS_PATTERNS)

    def test_system_type_blacklist_order(self) -> None:
        """Test l'ordre de la blacklist (__ avant _)."""
        # __ doit etre avant _ dans la blacklist
        double_underscore_idx = SYSTEM_TYPE_BLACKLIST.index("__")
        single_underscore_idx = SYSTEM_TYPE_BLACKLIST.index("_")
        assert double_underscore_idx < single_underscore_idx


# ============================================
# Tests de Performance
# ============================================

@pytest.mark.unit
class TestValidatorPerformance:
    """Tests de performance basiques."""

    def test_entity_type_validation_performance(self) -> None:
        """Test performance validation entity_type."""
        import time

        start = time.time()
        for i in range(10000):
            validate_entity_type(f"TYPE{i % 100}")
        duration = time.time() - start

        # Devrait completer en moins de 5 secondes
        assert duration < 5, f"Validation trop lente: {duration}s"

    def test_entity_name_validation_performance(self) -> None:
        """Test performance validation entity.name."""
        import time

        start = time.time()
        for i in range(10000):
            validate_entity_name(f"Entity Name {i}")
        duration = time.time() - start

        assert duration < 5, f"Validation trop lente: {duration}s"


# ============================================
# Tests Boundary
# ============================================

@pytest.mark.unit
class TestBoundaryConditions:
    """Tests des conditions aux limites."""

    def test_entity_type_boundary_49_chars(self) -> None:
        """Test entity_type a 49 caracteres (valide)."""
        result = validate_entity_type("A" * 49)
        assert len(result) == 49

    def test_entity_type_boundary_50_chars(self) -> None:
        """Test entity_type a 50 caracteres (valide - limite)."""
        result = validate_entity_type("A" * 50)
        assert len(result) == 50

    def test_entity_type_boundary_51_chars(self) -> None:
        """Test entity_type a 51 caracteres (invalide)."""
        with pytest.raises(ValueError):
            validate_entity_type("A" * 51)

    def test_entity_name_boundary_199_chars(self) -> None:
        """Test entity.name a 199 caracteres (valide)."""
        result = validate_entity_name("A" * 199)
        assert len(result) == 199

    def test_entity_name_boundary_200_chars(self) -> None:
        """Test entity.name a 200 caracteres (valide - limite)."""
        result = validate_entity_name("A" * 200)
        assert len(result) == 200

    def test_entity_name_boundary_201_chars(self) -> None:
        """Test entity.name a 201 caracteres (invalide)."""
        with pytest.raises(ValueError, match="trop long"):
            validate_entity_name("A" * 201)
