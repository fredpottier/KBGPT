"""
Router API pour la Navigation Layer (ADR: ADR_NAVIGATION_LAYER.md).

Endpoints pour explorer la couche de navigation non-sémantique.

IMPORTANT: Cette couche est pour la NAVIGATION corpus-level uniquement.
Elle ne doit JAMAIS être utilisée pour le raisonnement sémantique.

Author: Claude Code
Date: 2026-01-01
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from knowbase.api.dependencies import get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from knowbase.navigation import (
    get_navigation_layer_builder,
    GraphLinter,
    LintResult,
    validate_graph,
)

settings = get_settings()
logger = setup_logging(settings.logs_dir, "navigation_router.log")

router = APIRouter(prefix="/navigation", tags=["navigation"])


# ============================================================================
# Schemas
# ============================================================================

class NavigationStatsResponse(BaseModel):
    """Statistiques de la Navigation Layer."""
    document_count: int = Field(0, description="Nombre de DocumentContext")
    section_count: int = Field(0, description="Nombre de SectionContext")
    window_count: int = Field(0, description="Nombre de WindowContext (si activé)")
    mention_relations: int = Field(0, description="Nombre de liens MENTIONED_IN")
    concepts_with_mentions: int = Field(0, description="Concepts avec au moins une mention")


class LintViolationResponse(BaseModel):
    """Violation d'une règle de lint."""
    rule_id: str
    message: str
    severity: str
    details: Dict[str, Any] = Field(default_factory=dict)


class LintResultResponse(BaseModel):
    """Résultat de validation du graphe."""
    success: bool = Field(..., description="True si aucune violation")
    violation_count: int = Field(0, description="Nombre de violations")
    violations: List[LintViolationResponse] = Field(default_factory=list)
    stats: Dict[str, int] = Field(default_factory=dict)


class ConceptMention(BaseModel):
    """Mention d'un concept dans un contexte."""
    context_id: str
    context_kind: str
    document_id: str
    document_name: Optional[str] = None
    section_path: Optional[str] = None
    count: int = 1
    weight: float = 0.0


class ConceptMentionsResponse(BaseModel):
    """Réponse avec les mentions d'un concept."""
    canonical_id: str
    canonical_name: Optional[str] = None
    total_mentions: int = 0
    mentions: List[ConceptMention] = Field(default_factory=list)


class DocumentContextResponse(BaseModel):
    """Concepts mentionnés dans un document."""
    document_id: str
    document_name: Optional[str] = None
    concepts: List[Dict[str, Any]] = Field(default_factory=list)
    total_concepts: int = 0


# ============================================================================
# Endpoints
# ============================================================================

@router.get(
    "/stats",
    response_model=NavigationStatsResponse,
    summary="Statistiques Navigation Layer",
    description="""
    Retourne les statistiques de la couche de navigation.

    **Métriques**:
    - Nombre de ContextNodes par type (Document, Section, Window)
    - Nombre de relations MENTIONED_IN
    - Nombre de concepts avec au moins une mention
    """
)
async def get_navigation_stats(
    tenant_id: str = Depends(get_tenant_id)
) -> NavigationStatsResponse:
    """Retourne les statistiques de la Navigation Layer."""
    try:
        linter = GraphLinter(tenant_id=tenant_id)
        stats = linter.get_navigation_stats()

        return NavigationStatsResponse(
            document_count=stats.get("document_count", 0),
            section_count=stats.get("section_count", 0),
            window_count=stats.get("window_count", 0),
            mention_relations=stats.get("mention_relations", 0),
            concepts_with_mentions=stats.get("concepts_with_mentions", 0),
        )

    except Exception as e:
        logger.error(f"[Navigation API] Stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/validate",
    response_model=LintResultResponse,
    summary="Valider le graphe",
    description="""
    Exécute les règles de lint pour valider la séparation navigation/sémantique.

    **Règles validées**:
    - NAV-001: Pas de navigation edges Concept→Concept
    - NAV-002: Pas de sémantique vers ContextNode
    - NAV-003: Pas de sémantique depuis ContextNode
    - NAV-004: MENTIONED_IN a les propriétés requises

    **Retourne**: success=true si 0 violations
    """
)
async def validate_navigation_graph(
    tenant_id: str = Depends(get_tenant_id)
) -> LintResultResponse:
    """Valide le graphe avec les règles de lint."""
    try:
        result = validate_graph(tenant_id=tenant_id)

        violations = [
            LintViolationResponse(
                rule_id=v.rule_id.value,
                message=v.message,
                severity=v.severity,
                details=v.details,
            )
            for v in result.violations
        ]

        return LintResultResponse(
            success=result.success,
            violation_count=len(violations),
            violations=violations,
            stats=result.stats,
        )

    except Exception as e:
        logger.error(f"[Navigation API] Validation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/document/{document_id}",
    response_model=DocumentContextResponse,
    summary="Concepts d'un document",
    description="""
    Retourne les concepts mentionnés dans un document via la Navigation Layer.

    **Note**: Utilise les liens MENTIONED_IN, pas les relations sémantiques.
    """
)
async def get_document_concepts(
    document_id: str,
    limit: int = Query(50, ge=1, le=200, description="Nombre max de concepts"),
    min_weight: float = Query(0.0, ge=0.0, le=1.0, description="Poids minimum"),
    tenant_id: str = Depends(get_tenant_id)
) -> DocumentContextResponse:
    """Retourne les concepts mentionnés dans un document."""
    try:
        builder = get_navigation_layer_builder(tenant_id=tenant_id)

        # Requête pour récupérer les concepts
        query = """
        MATCH (ctx:ContextNode {context_id: $context_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (c:CanonicalConcept {tenant_id: $tenant_id})-[r:MENTIONED_IN]->(ctx)
        WHERE r.weight >= $min_weight
        WITH ctx, c, r
        ORDER BY r.weight DESC
        LIMIT $limit

        RETURN ctx.document_name AS document_name,
               collect({
                   canonical_id: c.canonical_id,
                   canonical_name: c.canonical_name,
                   count: r.count,
                   weight: r.weight
               }) AS concepts
        """

        results = builder._execute_query(query, {
            "context_id": f"doc:{document_id}",
            "tenant_id": tenant_id,
            "limit": limit,
            "min_weight": min_weight,
        })

        if not results:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found in Navigation Layer")

        r = results[0]
        concepts = [c for c in r.get("concepts", []) if c.get("canonical_id")]

        return DocumentContextResponse(
            document_id=document_id,
            document_name=r.get("document_name"),
            concepts=concepts,
            total_concepts=len(concepts),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Navigation API] Document concepts failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/concept/{canonical_id}/mentions",
    response_model=ConceptMentionsResponse,
    summary="Mentions d'un concept",
    description="""
    Retourne les contextes où un concept est mentionné.

    **Use case**: Explorer dans quels documents/sections un concept apparaît.

    **Note**: Navigation corpus-level, pas raisonnement sémantique.
    """
)
async def get_concept_mentions(
    canonical_id: str,
    limit: int = Query(50, ge=1, le=200, description="Nombre max de mentions"),
    include_sections: bool = Query(True, description="Inclure les sections"),
    tenant_id: str = Depends(get_tenant_id)
) -> ConceptMentionsResponse:
    """Retourne les contextes où un concept est mentionné."""
    try:
        builder = get_navigation_layer_builder(tenant_id=tenant_id)

        # Filtrer par kind si nécessaire
        kind_filter = "" if include_sections else "AND ctx.kind = 'document'"

        query = f"""
        MATCH (c:CanonicalConcept {{canonical_id: $canonical_id, tenant_id: $tenant_id}})
        OPTIONAL MATCH (c)-[r:MENTIONED_IN]->(ctx:ContextNode {{tenant_id: $tenant_id}})
        {kind_filter}
        WITH c, r, ctx
        ORDER BY r.weight DESC
        LIMIT $limit

        RETURN c.canonical_name AS canonical_name,
               collect({{
                   context_id: ctx.context_id,
                   context_kind: ctx.kind,
                   document_id: ctx.doc_id,
                   document_name: ctx.document_name,
                   section_path: ctx.section_path,
                   count: r.count,
                   weight: r.weight
               }}) AS mentions
        """

        results = builder._execute_query(query, {
            "canonical_id": canonical_id,
            "tenant_id": tenant_id,
            "limit": limit,
        })

        if not results:
            raise HTTPException(status_code=404, detail=f"Concept {canonical_id} not found")

        r = results[0]
        mentions = [
            ConceptMention(
                context_id=m["context_id"],
                context_kind=m["context_kind"],
                document_id=m["document_id"],
                document_name=m.get("document_name"),
                section_path=m.get("section_path"),
                count=m.get("count", 1),
                weight=m.get("weight", 0.0),
            )
            for m in r.get("mentions", [])
            if m.get("context_id")
        ]

        return ConceptMentionsResponse(
            canonical_id=canonical_id,
            canonical_name=r.get("canonical_name"),
            total_mentions=len(mentions),
            mentions=mentions,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Navigation API] Concept mentions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
