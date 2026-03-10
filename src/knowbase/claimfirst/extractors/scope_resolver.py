# src/knowbase/claimfirst/extractors/scope_resolver.py
"""
Scope Resolver — Cascade pour résoudre le scope de comparabilité.

V1 (synchrone) — 5 niveaux :
1. claim_explicit (conf 0.95) — scope_evidence de l'extracteur LLM
2. claim_entities (conf 0.85) — Entity ABOUT → entity_type mapping
3. section_context (conf 0.70) — Passage.section_title
4. document_context (conf 0.60) — DocumentContext.primary_subject
5. ambiguous — scope_status="ambiguous", non comparable

V2 (async) — 6 niveaux :
1. claim_explicit (conf 0.95)
2. claim_llm (conf 0.88) — LLM scope extraction (NOUVEAU)
3. claim_entities (conf 0.85)
4. section_context (conf 0.70)
5. document_context (conf 0.60)
6. ambiguous
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional, TYPE_CHECKING

from knowbase.claimfirst.models.resolved_scope import (
    ResolvedScope,
    ScopeAxis,
)

if TYPE_CHECKING:
    from knowbase.claimfirst.models.canonical_entity import CanonicalEntity
    from knowbase.claimfirst.models.document_context import DocumentContext
    from knowbase.claimfirst.models.entity import Entity
    from knowbase.claimfirst.models.passage import Passage

logger = logging.getLogger("[OSMOSE] scope_resolver")


# Mapping EntityType → anchor_type
_ENTITY_TYPE_TO_ANCHOR = {
    "product": "product",
    "service": "product",
    "feature": "product",
    "standard": "legal_frame",
    "legal_term": "legal_frame",
    "actor": "service_scope",
}

# Types non discriminants → passer au niveau suivant
_NON_DISCRIMINANT_TYPES = frozenset({"concept", "other"})

# Mapping scope_type LLM → anchor_type
_SCOPE_TYPE_TO_ANCHOR = {
    "product": "product",
    "service": "product",
    "component": "product",
    "regulation": "legal_frame",
    "population": "service_scope",
    "process": "service_scope",
    "other": None,
}


# ── Prompt LLM pour extraction de scope ──────────────────────────────

SCOPE_EXTRACTION_PROMPT = """Given a factual claim from a document, extract the SCOPE:
what specific entity/subject/context this claim applies to.

Respond in JSON:
{
  "primary_scope": "...",
  "secondary_scope": "...",
  "scope_type": "product|regulation|population|process|service|component|other",
  "scope_found": true/false,
  "confidence": 0.9
}

scope_type categories:
- product: software, hardware, tool, platform
- regulation: standard, legal framework, compliance rule
- population: user group, role, demographic
- process: workflow, procedure, business process
- service: cloud service, API, integration layer
- component: module, sub-system, feature
- other: anything else with a clear scope

If no specific scope can be determined from the claim text alone,
set scope_found=false."""


# ── V1 : resolve_scope (synchrone) ──────────────────────────────────

def resolve_scope(
    claim,
    entities: Optional[List] = None,
    canonical_entities: Optional[List] = None,
    passage=None,
    doc_context=None,
    scope_evidence: Optional[str] = None,
) -> ResolvedScope:
    """
    Résout le scope de comparabilité d'une claim (v1 synchrone, 5 niveaux).

    Cascade 5 niveaux, retourne dès qu'un scope est résolu.
    """
    entities = entities or []
    canonical_entities = canonical_entities or []

    # ── Priorité 1 : claim_explicit ────────────────────────────────────
    if scope_evidence:
        matched_ce = _match_scope_evidence(scope_evidence, canonical_entities)
        if matched_ce:
            anchor_type = _get_anchor_type(matched_ce)
            return ResolvedScope(
                primary_anchor_type=anchor_type,
                primary_anchor_id=matched_ce.canonical_entity_id,
                primary_anchor_label=matched_ce.canonical_name,
                axes=[ScopeAxis(
                    axis_key=anchor_type or "product",
                    value=matched_ce.canonical_name,
                    value_id=matched_ce.canonical_entity_id,
                    source="claim",
                )],
                scope_basis="claim_explicit",
                inheritance_mode="asserted",
                scope_status="resolved",
                scope_confidence=0.95,
                comparable_for_dimension=True,
            )

        return ResolvedScope(
            primary_anchor_type=None,
            primary_anchor_label=scope_evidence,
            scope_basis="claim_explicit",
            inheritance_mode="asserted",
            scope_status="resolved",
            scope_confidence=0.90,
            comparable_for_dimension=True,
        )

    # ── Priorité 2 : claim_entities ────────────────────────────────────
    best_entity = _find_best_entity(entities, canonical_entities)
    if best_entity:
        entity, ce = best_entity
        entity_type_str = _get_entity_type_str(entity)

        if entity_type_str not in _NON_DISCRIMINANT_TYPES:
            anchor_type = _ENTITY_TYPE_TO_ANCHOR.get(entity_type_str, "product")
            label = ce.canonical_name if ce else getattr(entity, "name", "")
            eid = ce.canonical_entity_id if ce else getattr(entity, "entity_id", None)

            return ResolvedScope(
                primary_anchor_type=anchor_type,
                primary_anchor_id=eid,
                primary_anchor_label=label,
                axes=[ScopeAxis(
                    axis_key=anchor_type,
                    value=label,
                    value_id=eid,
                    source="claim",
                )],
                scope_basis="claim_entities",
                inheritance_mode="asserted",
                scope_status="resolved",
                scope_confidence=0.85,
                comparable_for_dimension=True,
            )

    # ── Priorité 3 : section_context ───────────────────────────────────
    if passage:
        section_title = getattr(passage, "section_title", None)
        if section_title:
            return ResolvedScope(
                primary_anchor_label=section_title,
                scope_basis="section_context",
                inheritance_mode="inherited",
                scope_status="inherited",
                scope_confidence=0.70,
                comparable_for_dimension=True,
            )

    # ── Priorité 4 : document_context ──────────────────────────────────
    if doc_context:
        primary_subject = getattr(doc_context, "primary_subject", None)
        if primary_subject:
            return ResolvedScope(
                primary_anchor_label=primary_subject,
                scope_basis="document_context",
                inheritance_mode="inherited",
                scope_status="inherited",
                scope_confidence=0.60,
                comparable_for_dimension=True,
            )

    # ── Priorité 5 : ambiguous ─────────────────────────────────────────
    return ResolvedScope(
        scope_basis="missing",
        scope_status="ambiguous",
        scope_confidence=0.0,
        comparable_for_dimension=False,
    )


# ── V2 : resolve_scope_v2 (async, avec claim_llm) ───────────────────

async def resolve_scope_v2(
    claim,
    entities: Optional[List] = None,
    canonical_entities: Optional[List] = None,
    passage=None,
    doc_context=None,
    scope_evidence: Optional[str] = None,
    use_llm: bool = False,
) -> ResolvedScope:
    """
    Résout le scope de comparabilité d'une claim (v2 async, 6 niveaux).

    Cascade avec claim_llm entre claim_explicit et claim_entities.
    """
    entities = entities or []
    canonical_entities = canonical_entities or []

    # ── Priorité 1 : claim_explicit ────────────────────────────────────
    if scope_evidence:
        matched_ce = _match_scope_evidence(scope_evidence, canonical_entities)
        if matched_ce:
            anchor_type = _get_anchor_type(matched_ce)
            return ResolvedScope(
                primary_anchor_type=anchor_type,
                primary_anchor_id=matched_ce.canonical_entity_id,
                primary_anchor_label=matched_ce.canonical_name,
                axes=[ScopeAxis(
                    axis_key=anchor_type or "product",
                    value=matched_ce.canonical_name,
                    value_id=matched_ce.canonical_entity_id,
                    source="claim",
                )],
                scope_basis="claim_explicit",
                inheritance_mode="asserted",
                scope_status="resolved",
                scope_confidence=0.95,
                comparable_for_dimension=True,
            )

        return ResolvedScope(
            primary_anchor_type=None,
            primary_anchor_label=scope_evidence,
            scope_basis="claim_explicit",
            inheritance_mode="asserted",
            scope_status="resolved",
            scope_confidence=0.90,
            comparable_for_dimension=True,
        )

    # ── Priorité 1.5 : claim_llm ──────────────────────────────────────
    if use_llm:
        claim_text = getattr(claim, "text", "")
        if claim_text:
            llm_scope = await _extract_scope_via_llm(claim_text)
            if llm_scope and llm_scope.get("scope_found"):
                primary_scope = llm_scope.get("primary_scope", "")
                scope_type = llm_scope.get("scope_type", "other")
                confidence = min(llm_scope.get("confidence", 0.88), 0.88)
                anchor_type = _SCOPE_TYPE_TO_ANCHOR.get(scope_type)

                return ResolvedScope(
                    primary_anchor_type=anchor_type,
                    primary_anchor_label=primary_scope,
                    axes=[ScopeAxis(
                        axis_key=anchor_type or "product",
                        value=primary_scope,
                        source="claim",
                    )] if primary_scope else [],
                    scope_basis="claim_llm",
                    inheritance_mode="asserted",
                    scope_status="resolved",
                    scope_confidence=confidence,
                    comparable_for_dimension=True,
                )

    # ── Priorité 2 : claim_entities ────────────────────────────────────
    best_entity = _find_best_entity(entities, canonical_entities)
    if best_entity:
        entity, ce = best_entity
        entity_type_str = _get_entity_type_str(entity)

        if entity_type_str not in _NON_DISCRIMINANT_TYPES:
            anchor_type = _ENTITY_TYPE_TO_ANCHOR.get(entity_type_str, "product")
            label = ce.canonical_name if ce else getattr(entity, "name", "")
            eid = ce.canonical_entity_id if ce else getattr(entity, "entity_id", None)

            return ResolvedScope(
                primary_anchor_type=anchor_type,
                primary_anchor_id=eid,
                primary_anchor_label=label,
                axes=[ScopeAxis(
                    axis_key=anchor_type,
                    value=label,
                    value_id=eid,
                    source="claim",
                )],
                scope_basis="claim_entities",
                inheritance_mode="asserted",
                scope_status="resolved",
                scope_confidence=0.85,
                comparable_for_dimension=True,
            )

    # ── Priorité 3 : section_context ───────────────────────────────────
    if passage:
        section_title = getattr(passage, "section_title", None)
        if section_title:
            return ResolvedScope(
                primary_anchor_label=section_title,
                scope_basis="section_context",
                inheritance_mode="inherited",
                scope_status="inherited",
                scope_confidence=0.70,
                comparable_for_dimension=True,
            )

    # ── Priorité 4 : document_context ──────────────────────────────────
    if doc_context:
        primary_subject = getattr(doc_context, "primary_subject", None)
        if primary_subject:
            return ResolvedScope(
                primary_anchor_label=primary_subject,
                scope_basis="document_context",
                inheritance_mode="inherited",
                scope_status="inherited",
                scope_confidence=0.60,
                comparable_for_dimension=True,
            )

    # ── Priorité 5 : ambiguous ─────────────────────────────────────────
    return ResolvedScope(
        scope_basis="missing",
        scope_status="ambiguous",
        scope_confidence=0.0,
        comparable_for_dimension=False,
    )


# ── LLM scope extraction ─────────────────────────────────────────────

async def _extract_scope_via_llm(claim_text: str) -> Optional[dict]:
    """Extrait le scope d'une claim via LLM."""
    try:
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()
        response = await router.acomplete(
            task_type=TaskType.METADATA_EXTRACTION,
            messages=[
                {"role": "system", "content": SCOPE_EXTRACTION_PROMPT},
                {"role": "user", "content": f'Claim: "{claim_text}"'},
            ],
            temperature=0.1,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        return _parse_scope_llm_response(response)
    except Exception as e:
        logger.warning(f"[ScopeResolver] LLM extraction failed: {e}")
        return None


def _parse_scope_llm_response(response) -> Optional[dict]:
    """Parse la réponse LLM de scope extraction."""
    try:
        text = response if isinstance(response, str) else getattr(response, "text", str(response))
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        # Valider scope_type
        valid_types = {"product", "regulation", "population", "process", "service", "component", "other"}
        scope_type = data.get("scope_type", "other")
        if scope_type not in valid_types:
            data["scope_type"] = "other"
        return data
    except (json.JSONDecodeError, AttributeError):
        return None


# ── Helpers communs ──────────────────────────────────────────────────

def _match_scope_evidence(
    scope_evidence: str,
    canonical_entities: list,
) -> Optional[object]:
    """Cherche un CanonicalEntity dont le nom matche le scope_evidence."""
    evidence_lower = scope_evidence.lower().strip()
    for ce in canonical_entities:
        name = getattr(ce, "canonical_name", "")
        if name.lower() in evidence_lower or evidence_lower in name.lower():
            return ce
    return None


def _find_best_entity(
    entities: list,
    canonical_entities: list,
) -> Optional[tuple]:
    """Trouve la meilleure entité discriminante avec son CE."""
    ce_by_source = {}
    for ce in canonical_entities:
        for src_id in getattr(ce, "source_entity_ids", []):
            ce_by_source[src_id] = ce

    for entity in entities:
        eid = getattr(entity, "entity_id", None)
        etype = _get_entity_type_str(entity)
        if etype not in _NON_DISCRIMINANT_TYPES:
            ce = ce_by_source.get(eid)
            return (entity, ce)

    return None


def _get_entity_type_str(entity) -> str:
    """Extrait le type d'entité comme string."""
    etype = getattr(entity, "entity_type", "other")
    return etype.value if hasattr(etype, "value") else str(etype)


def _get_anchor_type(ce) -> Optional[str]:
    """Détermine le anchor_type depuis un CanonicalEntity."""
    etype = getattr(ce, "entity_type", None)
    if etype:
        etype_str = etype.value if hasattr(etype, "value") else str(etype)
        return _ENTITY_TYPE_TO_ANCHOR.get(etype_str)
    return None


__all__ = [
    "resolve_scope",
    "resolve_scope_v2",
    "SCOPE_EXTRACTION_PROMPT",
    "_parse_scope_llm_response",
]
