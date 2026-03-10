# src/knowbase/claimfirst/extractors/qs_llm_extractor.py
"""
QS LLM Extractor — Étapes 1 et 2 du pipeline cross-doc.

Étape 1 : Comparability Gate LLM (classification binaire)
Étape 2 : Extraction structurée (question + value + scope evidence)

Pattern LLM identique à entity_canonicalizer.py :
- Lazy import de llm_router
- asyncio.gather + Semaphore pour batch
- Politique ABSTAIN = drop (mode précision)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from knowbase.claimfirst.models.qs_candidate import QSCandidate
from knowbase.claimfirst.models.question_dimension import VALID_OPERATORS, VALID_VALUE_TYPES

if TYPE_CHECKING:
    from knowbase.claimfirst.models.document_context import DocumentContext

logger = logging.getLogger("[OSMOSE] qs_llm_extractor")


# ── Prompts ────────────────────────────────────────────────────────────

GATE_SYSTEM_PROMPT = """You are a comparability classifier. Given a factual claim from a document,
determine whether it answers an IMPLICIT FACTUAL QUESTION that could
meaningfully appear in OTHER INDEPENDENT documents.

A COMPARABLE_FACT is a claim that:
- States a specific value, constraint, requirement, policy, or capability
- Could be asked as a stable factual question (e.g., "What is X?", "Is X required?")
- Another document about a related subject could answer the SAME question differently

A NON_COMPARABLE_FACT is a claim that:
- Is purely procedural ("To configure X, do Y")
- Is an example or illustration
- Is too context-specific to appear in another document
- Describes a workflow step, not an assertion

Respond in JSON with exactly one field:
{"label": "COMPARABLE_FACT"} or {"label": "NON_COMPARABLE_FACT"} or {"label": "ABSTAIN"}"""


EXTRACTION_SYSTEM_PROMPT = """You are a factual question extractor. Given a claim from a document,
extract the implicit factual question it answers.

RULES:
1. The question must be ANSWERABLE by the claim text alone
2. The dimension_key must be snake_case, max 5 words, domain-agnostic
3. Extract the value AS STATED in the claim (raw), then normalize if possible
4. For scope: extract ONLY what the claim explicitly states or implies
   about WHICH product/subject/context this applies to
5. If you cannot extract a stable question, set abstain_reason

value_type must be one of: number, version, boolean, percent, enum, string
operator must be one of: =, >=, <=, >, <, approx, in

Respond in JSON:
{
  "candidate_question": "...",
  "candidate_dimension_key": "...",
  "value_type": "...",
  "value_raw": "...",
  "value_normalized": "...",
  "operator": "=",
  "scope_evidence": "...",
  "scope_basis": "claim_explicit",
  "confidence": 0.9,
  "abstain_reason": null
}"""


# ── Étape 1 : LLM Comparability Gate ──────────────────────────────────

async def llm_comparability_gate(
    claims: list,
    tenant_id: str = "default",
    max_concurrent: int = 5,
) -> List[Tuple[str, str]]:
    """
    Classification binaire LLM : COMPARABLE_FACT / NON_COMPARABLE_FACT / ABSTAIN.

    Args:
        claims: Liste de Claim objects (avec .claim_id, .text, .structured_form)
        tenant_id: Tenant
        max_concurrent: Parallélisme max

    Returns:
        Liste de (claim_id, label) pour chaque claim
    """
    from knowbase.common.llm_router import get_llm_router, TaskType

    router = get_llm_router()
    semaphore = asyncio.Semaphore(max_concurrent)
    results: List[Tuple[str, str]] = []
    lock = asyncio.Lock()

    async def classify_one(claim) -> None:
        claim_id = getattr(claim, "claim_id", "unknown")
        text = getattr(claim, "text", "")

        # Extraire noms d'entités si disponibles
        entity_names = _extract_entity_names(claim)

        user_content = f'Claim: "{text}"\nEntities mentioned: {entity_names}'

        async with semaphore:
            try:
                response = await router.acomplete(
                    task_type=TaskType.METADATA_EXTRACTION,
                    messages=[
                        {"role": "system", "content": GATE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.1,
                    max_tokens=50,
                    response_format={"type": "json_object"},
                )
                label = _parse_gate_response(response)
            except Exception as e:
                logger.warning("LLM gate error for %s: %s", claim_id, e)
                label = "ABSTAIN"

        async with lock:
            results.append((claim_id, label))

    await asyncio.gather(*[classify_one(c) for c in claims])
    return results


def _parse_gate_response(response) -> str:
    """Parse la réponse LLM du gate."""
    try:
        text = response if isinstance(response, str) else getattr(response, "text", str(response))
        data = json.loads(text)
        label = data.get("label", "ABSTAIN").upper().strip()
        if label in ("COMPARABLE_FACT", "NON_COMPARABLE_FACT", "ABSTAIN"):
            return label
        return "ABSTAIN"
    except (json.JSONDecodeError, AttributeError):
        return "ABSTAIN"


# ── Étape 2 : LLM Extraction structurée ───────────────────────────────

async def llm_extract_qs(
    claims: list,
    doc_contexts: Optional[Dict[str, object]] = None,
    tenant_id: str = "default",
    max_concurrent: int = 5,
    gating_info: Optional[Dict[str, Tuple[str, List[str]]]] = None,
) -> List[QSCandidate]:
    """
    Extraction structurée LLM : question + value + scope evidence.

    Args:
        claims: Liste de Claim objects
        doc_contexts: {doc_id: DocumentContext} pour le primary_subject
        tenant_id: Tenant
        max_concurrent: Parallélisme max
        gating_info: {claim_id: (gate_label, gating_signals)} pour traçabilité

    Returns:
        Liste de QSCandidate valides (invalides droppés)
    """
    from knowbase.common.llm_router import get_llm_router, TaskType

    router = get_llm_router()
    semaphore = asyncio.Semaphore(max_concurrent)
    doc_contexts = doc_contexts or {}
    gating_info = gating_info or {}
    results: List[QSCandidate] = []
    lock = asyncio.Lock()

    async def extract_one(claim) -> None:
        claim_id = getattr(claim, "claim_id", "unknown")
        doc_id = getattr(claim, "doc_id", "unknown")
        text = getattr(claim, "text", "")

        entity_names = _extract_entity_names(claim)
        doc_ctx = doc_contexts.get(doc_id)
        primary_subject = getattr(doc_ctx, "primary_subject", "") if doc_ctx else ""

        user_content = (
            f'Claim: "{text}"\n'
            f'Entities: {entity_names}\n'
            f'Document subject: "{primary_subject}"'
        )

        async with semaphore:
            try:
                response = await router.acomplete(
                    task_type=TaskType.KNOWLEDGE_EXTRACTION,
                    messages=[
                        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.1,
                    max_tokens=500,
                    response_format={"type": "json_object"},
                )
                candidate = _parse_extraction_response(response, claim_id, doc_id, gating_info)
            except Exception as e:
                logger.warning("LLM extraction error for %s: %s", claim_id, e)
                candidate = None

        if candidate and candidate.is_valid():
            async with lock:
                results.append(candidate)

    await asyncio.gather(*[extract_one(c) for c in claims])
    return results


def _parse_extraction_response(
    response,
    claim_id: str,
    doc_id: str,
    gating_info: Dict[str, Tuple[str, List[str]]],
) -> Optional[QSCandidate]:
    """Parse la réponse LLM d'extraction."""
    try:
        text = response if isinstance(response, str) else getattr(response, "text", str(response))
        data = json.loads(text)
    except (json.JSONDecodeError, AttributeError):
        return None

    # Vérifier champs obligatoires
    question = data.get("candidate_question")
    dim_key = data.get("candidate_dimension_key")
    value_type = data.get("value_type")
    value_raw = data.get("value_raw")

    if not all([question, dim_key, value_type, value_raw]):
        return None

    # Validation listes fermées
    if value_type not in VALID_VALUE_TYPES:
        return QSCandidate(
            claim_id=claim_id, doc_id=doc_id,
            candidate_question=question or "",
            candidate_dimension_key=dim_key or "",
            value_type=value_type or "string",
            value_raw=value_raw or "",
            abstain_reason="invalid_value_type",
        )

    operator = data.get("operator", "=")
    if operator not in VALID_OPERATORS:
        return QSCandidate(
            claim_id=claim_id, doc_id=doc_id,
            candidate_question=question,
            candidate_dimension_key=dim_key,
            value_type=value_type,
            value_raw=value_raw,
            operator=operator,
            abstain_reason="invalid_operator",
        )

    gate_label, gating_signals = gating_info.get(claim_id, ("", []))

    # Coercer value_raw et value_normalized en str (le LLM peut retourner bool/int)
    value_raw_str = str(value_raw) if value_raw is not None else ""
    val_norm = data.get("value_normalized")
    value_normalized_str = str(val_norm) if val_norm is not None else None

    return QSCandidate(
        claim_id=claim_id,
        doc_id=doc_id,
        candidate_question=question,
        candidate_dimension_key=dim_key,
        value_type=value_type,
        value_raw=value_raw_str,
        value_normalized=value_normalized_str,
        operator=operator,
        scope_evidence=data.get("scope_evidence"),
        scope_basis=data.get("scope_basis", "claim_explicit"),
        confidence=data.get("confidence", 0.0),
        abstain_reason=data.get("abstain_reason"),
        gate_label=gate_label,
        gating_signals=list(gating_signals),
    )


def _extract_entity_names(claim) -> List[str]:
    """Extrait les noms d'entités depuis structured_form."""
    sf = getattr(claim, "structured_form", None)
    if not sf or not isinstance(sf, dict):
        return []
    entities = sf.get("entities", [])
    if isinstance(entities, list):
        return [e.get("name", "") if isinstance(e, dict) else str(e) for e in entities]
    return []


__all__ = [
    "llm_comparability_gate",
    "llm_extract_qs",
    "GATE_SYSTEM_PROMPT",
    "EXTRACTION_SYSTEM_PROMPT",
    "_parse_gate_response",
    "_parse_extraction_response",
]
