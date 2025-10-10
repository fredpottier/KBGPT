"""
Validators pour Input Validation - Phase 0 Security Hardening.

Validation stricte des inputs utilisateurs pour prévenir injections et abus.
"""
import re
from typing import Optional
from pydantic import field_validator, BaseModel, Field


# Regex pour entity_type et relation_type : commence par majuscule, puis majuscules/chiffres/underscores
# Max 50 caractères
ENTITY_TYPE_REGEX = re.compile(r'^[A-Z][A-Z0-9_]{0,49}$')

# Prefixes/patterns interdits (types système)
# IMPORTANT : Ordre du plus spécifique au moins spécifique (__ avant _)
SYSTEM_TYPE_BLACKLIST = [
    "__",          # Double underscore (Python internals) - DOIT être avant _
    "SYSTEM_",     # Préfixe système
    "INTERNAL_",   # Préfixe interne
    "_",           # Commence par underscore
]

# Patterns dangereux pour injection SQL/JavaScript
DANGEROUS_PATTERNS = [
    re.compile(r"['\";].*(?:DROP|DELETE|INSERT|UPDATE|SELECT|UNION)", re.IGNORECASE),  # SQL injection
    re.compile(r"<\s*script", re.IGNORECASE),          # XSS <script>
    re.compile(r"javascript\s*:", re.IGNORECASE),      # javascript: protocol
    re.compile(r"on\w+\s*=", re.IGNORECASE),           # Event handlers (onclick=, onerror=)
    re.compile(r"\.\./|\.\.\\"),                       # Path traversal
    re.compile(r"[\x00-\x1f\x7f]"),                    # Control characters et null bytes
]


def validate_entity_type(value: str) -> str:
    """
    Valide un entity_type ou relation_type.

    Règles :
    - Format : ^[A-Z][A-Z0-9_]{0,49}$ (commence par majuscule, puis maj/chiffres/underscores)
    - Max 50 caractères
    - Pas de préfixes système (_, SYSTEM_, INTERNAL_, __)
    - Pas de patterns dangereux (SQL injection, XSS, path traversal)

    Args:
        value: Le type à valider

    Returns:
        str: Le type validé

    Raises:
        ValueError: Si le type est invalide
    """
    if not value:
        raise ValueError("entity_type ne peut pas être vide")

    # Vérifier patterns dangereux (SQL, XSS, path traversal)
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(value):
            raise ValueError(
                f"entity_type invalide '{value[:50]}...': contient un pattern dangereux (injection potentielle)"
            )

    # Vérifier blacklist système EN PREMIER (avant regex)
    # Car _ et __ ne matchent pas le regex mais doivent donner un message spécifique
    for blacklisted in SYSTEM_TYPE_BLACKLIST:
        if value.startswith(blacklisted):
            raise ValueError(
                f"entity_type invalide '{value}': les types système avec préfixe '{blacklisted}' sont interdits"
            )

    # Vérifier format regex
    if not ENTITY_TYPE_REGEX.match(value):
        raise ValueError(
            f"entity_type invalide '{value}': doit commencer par une majuscule "
            "et ne contenir que majuscules, chiffres et underscores (max 50 chars)"
        )

    return value


def validate_entity_name(value: str) -> str:
    """
    Valide un entity.name pour prévenir XSS et path traversal.

    Règles :
    - Max 200 caractères
    - Pas de caractères dangereux : <>'"
    - Pas de path traversal : ../ ou ..\\
    - Pas de null bytes ni caractères de contrôle
    - Pas de patterns SQL/XSS

    Args:
        value: Le nom à valider

    Returns:
        str: Le nom validé et nettoyé

    Raises:
        ValueError: Si le nom est invalide
    """
    if not value:
        raise ValueError("entity.name ne peut pas être vide")

    # Max length
    if len(value) > 200:
        raise ValueError(f"entity.name trop long ({len(value)} chars, max 200)")

    # Vérifier patterns dangereux (SQL, XSS, path traversal)
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(value):
            raise ValueError(
                f"entity.name invalide: contient un pattern dangereux (injection potentielle)"
            )

    # Caractères XSS dangereux (vérification redondante mais explicite)
    dangerous_chars = ['<', '>', '"', "'"]
    for char in dangerous_chars:
        if char in value:
            raise ValueError(
                f"entity.name invalide: caractère interdit '{char}' (prévention XSS)"
            )

    # Path traversal (vérification redondante mais explicite)
    if '../' in value or '..\\' in value:
        raise ValueError("entity.name invalide: path traversal détecté (../ ou ..\\)")

    # Null bytes (vérification redondante mais explicite)
    if '\x00' in value:
        raise ValueError("entity.name invalide: null byte détecté")

    return value.strip()


def validate_relation_type(value: str) -> str:
    """
    Valide un relation_type.

    Utilise les mêmes règles que entity_type.
    """
    return validate_entity_type(value)


class EntityTypeValidator(BaseModel):
    """Modèle Pydantic avec validation entity_type."""
    entity_type: str = Field(..., min_length=1, max_length=50)

    @field_validator('entity_type')
    @classmethod
    def validate_entity_type_field(cls, v: str) -> str:
        return validate_entity_type(v)


class EntityNameValidator(BaseModel):
    """Modèle Pydantic avec validation entity.name."""
    name: str = Field(..., min_length=1, max_length=200)

    @field_validator('name')
    @classmethod
    def validate_name_field(cls, v: str) -> str:
        return validate_entity_name(v)


class RelationTypeValidator(BaseModel):
    """Modèle Pydantic avec validation relation_type."""
    relation_type: str = Field(..., min_length=1, max_length=50)

    @field_validator('relation_type')
    @classmethod
    def validate_relation_type_field(cls, v: str) -> str:
        return validate_relation_type(v)


# Helpers pour validation inline dans schemas existants
def entity_type_validator(v: str) -> str:
    """Validator inline pour entity_type dans schemas Pydantic."""
    return validate_entity_type(v)


def entity_name_validator(v: str) -> str:
    """Validator inline pour entity.name dans schemas Pydantic."""
    return validate_entity_name(v)


def relation_type_validator(v: str) -> str:
    """Validator inline pour relation_type dans schemas Pydantic."""
    return validate_relation_type(v)
