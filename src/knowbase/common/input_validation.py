"""
Input Validation - Phase 0.5 P2.15

Validation taille inputs pour prévenir:
- Payload bombs (JSON énormes)
- Déni de service (arrays infinies)
- OOM (strings/lists trop grandes)

Usage:
    from knowbase.common.input_validation import (
        validate_payload_size,
        validate_string_length,
        validate_array_length
    )

    # Validation payload
    @router.post("/endpoint")
    async def endpoint(request: Request):
        await validate_payload_size(request)  # Lance 413 si trop grand
        ...

    # Validation string
    validate_string_length(text, max_length=10000)

    # Validation array
    validate_array_length(items, max_length=1000)
"""

import logging
from typing import List, Any
from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)

# Limites par défaut (configurables)
MAX_PAYLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_STRING_LENGTH = 100_000  # 100K caractères
MAX_ARRAY_LENGTH = 10_000    # 10K éléments
MAX_CANDIDATES_COUNT = 100   # Max candidates pour merge


async def validate_payload_size(
    request: Request,
    max_size: int = MAX_PAYLOAD_SIZE
) -> int:
    """
    Valider taille payload HTTP

    Args:
        request: FastAPI Request
        max_size: Taille max en bytes (défaut 10MB)

    Returns:
        Taille payload en bytes

    Raises:
        HTTPException 413 si payload trop grand
    """
    content_length = request.headers.get("content-length")

    if not content_length:
        # Pas de Content-Length, lire body avec limite
        body = await request.body()
        size = len(body)
    else:
        size = int(content_length)

    if size > max_size:
        logger.warning(
            f"⚠️ Payload trop grand: {size} bytes (max {max_size})"
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Payload too large: {size} bytes (max {max_size} bytes)"
        )

    logger.debug(f"✅ Payload validé: {size} bytes")
    return size


def validate_string_length(
    text: str,
    max_length: int = MAX_STRING_LENGTH,
    field_name: str = "string"
) -> int:
    """
    Valider longueur string

    Args:
        text: String à valider
        max_length: Longueur max (défaut 100K)
        field_name: Nom champ pour message erreur

    Returns:
        Longueur string

    Raises:
        HTTPException 400 si string trop longue
    """
    length = len(text)

    if length > max_length:
        logger.warning(
            f"⚠️ String '{field_name}' trop longue: {length} chars (max {max_length})"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} too long: {length} characters (max {max_length})"
        )

    return length


def validate_array_length(
    items: List[Any],
    max_length: int = MAX_ARRAY_LENGTH,
    field_name: str = "array"
) -> int:
    """
    Valider longueur array

    Args:
        items: Liste à valider
        max_length: Longueur max (défaut 10K)
        field_name: Nom champ pour message erreur

    Returns:
        Longueur array

    Raises:
        HTTPException 400 si array trop grande
    """
    length = len(items)

    if length > max_length:
        logger.warning(
            f"⚠️ Array '{field_name}' trop grande: {length} items (max {max_length})"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} too large: {length} items (max {max_length})"
        )

    return length


def validate_candidates(candidates: List[str]) -> int:
    """
    Valider liste candidates pour merge

    Args:
        candidates: Liste candidate IDs

    Returns:
        Nombre candidates

    Raises:
        HTTPException 400 si trop de candidates
    """
    return validate_array_length(
        candidates,
        max_length=MAX_CANDIDATES_COUNT,
        field_name="candidates"
    )


def validate_text_input(text: str, max_length: int = 50_000) -> int:
    """
    Valider input texte utilisateur (questions, etc.)

    Args:
        text: Texte utilisateur
        max_length: Longueur max (défaut 50K)

    Returns:
        Longueur texte

    Raises:
        HTTPException 400 si texte trop long
    """
    return validate_string_length(
        text,
        max_length=max_length,
        field_name="text"
    )


def validate_batch_size(
    items: List[Any],
    max_size: int = 1000
) -> int:
    """
    Valider taille batch pour traitement

    Args:
        items: Items à traiter
        max_size: Taille max batch (défaut 1000)

    Returns:
        Taille batch

    Raises:
        HTTPException 400 si batch trop grand
    """
    return validate_array_length(
        items,
        max_length=max_size,
        field_name="batch"
    )
