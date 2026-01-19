"""
Hybrid Anchor Model - Anchor Resolution Module

Responsabilités:
1. Localiser les quotes LLM dans le texte source via fuzzy matching
2. Créer des Anchors avec positions exactes (char_start, char_end)
3. Valider les anchors selon les seuils de confiance
4. Détecter les concepts high-signal pour promotion singleton

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2024-12
"""

import logging
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from rapidfuzz import fuzz, process

from knowbase.api.schemas.concepts import (
    Anchor,
    AnchorRole,
    AnchorPayload,
    HighSignalCheck,
)
from knowbase.config.feature_flags import get_hybrid_anchor_config

logger = logging.getLogger(__name__)


class AnchorStatus(str, Enum):
    """Statut de l'ancrage d'un concept.

    SPAN: Ancrage réussi avec position textuelle précise
    FUZZY_FAILED: Quote LLM non matchée (score < seuil)
    NO_MATCH: Aucune correspondance trouvée dans le texte
    EMPTY_QUOTE: Quote vide ou texte source vide
    """
    SPAN = "SPAN"
    FUZZY_FAILED = "FUZZY_FAILED"
    NO_MATCH = "NO_MATCH"
    EMPTY_QUOTE = "EMPTY_QUOTE"


@dataclass
class AnchorResolutionResult:
    """Résultat complet de la résolution d'anchor avec diagnostics.

    Permet de tracer pourquoi un concept n'a pas été ancré,
    même en cas d'échec du fuzzy matching.
    """
    anchor: Optional[Anchor]
    anchor_status: AnchorStatus
    fuzzy_best_score: float = 0.0
    failure_reason: Optional[str] = None
    llm_quote: str = ""
    reject_threshold: float = 70.0

    @property
    def success(self) -> bool:
        """True si l'ancrage a réussi."""
        return self.anchor is not None and self.anchor_status == AnchorStatus.SPAN


@dataclass
class FuzzyMatchResult:
    """Résultat d'un fuzzy match."""

    score: float
    start: int
    end: int
    matched_text: str
    approximate: bool


def create_anchor_with_fuzzy_match(
    concept_id: str,
    chunk_id: str,
    llm_quote: str,
    source_text: str,
    role: str = "context",
    section_id: Optional[str] = None,
    tenant_id: str = "default"
) -> Optional[Anchor]:
    """
    Crée un Anchor en localisant la quote LLM dans le texte source.

    Utilise rapidfuzz pour trouver la meilleure correspondance et
    extraire les positions exactes (char_start, char_end).

    Args:
        concept_id: ID du concept (proto ou canonical)
        chunk_id: ID du chunk contenant le texte
        llm_quote: Quote fournie par le LLM
        source_text: Texte source où chercher la quote
        role: Rôle sémantique de l'anchor
        section_id: ID de la section (optionnel)
        tenant_id: ID tenant pour configuration

    Returns:
        Anchor si trouvé avec confiance suffisante, None sinon
    """
    if not llm_quote or not source_text:
        logger.warning(
            f"[OSMOSE:ANCHOR_RESOLUTION] Empty quote or source for concept {concept_id}"
        )
        return None

    # Charger configuration
    anchor_config = get_hybrid_anchor_config("anchor_config", tenant_id) or {}
    min_fuzzy_score = anchor_config.get("min_fuzzy_score", 85)
    min_approximate_score = anchor_config.get("min_approximate_score", 70)
    reject_below_score = anchor_config.get("reject_below_score", 70)

    # Fuzzy match
    match_result = _find_best_match(llm_quote, source_text)

    if match_result is None:
        logger.debug(
            f"[OSMOSE:ANCHOR_RESOLUTION] No match found for concept {concept_id}"
        )
        return None

    # Vérifier seuils
    if match_result.score < reject_below_score:
        logger.debug(
            f"[OSMOSE:ANCHOR_RESOLUTION] Match score {match_result.score:.1f} "
            f"below threshold {reject_below_score} for concept {concept_id}"
        )
        return None

    # Déterminer si approximate
    approximate = match_result.score < min_fuzzy_score

    # Convertir role string en enum
    try:
        anchor_role = AnchorRole(role.lower())
    except ValueError:
        anchor_role = AnchorRole.CONTEXT

    # Créer l'anchor
    anchor = Anchor(
        concept_id=concept_id,
        chunk_id=chunk_id,
        surface_form=match_result.matched_text,
        role=anchor_role,
        confidence=match_result.score / 100.0,
        span_start=match_result.start,
        span_end=match_result.end,
        approximate=approximate,
        section_id=section_id
    )

    log_level = "DEBUG" if approximate else "INFO"
    logger.log(
        logging.DEBUG if approximate else logging.INFO,
        f"[OSMOSE:ANCHOR_RESOLUTION] Created anchor for {concept_id}: "
        f"score={match_result.score:.1f}%, approximate={approximate}"
    )

    return anchor


def resolve_anchor_with_diagnostics(
    concept_id: str,
    chunk_id: str,
    llm_quote: str,
    source_text: str,
    role: str = "context",
    section_id: Optional[str] = None,
    tenant_id: str = "default"
) -> AnchorResolutionResult:
    """
    Résout un anchor avec diagnostics complets.

    Contrairement à create_anchor_with_fuzzy_match qui retourne None en cas
    d'échec, cette fonction retourne toujours un AnchorResolutionResult
    avec les informations de diagnostic (score, raison d'échec).

    Utilisé pour classifier les concepts en SPAN vs FUZZY_FAILED.

    Args:
        concept_id: ID du concept
        chunk_id: ID du chunk contenant le texte
        llm_quote: Quote fournie par le LLM
        source_text: Texte source où chercher la quote
        role: Rôle sémantique de l'anchor
        section_id: ID de la section (optionnel)
        tenant_id: ID tenant pour configuration

    Returns:
        AnchorResolutionResult avec anchor (si succès) et diagnostics
    """
    # Cas 1: Quote ou source vide
    if not llm_quote or not source_text:
        logger.debug(
            f"[OSMOSE:ANCHOR_DIAG] Empty quote or source for concept {concept_id}"
        )
        return AnchorResolutionResult(
            anchor=None,
            anchor_status=AnchorStatus.EMPTY_QUOTE,
            fuzzy_best_score=0.0,
            failure_reason="empty_quote" if not llm_quote else "empty_source",
            llm_quote=llm_quote or ""
        )

    # Charger configuration
    anchor_config = get_hybrid_anchor_config("anchor_config", tenant_id) or {}
    min_fuzzy_score = anchor_config.get("min_fuzzy_score", 85)
    reject_below_score = anchor_config.get("reject_below_score", 70)

    # Fuzzy match
    match_result = _find_best_match(llm_quote, source_text)

    # Cas 2: Aucun match trouvé
    if match_result is None:
        logger.debug(
            f"[OSMOSE:ANCHOR_DIAG] No match found for concept {concept_id}, "
            f"quote='{llm_quote[:50]}...'"
        )
        return AnchorResolutionResult(
            anchor=None,
            anchor_status=AnchorStatus.NO_MATCH,
            fuzzy_best_score=0.0,
            failure_reason="no_match_found",
            llm_quote=llm_quote,
            reject_threshold=reject_below_score
        )

    # Cas 3: Score insuffisant (FUZZY_FAILED)
    if match_result.score < reject_below_score:
        logger.debug(
            f"[OSMOSE:ANCHOR_DIAG] FUZZY_FAILED for concept {concept_id}: "
            f"score={match_result.score:.1f}% < threshold={reject_below_score}%"
        )
        return AnchorResolutionResult(
            anchor=None,
            anchor_status=AnchorStatus.FUZZY_FAILED,
            fuzzy_best_score=match_result.score,
            failure_reason=f"score_below_{int(reject_below_score)}",
            llm_quote=llm_quote,
            reject_threshold=reject_below_score
        )

    # Cas 4: Succès - créer l'anchor
    approximate = match_result.score < min_fuzzy_score

    try:
        anchor_role = AnchorRole(role.lower())
    except ValueError:
        anchor_role = AnchorRole.CONTEXT

    anchor = Anchor(
        concept_id=concept_id,
        chunk_id=chunk_id,
        surface_form=match_result.matched_text,
        role=anchor_role,
        confidence=match_result.score / 100.0,
        span_start=match_result.start,
        span_end=match_result.end,
        approximate=approximate,
        section_id=section_id
    )

    logger.debug(
        f"[OSMOSE:ANCHOR_DIAG] SPAN success for {concept_id}: "
        f"score={match_result.score:.1f}%, approximate={approximate}"
    )

    return AnchorResolutionResult(
        anchor=anchor,
        anchor_status=AnchorStatus.SPAN,
        fuzzy_best_score=match_result.score,
        failure_reason=None,
        llm_quote=llm_quote,
        reject_threshold=reject_below_score
    )


def _find_best_match(
    query: str,
    source_text: str,
    min_length: int = 10
) -> Optional[FuzzyMatchResult]:
    """
    Trouve la meilleure correspondance de la query dans le texte source.

    Utilise une approche sliding window pour trouver le meilleur match
    et ses positions exactes.

    Args:
        query: Texte à rechercher
        source_text: Texte source
        min_length: Longueur minimale pour considérer un match

    Returns:
        FuzzyMatchResult ou None
    """
    if len(query) < min_length:
        # Query trop courte, essayer match exact
        idx = source_text.find(query)
        if idx >= 0:
            return FuzzyMatchResult(
                score=100.0,
                start=idx,
                end=idx + len(query),
                matched_text=query,
                approximate=False
            )
        return None

    # Approche 1: Essayer match exact d'abord
    idx = source_text.find(query)
    if idx >= 0:
        return FuzzyMatchResult(
            score=100.0,
            start=idx,
            end=idx + len(query),
            matched_text=query,
            approximate=False
        )

    # Approche 2: Sliding window avec ratio partiel
    query_len = len(query)
    best_score = 0.0
    best_start = 0
    best_end = 0
    best_text = ""

    # Window sizes: query_len +/- 20%
    min_window = max(min_length, int(query_len * 0.8))
    max_window = min(len(source_text), int(query_len * 1.2))

    for window_size in range(min_window, max_window + 1, max(1, (max_window - min_window) // 10)):
        for start in range(0, len(source_text) - window_size + 1, max(1, window_size // 4)):
            end = start + window_size
            window_text = source_text[start:end]

            score = fuzz.ratio(query, window_text)

            if score > best_score:
                best_score = score
                best_start = start
                best_end = end
                best_text = window_text

    if best_score > 0:
        return FuzzyMatchResult(
            score=best_score,
            start=best_start,
            end=best_end,
            matched_text=best_text,
            approximate=best_score < 85
        )

    return None


def create_anchor_payload(anchor: Anchor, label: str) -> AnchorPayload:
    """
    Crée le payload minimal pour Qdrant à partir d'un Anchor.

    Respecte l'Invariant d'Architecture: seuls les champs autorisés.

    Args:
        anchor: Anchor source
        label: Label du concept pour affichage

    Returns:
        AnchorPayload pour Qdrant
    """
    return AnchorPayload(
        concept_id=anchor.concept_id,
        concept_name=label,
        role=anchor.role.value,
        span=[anchor.span_start, anchor.span_end]
    )


def validate_anchor_payload(payload: Dict[str, Any]) -> bool:
    """
    Valide qu'un payload anchor respecte les champs autorisés.

    Invariant d'Architecture: rejette tout champ non autorisé.

    Args:
        payload: Dictionnaire payload à valider

    Returns:
        True si valide

    Raises:
        ValueError: Si champ interdit détecté
    """
    allowed_fields = {"concept_id", "label", "role", "span", "chunk_id"}
    forbidden_fields = {
        "definition", "synthetic_text", "full_context",
        "embedding", "relations", "metadata"
    }

    for key in payload.keys():
        if key in forbidden_fields:
            raise ValueError(
                f"[OSMOSE:ANCHOR_PAYLOAD] Champ interdit dans anchor payload: {key}. "
                f"Seuls autorisés: {allowed_fields}"
            )
        if key not in allowed_fields:
            logger.warning(
                f"[OSMOSE:ANCHOR_PAYLOAD] Champ non reconnu: {key}. "
                f"Autorisés: {allowed_fields}"
            )

    return True


def check_high_signal(
    quote: str,
    anchor_role: str,
    section_type: Optional[str] = None,
    domain: Optional[str] = None,
    tenant_id: str = "default"
) -> HighSignalCheck:
    """
    Vérifie si un concept singleton est high-signal.

    Utilisé pour la voie d'exception dans la promotion CanonicalConcept.
    Un singleton high-signal peut être promu même s'il n'apparaît qu'une fois.

    Args:
        quote: Quote textuelle de l'anchor
        anchor_role: Rôle de l'anchor
        section_type: Type de section du document
        domain: Domaine du concept
        tenant_id: ID tenant pour configuration

    Returns:
        HighSignalCheck avec détails du statut
    """
    promotion_config = get_hybrid_anchor_config("promotion_config", tenant_id) or {}

    high_signal_roles = set(promotion_config.get("high_signal_roles", [
        "requirement", "prohibition", "definition", "constraint", "obligation"
    ]))
    high_signal_modals = promotion_config.get("high_signal_modals", [
        "shall", "must", "required", "prohibited", "mandatory"
    ])
    high_signal_sections = set(promotion_config.get("high_signal_sections", [
        "requirements", "security", "compliance", "sla", "constraints"
    ]))
    high_signal_domains = set(promotion_config.get("high_signal_domains", [
        "gdpr", "security", "disaster_recovery", "sla", "compliance", "legal"
    ]))

    result = HighSignalCheck(is_high_signal=False, reasons=[])
    quote_lower = quote.lower()

    # Check 1: Rôle anchor normatif
    if anchor_role.lower() in high_signal_roles:
        result.anchor_role_match = True
        result.reasons.append(f"Anchor role '{anchor_role}' is high-signal")

    # Check 2: Modaux normatifs dans la quote
    for modal in high_signal_modals:
        if modal in quote_lower:
            result.modal_match = True
            result.reasons.append(f"Modal '{modal}' found in quote")
            break

    # Check 3: Section type critique
    if section_type and section_type.lower() in high_signal_sections:
        result.section_match = True
        result.reasons.append(f"Section type '{section_type}' is high-signal")

    # Check 4: Domaine high-value
    if domain and domain.lower() in high_signal_domains:
        result.domain_match = True
        result.reasons.append(f"Domain '{domain}' is high-signal")

    # High-signal si au moins un critère match
    result.is_high_signal = (
        result.anchor_role_match or
        result.modal_match or
        result.section_match or
        result.domain_match
    )

    if result.is_high_signal:
        logger.info(
            f"[OSMOSE:HIGH_SIGNAL] Concept detected as high-signal: {result.reasons}"
        )

    return result


def batch_resolve_anchors(
    concepts_with_quotes: List[Dict[str, Any]],
    source_text: str,
    chunk_id: str,
    section_id: Optional[str] = None,
    tenant_id: str = "default"
) -> Tuple[List[Anchor], List[Dict[str, Any]]]:
    """
    Résout les anchors pour un batch de concepts.

    Args:
        concepts_with_quotes: Liste de dicts avec 'concept_id', 'quote', 'role'
        source_text: Texte source du segment
        chunk_id: ID du chunk
        section_id: ID de la section
        tenant_id: ID tenant

    Returns:
        Tuple (anchors valides, concepts rejetés)
    """
    valid_anchors = []
    rejected_concepts = []

    for concept_data in concepts_with_quotes:
        concept_id = concept_data.get("concept_id", "unknown")
        quote = concept_data.get("quote", "")
        role = concept_data.get("role", "context")

        anchor = create_anchor_with_fuzzy_match(
            concept_id=concept_id,
            chunk_id=chunk_id,
            llm_quote=quote,
            source_text=source_text,
            role=role,
            section_id=section_id,
            tenant_id=tenant_id
        )

        if anchor:
            valid_anchors.append(anchor)
        else:
            rejected_concepts.append({
                **concept_data,
                "rejection_reason": "Anchor not found or below threshold"
            })

    logger.info(
        f"[OSMOSE:ANCHOR_RESOLUTION] Batch result: "
        f"{len(valid_anchors)} valid, {len(rejected_concepts)} rejected"
    )

    return valid_anchors, rejected_concepts
