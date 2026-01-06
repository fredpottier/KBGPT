"""
Router API pour les Markers (PR3 - ADR_ASSERTION_AWARE_KG).

Endpoints:
- GET /markers: Liste tous les markers disponibles
- GET /markers/{value}: Détails d'un marker spécifique
- GET /markers/{value}/concepts: Concepts associés à un marker

Normalization endpoints (ADR_MARKER_NORMALIZATION_LAYER):
- GET /markers/normalization/suggestions: Suggestions de normalisation
- POST /markers/normalization/apply: Appliquer une normalisation
- GET /markers/normalization/aliases: Liste des aliases
- POST /markers/normalization/aliases: Ajouter un alias
- DELETE /markers/normalization/aliases/{raw_marker}: Supprimer un alias
- POST /markers/normalization/blacklist: Ajouter à la blacklist
- GET /markers/normalization/stats: Statistiques de normalisation
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends, Body
from pydantic import BaseModel, Field

from knowbase.consolidation.marker_store import (
    MarkerStore,
    MarkerKind,
    get_marker_store,
)
from knowbase.consolidation.normalization import (
    NormalizationEngine,
    NormalizationStore,
    MarkerMention,
    CanonicalMarker,
    NormalizationStatus,
    get_normalization_engine,
    get_normalization_store,
)
from knowbase.api.dependencies import get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "markers_router.log")

router = APIRouter(prefix="/markers", tags=["markers"])


class MarkerInfo(BaseModel):
    """Information sur un marker."""
    value: str
    kind: str
    concept_count: int = 0
    avg_confidence: Optional[float] = None


class MarkerListResponse(BaseModel):
    """Liste de markers."""
    markers: List[MarkerInfo] = Field(default_factory=list)
    total: int = 0


class ConceptInMarker(BaseModel):
    """Concept associé à un marker."""
    concept_id: str
    label: str
    confidence: float
    is_inherited: bool = False
    canonical_id: Optional[str] = None
    canonical_name: Optional[str] = None


class MarkerConceptsResponse(BaseModel):
    """Concepts associés à un marker."""
    marker_value: str
    concepts: List[ConceptInMarker] = Field(default_factory=list)
    total: int = 0


@router.get(
    "",
    response_model=MarkerListResponse,
    summary="Liste des markers",
    description="""
    Récupère tous les markers disponibles dans le Knowledge Graph.

    Les markers sont des identifiants de contexte (versions, éditions, etc.)
    extraits des documents. Ils permettent de filtrer et comparer les concepts.

    **Types de markers**:
    - `numeric_code`: Codes SAP (1809, 2020, 2508)
    - `version`: Versions (v1.0.0, 3.2.1)
    - `fps`: Feature Pack Stacks (FPS03, FPS05)
    - `sp`: Support Packages (SP02, SP100)
    - `year`: Années (2024, 2025)
    - `edition`: Éditions (Cloud, Private, Public)
    """,
)
async def list_markers(
    kind: Optional[str] = Query(None, description="Filtrer par type de marker"),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
) -> MarkerListResponse:
    """
    Liste tous les markers disponibles.

    Args:
        kind: Type de marker à filtrer (optionnel)
        limit: Nombre max de résultats
        tenant_id: ID tenant

    Returns:
        MarkerListResponse avec la liste des markers
    """
    logger.info(f"[MARKERS:LIST] Request (kind={kind}, limit={limit}, tenant={tenant_id})")

    try:
        store = get_marker_store(tenant_id)

        # Filtrer par kind si spécifié
        kind_filter = None
        if kind:
            try:
                kind_filter = MarkerKind(kind)
            except ValueError:
                pass  # Ignorer kind invalide

        markers_data = await store.get_all_markers(kind_filter=kind_filter)

        # Limiter les résultats
        markers_data = markers_data[:limit]

        markers = [
            MarkerInfo(
                value=m.get("value", ""),
                kind=m.get("kind", "unknown"),
                concept_count=m.get("concept_count", 0),
                avg_confidence=m.get("avg_confidence"),
            )
            for m in markers_data
        ]

        logger.info(f"[MARKERS:LIST] Found {len(markers)} markers")

        return MarkerListResponse(
            markers=markers,
            total=len(markers),
        )

    except Exception as e:
        logger.error(f"[MARKERS:LIST] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list markers: {str(e)}"
        )


@router.get(
    "/{marker_value}",
    response_model=MarkerInfo,
    summary="Détails d'un marker",
    description="Récupère les informations détaillées d'un marker spécifique.",
)
async def get_marker(
    marker_value: str,
    tenant_id: str = Depends(get_tenant_id),
) -> MarkerInfo:
    """
    Récupère les détails d'un marker.

    Args:
        marker_value: Valeur du marker
        tenant_id: ID tenant

    Returns:
        MarkerInfo avec les détails
    """
    logger.info(f"[MARKERS:GET] Request for {marker_value}")

    try:
        store = get_marker_store(tenant_id)
        markers_data = await store.get_all_markers()

        # Chercher le marker
        for m in markers_data:
            if m.get("value") == marker_value:
                return MarkerInfo(
                    value=m.get("value", ""),
                    kind=m.get("kind", "unknown"),
                    concept_count=m.get("concept_count", 0),
                    avg_confidence=m.get("avg_confidence"),
                )

        raise HTTPException(
            status_code=404,
            detail=f"Marker '{marker_value}' not found"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MARKERS:GET] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get marker: {str(e)}"
        )


@router.get(
    "/{marker_value}/concepts",
    response_model=MarkerConceptsResponse,
    summary="Concepts d'un marker",
    description="""
    Récupère tous les concepts associés à un marker.

    Utile pour voir quels concepts sont valides pour une version/édition spécifique.
    """,
)
async def get_marker_concepts(
    marker_value: str,
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: str = Depends(get_tenant_id),
) -> MarkerConceptsResponse:
    """
    Récupère les concepts associés à un marker.

    Args:
        marker_value: Valeur du marker
        min_confidence: Confiance minimale
        limit: Nombre max de résultats
        tenant_id: ID tenant

    Returns:
        MarkerConceptsResponse avec les concepts
    """
    logger.info(f"[MARKERS:CONCEPTS] Request for {marker_value} (min_conf={min_confidence})")

    try:
        store = get_marker_store(tenant_id)
        concepts_data = await store.get_concepts_with_marker(
            marker_value=marker_value,
            min_confidence=min_confidence,
        )

        # Limiter
        concepts_data = concepts_data[:limit]

        concepts = [
            ConceptInMarker(
                concept_id=c.get("concept_id", ""),
                label=c.get("label", ""),
                confidence=c.get("confidence", 0.0),
                is_inherited=c.get("is_inherited", False),
                canonical_id=c.get("canonical_id"),
                canonical_name=c.get("canonical_name"),
            )
            for c in concepts_data
        ]

        return MarkerConceptsResponse(
            marker_value=marker_value,
            concepts=concepts,
            total=len(concepts),
        )

    except Exception as e:
        logger.error(f"[MARKERS:CONCEPTS] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get marker concepts: {str(e)}"
        )


# =============================================================================
# Normalization Models (Phase 4)
# =============================================================================


class NormalizationSuggestion(BaseModel):
    """Suggestion de normalisation pour un marker."""
    mention_id: str
    raw_text: str
    doc_id: str
    suggested_canonical: Optional[str] = None
    entity_anchor: Optional[str] = None
    rule_id: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""


class SuggestionsResponse(BaseModel):
    """Liste de suggestions de normalisation."""
    suggestions: List[NormalizationSuggestion] = Field(default_factory=list)
    total_unresolved: int = 0
    total_resolved: int = 0
    total_blacklisted: int = 0


class ApplyNormalizationRequest(BaseModel):
    """Requête pour appliquer une normalisation."""
    mention_id: str = Field(..., description="ID de la mention à normaliser")
    canonical_form: str = Field(..., description="Forme canonique à appliquer")
    entity_anchor: Optional[str] = Field(None, description="Entity Anchor (optionnel)")
    create_alias: bool = Field(False, description="Créer un alias pour applications futures")


class ApplyNormalizationResponse(BaseModel):
    """Réponse après application d'une normalisation."""
    success: bool
    mention_id: str
    canonical_id: Optional[str] = None
    canonical_form: Optional[str] = None
    alias_created: bool = False
    message: str = ""


class AliasInfo(BaseModel):
    """Information sur un alias."""
    raw_marker: str
    canonical_form: str


class AliasListResponse(BaseModel):
    """Liste des aliases configurés."""
    aliases: List[AliasInfo] = Field(default_factory=list)
    total: int = 0
    max_allowed: int = 200


class AddAliasRequest(BaseModel):
    """Requête pour ajouter un alias."""
    raw_marker: str = Field(..., description="Marker brut")
    canonical_form: str = Field(..., description="Forme canonique")


class BlacklistRequest(BaseModel):
    """Requête pour ajouter à la blacklist."""
    marker: str = Field(..., description="Marker à blacklister")


class NormalizationStats(BaseModel):
    """Statistiques de normalisation."""
    total_mentions: int = 0
    resolved: int = 0
    unresolved: int = 0
    blacklisted: int = 0
    pending_review: int = 0
    resolution_rate: float = 0.0
    unique_canonicals: int = 0
    aliases_count: int = 0
    blacklist_count: int = 0
    rules_count: int = 0


class ClusterSuggestion(BaseModel):
    """Suggestion de clustering pour markers similaires."""
    cluster_id: str
    raw_markers: List[str]
    suggested_canonical: str
    document_count: int
    confidence: float
    reason: str


class ClusterSuggestionsResponse(BaseModel):
    """Liste de suggestions de clustering."""
    clusters: List[ClusterSuggestion] = Field(default_factory=list)
    total: int = 0


# =============================================================================
# Normalization Endpoints (Phase 4)
# =============================================================================


@router.get(
    "/normalization/suggestions",
    response_model=SuggestionsResponse,
    summary="Suggestions de normalisation",
    description="""
    Récupère les suggestions de normalisation pour les markers non résolus.

    Permet de voir quels markers pourraient être normalisés et avec quelle
    forme canonique suggérée.
    """,
)
async def get_normalization_suggestions(
    doc_id: Optional[str] = Query(None, description="Filtrer par document"),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
) -> SuggestionsResponse:
    """
    Récupère les suggestions de normalisation.

    Args:
        doc_id: ID du document (optionnel)
        limit: Nombre max de résultats
        tenant_id: ID tenant

    Returns:
        SuggestionsResponse avec les suggestions
    """
    logger.info(f"[MARKERS:SUGGESTIONS] Request (doc_id={doc_id}, tenant={tenant_id})")

    try:
        store = get_normalization_store(tenant_id)
        engine = get_normalization_engine(tenant_id)
        engine.load_config()

        # Récupérer les mentions non résolues
        if doc_id:
            mentions = await store.get_mentions_by_doc(doc_id)
        else:
            mentions = await store.get_unresolved_mentions(limit=limit)

        suggestions = []
        for mention in mentions:
            if mention.normalization_status != NormalizationStatus.UNRESOLVED:
                continue

            # Tenter de trouver une suggestion
            result = await engine.normalize_mention(mention)

            suggestion = NormalizationSuggestion(
                mention_id=mention.id,
                raw_text=mention.raw_text,
                doc_id=mention.doc_id,
                suggested_canonical=result.canonical_marker.canonical_form if result.canonical_marker else None,
                entity_anchor=result.entity_anchor_found,
                rule_id=result.rule_applied,
                confidence=result.confidence,
                reason=result.reason,
            )
            suggestions.append(suggestion)

        # Stats
        stats = await store.get_normalization_stats()

        return SuggestionsResponse(
            suggestions=suggestions[:limit],
            total_unresolved=stats.get("unresolved", 0),
            total_resolved=stats.get("resolved", 0),
            total_blacklisted=stats.get("blacklisted", 0),
        )

    except Exception as e:
        logger.error(f"[MARKERS:SUGGESTIONS] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get suggestions: {str(e)}"
        )


@router.post(
    "/normalization/apply",
    response_model=ApplyNormalizationResponse,
    summary="Appliquer une normalisation",
    description="""
    Applique une normalisation manuelle sur une mention.

    Permet à un administrateur de normaliser un marker avec une forme canonique
    spécifique. Peut optionnellement créer un alias pour applications futures.
    """,
)
async def apply_normalization(
    request: ApplyNormalizationRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> ApplyNormalizationResponse:
    """
    Applique une normalisation manuelle.

    Args:
        request: Données de normalisation
        tenant_id: ID tenant

    Returns:
        ApplyNormalizationResponse avec le résultat
    """
    logger.info(
        f"[MARKERS:APPLY] Normalizing {request.mention_id} → '{request.canonical_form}'"
    )

    try:
        store = get_normalization_store(tenant_id)
        engine = get_normalization_engine(tenant_id)

        # Récupérer la mention
        mention = await store.get_mention_by_id(request.mention_id)
        if not mention:
            raise HTTPException(
                status_code=404,
                detail=f"Mention '{request.mention_id}' not found"
            )

        # Créer ou récupérer le canonical
        canonical = await store.ensure_canonical_marker(
            canonical_form=request.canonical_form,
            entity_anchor=request.entity_anchor or "",
            created_by="user:manual",
            confidence=1.0,
        )

        # Lier mention → canonical
        success = await store.link_mention_to_canonical(
            mention_id=mention.id,
            canonical_id=canonical.id,
            rule_id="manual",
            confidence=1.0,
        )

        # Créer alias si demandé
        alias_created = False
        if request.create_alias:
            alias_created = await engine.add_alias(
                raw_marker=mention.raw_text,
                canonical_form=request.canonical_form,
                persist=True,
            )

        return ApplyNormalizationResponse(
            success=success,
            mention_id=mention.id,
            canonical_id=canonical.id,
            canonical_form=canonical.canonical_form,
            alias_created=alias_created,
            message=f"Normalized '{mention.raw_text}' → '{canonical.canonical_form}'"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MARKERS:APPLY] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply normalization: {str(e)}"
        )


@router.get(
    "/normalization/aliases",
    response_model=AliasListResponse,
    summary="Liste des aliases",
    description="Récupère la liste des aliases configurés pour le tenant.",
)
async def list_aliases(
    tenant_id: str = Depends(get_tenant_id),
) -> AliasListResponse:
    """
    Liste tous les aliases configurés.

    Args:
        tenant_id: ID tenant

    Returns:
        AliasListResponse avec les aliases
    """
    logger.info(f"[MARKERS:ALIASES] Listing aliases for tenant {tenant_id}")

    try:
        engine = get_normalization_engine(tenant_id)
        config = engine.load_config()

        aliases = [
            AliasInfo(raw_marker=raw, canonical_form=canonical)
            for raw, canonical in config.aliases.items()
        ]

        return AliasListResponse(
            aliases=aliases,
            total=len(aliases),
            max_allowed=config.max_aliases,
        )

    except Exception as e:
        logger.error(f"[MARKERS:ALIASES] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list aliases: {str(e)}"
        )


@router.post(
    "/normalization/aliases",
    response_model=AliasInfo,
    summary="Ajouter un alias",
    description="Ajoute un nouvel alias de normalisation.",
)
async def add_alias(
    request: AddAliasRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> AliasInfo:
    """
    Ajoute un nouvel alias.

    Args:
        request: Données de l'alias
        tenant_id: ID tenant

    Returns:
        AliasInfo de l'alias créé
    """
    logger.info(
        f"[MARKERS:ALIASES] Adding alias: '{request.raw_marker}' → '{request.canonical_form}'"
    )

    try:
        engine = get_normalization_engine(tenant_id)
        engine.load_config()

        success = await engine.add_alias(
            raw_marker=request.raw_marker,
            canonical_form=request.canonical_form,
            persist=True,
        )

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to add alias (max aliases reached?)"
            )

        return AliasInfo(
            raw_marker=request.raw_marker,
            canonical_form=request.canonical_form,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MARKERS:ALIASES] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add alias: {str(e)}"
        )


@router.delete(
    "/normalization/aliases/{raw_marker}",
    summary="Supprimer un alias",
    description="Supprime un alias de normalisation.",
)
async def delete_alias(
    raw_marker: str,
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """
    Supprime un alias.

    Args:
        raw_marker: Marker brut de l'alias à supprimer
        tenant_id: ID tenant

    Returns:
        Confirmation de suppression
    """
    logger.info(f"[MARKERS:ALIASES] Deleting alias: '{raw_marker}'")

    try:
        engine = get_normalization_engine(tenant_id)
        config = engine.load_config()

        if raw_marker not in config.aliases:
            raise HTTPException(
                status_code=404,
                detail=f"Alias '{raw_marker}' not found"
            )

        del config.aliases[raw_marker]
        # TODO: Persist to YAML

        return {"success": True, "deleted": raw_marker}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MARKERS:ALIASES] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete alias: {str(e)}"
        )


@router.post(
    "/normalization/blacklist",
    summary="Ajouter à la blacklist",
    description="Ajoute un marker à la blacklist (faux positifs).",
)
async def add_to_blacklist(
    request: BlacklistRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """
    Ajoute un marker à la blacklist.

    Args:
        request: Marker à blacklister
        tenant_id: ID tenant

    Returns:
        Confirmation d'ajout
    """
    logger.info(f"[MARKERS:BLACKLIST] Adding to blacklist: '{request.marker}'")

    try:
        engine = get_normalization_engine(tenant_id)
        engine.load_config()

        success = await engine.add_to_blacklist(
            marker=request.marker,
            persist=True,
        )

        return {"success": success, "blacklisted": request.marker}

    except Exception as e:
        logger.error(f"[MARKERS:BLACKLIST] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add to blacklist: {str(e)}"
        )


# =============================================================================
# Normalization Metrics (Phase 5)
# =============================================================================


@router.get(
    "/normalization/stats",
    response_model=NormalizationStats,
    summary="Statistiques de normalisation",
    description="""
    Récupère les statistiques de normalisation pour le tenant.

    Inclut le nombre de mentions résolues, non résolues, blacklistées,
    ainsi que le taux de résolution et le nombre de canoniques uniques.
    """,
)
async def get_normalization_stats(
    tenant_id: str = Depends(get_tenant_id),
) -> NormalizationStats:
    """
    Récupère les statistiques de normalisation.

    Args:
        tenant_id: ID tenant

    Returns:
        NormalizationStats avec les métriques
    """
    logger.info(f"[MARKERS:STATS] Getting stats for tenant {tenant_id}")

    try:
        store = get_normalization_store(tenant_id)
        engine = get_normalization_engine(tenant_id)
        config = engine.load_config()

        stats = await store.get_normalization_stats()

        total = stats.get("total", 0)
        resolved = stats.get("resolved", 0)

        return NormalizationStats(
            total_mentions=total,
            resolved=resolved,
            unresolved=stats.get("unresolved", 0),
            blacklisted=stats.get("blacklisted", 0),
            pending_review=stats.get("pending", 0),
            resolution_rate=resolved / total if total > 0 else 0.0,
            unique_canonicals=stats.get("unique_canonicals", 0),
            aliases_count=len(config.aliases),
            blacklist_count=len(config.blacklist),
            rules_count=len(config.rules),
        )

    except Exception as e:
        logger.error(f"[MARKERS:STATS] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get stats: {str(e)}"
        )


@router.get(
    "/normalization/clusters",
    response_model=ClusterSuggestionsResponse,
    summary="Suggestions de clustering",
    description="""
    Analyse les markers non résolus et suggère des regroupements.

    Identifie les markers similaires qui pourraient partager une même
    forme canonique, basé sur la co-occurrence dans les documents.
    """,
)
async def get_cluster_suggestions(
    min_documents: int = Query(default=2, ge=1, description="Documents min pour cluster"),
    limit: int = Query(default=20, ge=1, le=100),
    tenant_id: str = Depends(get_tenant_id),
) -> ClusterSuggestionsResponse:
    """
    Récupère les suggestions de clustering.

    Args:
        min_documents: Nombre minimum de documents pour un cluster
        limit: Nombre max de clusters
        tenant_id: ID tenant

    Returns:
        ClusterSuggestionsResponse avec les clusters suggérés
    """
    logger.info(f"[MARKERS:CLUSTERS] Getting clusters (min_docs={min_documents})")

    try:
        store = get_normalization_store(tenant_id)

        # Récupérer les mentions non résolues groupées par raw_text
        clusters_data = await store.get_marker_clusters(
            min_documents=min_documents,
            limit=limit,
        )

        clusters = []
        for i, cluster in enumerate(clusters_data):
            raw_markers = cluster.get("raw_markers", [])
            doc_count = cluster.get("document_count", 0)
            entity_anchor = cluster.get("common_entity", "")

            # Suggérer une forme canonique
            if entity_anchor and raw_markers:
                suggested = f"{entity_anchor} {raw_markers[0]}"
            else:
                suggested = raw_markers[0] if raw_markers else ""

            clusters.append(ClusterSuggestion(
                cluster_id=f"cluster_{i}",
                raw_markers=raw_markers,
                suggested_canonical=suggested,
                document_count=doc_count,
                confidence=min(0.9, doc_count * 0.15),
                reason=f"Co-occurs in {doc_count} documents"
                       + (f" with entity '{entity_anchor}'" if entity_anchor else ""),
            ))

        return ClusterSuggestionsResponse(
            clusters=clusters,
            total=len(clusters),
        )

    except Exception as e:
        logger.error(f"[MARKERS:CLUSTERS] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get clusters: {str(e)}"
        )


__all__ = ["router"]
