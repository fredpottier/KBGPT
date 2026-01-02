"""
OSMOSE Pass 2 - Conflict Verifier (Verify-to-Persist Pattern)

Validation 2-phases pour le prédicat conflicts_with.

Le self-audit LLM (has_conflict_cue) est structurellement biaisé car
le même modèle qui extrait justifie son choix a posteriori.

Cette approche découple extraction et validation:
1. Phase 1: Extraction normale (conflicts_with marqué "provisional")
2. Phase 2: Appel LLM séparé, ultra-court, binaire

Seules les relations confirmées par le vérificateur sont persistées.

Basé sur recommandations ChatGPT (2025-01).

Author: OSMOSE Phase 2
Date: 2025-01
"""

import logging
from typing import Optional

from knowbase.common.llm_router import get_llm_router, TaskType

logger = logging.getLogger(__name__)


# =============================================================================
# Verification Prompt (Ultra-concis, binaire)
# =============================================================================

CONFLICT_VERIFY_PROMPT = """You are validating a candidate semantic relation.

Question:
Does the following quote explicitly state a HARD INCOMPATIBILITY
where A and B cannot logically or technically coexist?

A hard incompatibility means:
- A and B cannot be simultaneously true, applied, enabled, or implemented
- Choosing A necessarily excludes B
- The conflict would still exist even if tone and sentiment were removed

NOT a conflict (reject these):
- Threat targeting something (should use 'prevents' or 'mitigates')
- Loss, weakness, limitation, difficulty (should use 'causes')
- Comparison, frequency difference, ranking (no relation needed)
- Negative outcome or tension (should use 'causes' or 'prevents')
- One thing affecting another negatively (causation, not conflict)

Subject: {subject_label}
Object: {object_label}
Quote: "{quote}"

Answer with ONLY one word:
YES_INCOMPATIBLE or NO_NOT_INCOMPATIBLE"""


# =============================================================================
# Verifier Function
# =============================================================================

async def verify_conflict(
    subject_label: str,
    object_label: str,
    quote: str,
    llm_router=None
) -> bool:
    """
    Vérifie si une relation conflicts_with est une vraie incompatibilité.

    2ème appel LLM séparé, ultra-court, pour valider le prédicat.

    Args:
        subject_label: Label du concept sujet
        object_label: Label du concept objet
        quote: Citation extraite du texte
        llm_router: LLM Router (optionnel, utilise singleton sinon)

    Returns:
        True si l'incompatibilité est confirmée, False sinon
    """
    if llm_router is None:
        llm_router = get_llm_router()

    # Construire le prompt
    prompt = CONFLICT_VERIFY_PROMPT.format(
        subject_label=subject_label,
        object_label=object_label,
        quote=quote
    )

    try:
        response = await llm_router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,  # Déterministe
            max_tokens=20     # Réponse ultra-courte
        )

        if not response:
            logger.warning("[OSMOSE:ConflictVerifier] Empty response from LLM")
            return False

        # Parser la réponse
        response_upper = response.strip().upper()
        is_valid = "YES_INCOMPATIBLE" in response_upper

        logger.debug(
            f"[OSMOSE:ConflictVerifier] {subject_label} <-> {object_label}: "
            f"{'VERIFIED' if is_valid else 'REJECTED'} (response: {response.strip()})"
        )

        return is_valid

    except Exception as e:
        logger.error(f"[OSMOSE:ConflictVerifier] LLM call failed: {e}")
        # En cas d'erreur, rejeter par précaution
        return False


async def verify_conflicts_batch(
    candidates: list,
    llm_router=None
) -> list:
    """
    Vérifie un batch de candidats conflicts_with.

    Args:
        candidates: Liste de dicts avec {subject_label, object_label, quote, ...}
        llm_router: LLM Router

    Returns:
        Liste des candidats vérifiés (ceux qui ont passé)
    """
    if llm_router is None:
        llm_router = get_llm_router()

    verified = []
    rejected_count = 0

    for candidate in candidates:
        is_valid = await verify_conflict(
            subject_label=candidate.get("subject_label", "Unknown"),
            object_label=candidate.get("object_label", "Unknown"),
            quote=candidate.get("quote", ""),
            llm_router=llm_router
        )

        if is_valid:
            verified.append(candidate)
        else:
            rejected_count += 1

    logger.info(
        f"[OSMOSE:ConflictVerifier] Batch result: "
        f"{len(verified)} verified, {rejected_count} rejected"
    )

    return verified
