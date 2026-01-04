"""
Router API pour les analytics d'import.

Endpoints:
- GET /api/analytics/imports : Liste des imports disponibles
- GET /api/analytics/imports/{file_hash} : Analytics détaillées d'un import
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from knowbase.api.services.import_analytics_service import (
    ImportAnalyticsService,
    ImportAnalytics,
)
from knowbase.api.services.pass2_quality_service import (
    Pass2QualityService,
    get_pass2_quality_service,
    QualityVerdict,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# === Pydantic Models ===

class ImportListItem(BaseModel):
    """Item dans la liste des imports."""
    cache_file: str
    file_hash: str
    document_id: str
    source_path: str
    file_type: str
    total_pages: int
    total_chars: int
    created_at: str


class PhaseMetricsResponse(BaseModel):
    """Métriques d'une phase."""
    name: str
    duration_ms: float
    llm_calls: int = 0
    llm_model: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class GatingAnalysisResponse(BaseModel):
    """Analyse du Vision Gating."""
    total_pages: int
    vision_required: int
    vision_recommended: int
    no_vision: int
    avg_vns: float
    max_vns: float
    reasons_distribution: Dict[str, int]


class VisionAnalysisResponse(BaseModel):
    """Analyse des extractions Vision."""
    pages_processed: int
    total_elements: int
    total_relations: int
    avg_elements_per_page: float
    element_types: Dict[str, int]


class OsmoseAnalysisResponse(BaseModel):
    """Analyse OSMOSE."""
    proto_concepts: int
    canonical_concepts: int
    topics_segmented: int
    relations_stored: int
    phase2_relations: int
    embeddings_stored: int


class ImportAnalyticsResponse(BaseModel):
    """Réponse complète d'analytics."""
    document_id: str
    document_name: str
    file_type: str
    import_timestamp: str
    cache_used: bool
    total_pages: int
    total_chars: int
    total_duration_ms: float
    phases: List[PhaseMetricsResponse]
    gating: Optional[GatingAnalysisResponse] = None
    vision: Optional[VisionAnalysisResponse] = None
    osmose: Optional[OsmoseAnalysisResponse] = None
    quality_score: float
    quality_notes: List[str]


class ImportListResponse(BaseModel):
    """Réponse liste des imports."""
    imports: List[ImportListItem]
    total: int


# === Service Dependency ===

def get_analytics_service() -> ImportAnalyticsService:
    """Dependency injection pour le service analytics."""
    import os
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
        neo4j_client = get_neo4j_client(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
        )
    except Exception as e:
        logger.warning(f"[Analytics] Neo4j connection failed: {e}")
        neo4j_client = None

    return ImportAnalyticsService(
        cache_dir="/data/extraction_cache",
        neo4j_client=neo4j_client,
    )


# === Endpoints ===

@router.get("/imports", response_model=ImportListResponse)
async def list_imports(
    limit: int = 50,
    service: ImportAnalyticsService = Depends(get_analytics_service),
):
    """
    Liste les imports disponibles.

    Retourne les documents importés avec leurs métadonnées de base.
    """
    try:
        imports = service.list_imports(limit=limit)
        return ImportListResponse(
            imports=[ImportListItem(**imp) for imp in imports],
            total=len(imports),
        )
    except Exception as e:
        logger.error(f"[Analytics] Error listing imports: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/imports/{file_hash}", response_model=ImportAnalyticsResponse)
async def get_import_analytics(
    file_hash: str,
    service: ImportAnalyticsService = Depends(get_analytics_service),
):
    """
    Récupère les analytics détaillées d'un import.

    Args:
        file_hash: Hash SHA256 du fichier source (identifiant du cache)

    Returns:
        Analytics complètes incluant:
        - Métriques par phase (temps, appels LLM)
        - Analyse Vision Gating
        - Analyse extractions Vision GPT-4o
        - Analyse OSMOSE (concepts, relations)
        - Score de qualité
    """
    try:
        analytics = service.get_analytics(file_hash)

        if not analytics:
            raise HTTPException(
                status_code=404,
                detail=f"Import not found: {file_hash}",
            )

        return ImportAnalyticsResponse(**analytics.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Analytics] Error getting analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/imports/{file_hash}/pages/{page_index}")
async def get_page_details(
    file_hash: str,
    page_index: int,
    service: ImportAnalyticsService = Depends(get_analytics_service),
):
    """
    Récupère les détails d'une page spécifique.

    Utile pour comparer visuellement le PDF vs l'extraction.
    """
    # TODO: Implémenter la récupération des détails d'une page
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/imports/{file_hash}/compare")
async def compare_extraction(
    file_hash: str,
    page_indices: str = "0,1,2",  # Comma-separated
    service: ImportAnalyticsService = Depends(get_analytics_service),
):
    """
    Compare l'extraction avec le contenu original.

    Retourne le texte extrait pour les pages spécifiées,
    permettant une comparaison visuelle avec le PDF.
    """
    # TODO: Implémenter la comparaison
    raise HTTPException(status_code=501, detail="Not implemented yet")


# === Pass 2 Quality Endpoints ===

class DensityMetricsResponse(BaseModel):
    """Métriques de densité."""
    segments_total: int
    segments_processed: int
    coverage_pct: float
    raw_relations: int
    unique_relations: int
    dup_ratio: float
    relations_per_segment: float


class VaguenessMetricsResponse(BaseModel):
    """Métriques de relations vagues."""
    total_relations: int
    vague_relations: int
    vague_pct: float
    vague_types: Dict[str, int] = Field(default_factory=dict)


class HubNodeResponse(BaseModel):
    """Noeud hub."""
    node: str
    degree: int


class HubMetricsResponse(BaseModel):
    """Métriques de concentration."""
    total_edges: int
    top1_node: str
    top1_degree: int
    top1_degree_share: float
    top10_degree_share: float
    top10_nodes: List[HubNodeResponse] = Field(default_factory=list)


class ProblematicPairResponse(BaseModel):
    """Paire problématique."""
    a: str
    b: str
    type: str


class CycleMetricsResponse(BaseModel):
    """Métriques de cycles."""
    symmetric_pairs: int
    symmetric_ratio: float
    short_cycles_3: int
    problematic_pairs: List[ProblematicPairResponse] = Field(default_factory=list)


class QualityReportResponse(BaseModel):
    """Rapport de qualité Pass 2."""
    document_id: str
    verdict: str
    verdict_reasons: List[str]
    quality_score: float
    density: DensityMetricsResponse
    vagueness: VaguenessMetricsResponse
    hubs: HubMetricsResponse
    cycles: CycleMetricsResponse
    flags: Dict[str, bool] = Field(default_factory=dict)


class CorpusQualityResponse(BaseModel):
    """Qualité globale du corpus."""
    status: str
    documents_count: int = 0
    total_unique_relations: int = 0
    avg_coverage_pct: float = 0.0
    avg_vague_pct: float = 0.0
    verdicts_distribution: Dict[str, int] = Field(default_factory=dict)
    documents: List[Dict[str, Any]] = Field(default_factory=list)


def get_quality_service() -> Pass2QualityService:
    """Dependency injection pour le service qualité."""
    import os
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
        neo4j_client = get_neo4j_client(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
        )
    except Exception as e:
        logger.warning(f"[Analytics] Neo4j connection failed for quality: {e}")
        neo4j_client = None

    return Pass2QualityService(
        neo4j_client=neo4j_client,
        tenant_id="default",
    )


@router.get("/quality/corpus", response_model=CorpusQualityResponse)
async def get_corpus_quality(
    service: Pass2QualityService = Depends(get_quality_service),
):
    """
    Analyse la qualité globale du corpus Pass 2.

    Retourne:
    - Métriques agrégées sur tous les documents
    - Distribution des verdicts (OK, TOO_PERMISSIVE, TOO_RESTRICTIVE)
    - Détails par document
    """
    try:
        result = service.analyze_corpus()
        return CorpusQualityResponse(**result)
    except Exception as e:
        logger.error(f"[Analytics] Error analyzing corpus quality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quality/{document_id}", response_model=QualityReportResponse)
async def get_document_quality(
    document_id: str,
    service: Pass2QualityService = Depends(get_quality_service),
):
    """
    Analyse la qualité Pass 2 pour un document spécifique.

    Métriques incluses:
    - Densité: couverture, relations/segment, taux de déduplication
    - Vagueness: pourcentage de relations vagues (associated_with, etc.)
    - Hubs: concentration des degrés (détection de "hub explosion")
    - Cycles: paires symétriques, cycles courts

    Verdict automatique:
    - OK: métriques dans les normes
    - TOO_PERMISSIVE: trop de bruit détecté
    - TOO_RESTRICTIVE: couverture insuffisante
    """
    try:
        report = service.analyze_document(document_id)

        if not report:
            raise HTTPException(
                status_code=404,
                detail=f"No quality data for document: {document_id}",
            )

        return QualityReportResponse(**report.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Analytics] Error getting document quality: {e}")
        raise HTTPException(status_code=500, detail=str(e))
