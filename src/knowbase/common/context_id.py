"""
OSMOSE - Context ID Helper

Helper unique pour générer des context_id cohérents entre Neo4j et Qdrant.
ADR: doc/ongoing/ADR_GRAPH_FIRST_ARCHITECTURE.md

IMPORTANT: Cette fonction DOIT être utilisée partout où un context_id est généré :
- NavigationLayerBuilder (Neo4j)
- HybridAnchorChunker (Qdrant)
- Tout autre code manipulant des context_id

Author: Claude Code
Date: 2026-01-06
"""

import hashlib
from typing import Optional


def make_context_id(document_id: str, section_path: Optional[str] = None) -> str:
    """
    Génère un context_id unique et cohérent.

    Format canonique:
    - Document: "doc:{document_id}"
    - Section: "sec:{document_id}:{hash12}"

    Args:
        document_id: ID du document (ex: "Joule_L0_f8e565db")
        section_path: Chemin de section (ex: "1.2 Security Architecture")
                     Si None, génère un context_id de type document

    Returns:
        context_id au format canonique

    Examples:
        >>> make_context_id("doc123")
        'doc:doc123'
        >>> make_context_id("doc123", "1.2 Security")
        'sec:doc123:a1b2c3d4e5f6'
    """
    if section_path is None:
        # Document-level context
        return f"doc:{document_id}"

    # Section-level context
    # Normalisation pour cohérence : strip seulement (garder casing pour unicité)
    normalized_path = section_path.strip()

    # Hash court (12 chars) pour unicité
    hash_input = f"{document_id}:{normalized_path}"
    section_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]

    return f"sec:{document_id}:{section_hash}"


def make_section_hash(document_id: str, section_path: str) -> str:
    """
    Génère uniquement le hash de section (pour compatibilité).

    Args:
        document_id: ID du document
        section_path: Chemin de section

    Returns:
        Hash de 12 caractères
    """
    normalized_path = section_path.strip()
    hash_input = f"{document_id}:{normalized_path}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:12]


def parse_context_id(context_id: str) -> dict:
    """
    Parse un context_id pour extraire ses composants.

    Args:
        context_id: Context ID au format canonique

    Returns:
        Dict avec 'kind', 'document_id', et optionnellement 'section_hash'

    Examples:
        >>> parse_context_id("doc:doc123")
        {'kind': 'document', 'document_id': 'doc123'}
        >>> parse_context_id("sec:doc123:a1b2c3d4e5f6")
        {'kind': 'section', 'document_id': 'doc123', 'section_hash': 'a1b2c3d4e5f6'}
    """
    parts = context_id.split(":")

    if parts[0] == "doc" and len(parts) >= 2:
        return {
            "kind": "document",
            "document_id": ":".join(parts[1:])  # Handle doc_id with colons
        }
    elif parts[0] == "sec" and len(parts) >= 3:
        return {
            "kind": "section",
            "document_id": parts[1],
            "section_hash": parts[2]
        }
    elif parts[0] == "win" and len(parts) >= 2:
        return {
            "kind": "window",
            "chunk_id": ":".join(parts[1:])
        }
    else:
        return {
            "kind": "unknown",
            "raw": context_id
        }


__all__ = ["make_context_id", "make_section_hash", "parse_context_id"]
