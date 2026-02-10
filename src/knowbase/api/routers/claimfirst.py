# src/knowbase/api/routers/claimfirst.py
"""
Router API pour le pipeline Claim-First (Pivot Épistémique).

Endpoints:
- GET /api/claimfirst/status - Statut du pipeline
- POST /api/claimfirst/jobs - Lancer un job Claim-First
- GET /api/claimfirst/jobs/{job_id} - Statut d'un job
- DELETE /api/claimfirst/jobs/{job_id} - Annuler un job
- GET /api/claimfirst/documents - Documents disponibles pour traitement
- GET /api/claimfirst/stats - Statistiques Neo4j du pipeline

Author: Claude Code
Date: 2026-02-03
"""

import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from knowbase.api.dependencies import require_admin, get_tenant_id
from knowbase.config.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/claimfirst",
    tags=["claimfirst"],
    responses={404: {"description": "Not found"}}
)


# =============================================================================
# Schemas
# =============================================================================

class ClaimFirstStatusResponse(BaseModel):
    """Statut global du pipeline Claim-First."""
    # Neo4j counts (Passage retiré — Chantier 0 Phase 1A)
    claims: int = 0
    entities: int = 0
    facets: int = 0
    clusters: int = 0

    # Subject Resolution (INV-8, INV-9)
    doc_contexts: int = 0
    subject_anchors: int = 0

    # Relations (SUPPORTED_BY retiré — Chantier 0 Phase 1A)
    about: int = 0
    has_facet: int = 0
    in_cluster: int = 0
    contradicts: int = 0
    refines: int = 0
    qualifies: int = 0
    about_subject: int = 0  # DocumentContext → SubjectAnchor

    # Documents
    documents_available: int = 0
    documents_processed: int = 0

    # Job status
    job_running: bool = False
    current_job_id: Optional[str] = None
    current_phase: Optional[str] = None


class ClaimFirstJobRequest(BaseModel):
    """Requête pour créer un job Claim-First."""
    doc_ids: List[str] = Field(
        ...,
        description="Liste des document IDs à traiter"
    )
    cache_dir: str = Field(
        default="/data/extraction_cache",
        description="Répertoire du cache d'extraction"
    )


class ClaimFirstJobResponse(BaseModel):
    """Réponse création/statut job."""
    job_id: str
    status: str
    phase: Optional[str] = None
    current_document: Optional[str] = None
    processed: int = 0
    total: int = 0
    errors: List[str] = []
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class AvailableDocument(BaseModel):
    """Document disponible pour traitement."""
    doc_id: str
    filename: str
    cached_at: Optional[str] = None


class ClaimFirstStatsResponse(BaseModel):
    """Statistiques détaillées du pipeline."""
    # Counts par type
    node_counts: Dict[str, int] = {}
    relation_counts: Dict[str, int] = {}

    # Distribution
    claims_by_type: Dict[str, int] = {}
    entities_by_type: Dict[str, int] = {}
    facets_by_kind: Dict[str, int] = {}

    # Quality metrics
    avg_claim_confidence: float = 0.0
    claims_with_units: int = 0
    claims_total: int = 0


# =============================================================================
# Temporal Query Schemas (Applicability Axis)
# =============================================================================

class TemporalQueryRequest(BaseModel):
    """Requête temporelle (since when, still applicable)."""
    query_type: str = Field(
        ...,
        description="Type: 'since_when' | 'still_applicable' | 'compare'"
    )
    capability: Optional[str] = Field(
        default=None,
        description="Capability recherchée (pour since_when)"
    )
    claim_id: Optional[str] = Field(
        default=None,
        description="Claim ID (pour still_applicable)"
    )
    context_a: Optional[str] = Field(
        default=None,
        description="Premier contexte (pour compare)"
    )
    context_b: Optional[str] = Field(
        default=None,
        description="Deuxième contexte (pour compare)"
    )
    axis_key: str = Field(
        default="release_id",
        description="Clé de l'axe pour l'ordre"
    )


class TemporalQueryResponse(BaseModel):
    """Réponse à une requête temporelle."""
    query_type: str
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class TextValidationRequest(BaseModel):
    """Requête de validation de texte."""
    user_statement: str = Field(
        ...,
        min_length=10,
        description="Texte à valider contre le corpus"
    )
    target_context: Optional[str] = Field(
        default=None,
        description="Contexte cible (ex: '2023')"
    )
    subject_filter: Optional[str] = Field(
        default=None,
        description="Filtre sur le sujet"
    )


class TextValidationResponse(BaseModel):
    """Réponse de validation de texte."""
    status: str = Field(
        ...,
        description="CONFIRMED | INCORRECT | UNCERTAIN | NOT_DOCUMENTED"
    )
    confidence: float
    supporting_claims: List[Dict[str, Any]] = []
    contradicting_claims: List[Dict[str, Any]] = []
    explanation: str


class AxisInfo(BaseModel):
    """Informations sur un axe d'applicabilité."""
    axis_id: str
    axis_key: str
    axis_display_name: Optional[str] = None
    is_orderable: bool
    ordering_confidence: str
    known_values: List[str] = []
    doc_count: int = 0


# =============================================================================
# Endpoints
# =============================================================================

@router.get(
    "/status",
    response_model=ClaimFirstStatusResponse,
    summary="Statut du pipeline Claim-First",
    description="""
    Récupère le statut global du pipeline Claim-First.

    Affiche:
    - Nombre de nœuds par type (Passage, Claim, Entity, Facet, ClaimCluster)
    - Nombre de relations
    - Documents disponibles vs traités
    - Statut du job en cours
    """
)
async def get_claimfirst_status(
    tenant_id: str = Depends(get_tenant_id),
) -> ClaimFirstStatusResponse:
    """Récupère le statut du pipeline Claim-First."""
    import os
    from neo4j import GraphDatabase

    response = ClaimFirstStatusResponse()

    # Get Neo4j stats
    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            # Node counts - Claim-First specific labels
            # Note: Passage retiré (Chantier 0 Phase 1A)
            node_queries = {
                "claims": "MATCH (n:Claim {tenant_id: $tid}) RETURN count(n) as c",
                "entities": "MATCH (n:EntityClaimFirst {tenant_id: $tid}) RETURN count(n) as c",
                "facets": "MATCH (n:Facet {tenant_id: $tid}) RETURN count(n) as c",
                "clusters": "MATCH (n:ClaimCluster {tenant_id: $tid}) RETURN count(n) as c",
                # Subject Resolution (INV-8, INV-9)
                "doc_contexts": "MATCH (n:DocumentContext {tenant_id: $tid}) RETURN count(n) as c",
                "subject_anchors": "MATCH (n:SubjectAnchor) RETURN count(n) as c",
            }

            for key, query in node_queries.items():
                try:
                    result = session.run(query, tid=tenant_id)
                    record = result.single()
                    setattr(response, key, record["c"] if record else 0)
                except Exception:
                    pass

            # Relation counts (SUPPORTED_BY retiré — Chantier 0 Phase 1A)
            rel_queries = {
                "about": "MATCH (:Claim)-[r:ABOUT]->(:EntityClaimFirst) RETURN count(r) as c",
                "has_facet": "MATCH (:Claim)-[r:HAS_FACET]->(:Facet) RETURN count(r) as c",
                "in_cluster": "MATCH (:Claim)-[r:IN_CLUSTER]->(:ClaimCluster) RETURN count(r) as c",
                "contradicts": "MATCH (:Claim)-[r:CONTRADICTS]->(:Claim) RETURN count(r) as c",
                "refines": "MATCH (:Claim)-[r:REFINES]->(:Claim) RETURN count(r) as c",
                "qualifies": "MATCH (:Claim)-[r:QUALIFIES]->(:Claim) RETURN count(r) as c",
                # Subject Resolution (INV-8)
                "about_subject": "MATCH (:DocumentContext)-[r:ABOUT_SUBJECT]->(:SubjectAnchor) RETURN count(r) as c",
            }

            for key, query in rel_queries.items():
                try:
                    result = session.run(query)
                    record = result.single()
                    setattr(response, key, record["c"] if record else 0)
                except Exception:
                    pass

        driver.close()

    except Exception as e:
        logger.warning(f"[ClaimFirst] Neo4j query failed: {e}")

    # Count available documents in cache using cache_loader
    try:
        from knowbase.stratified.pass0.cache_loader import list_cached_documents
        cached_docs = list_cached_documents("/data/extraction_cache")
        response.documents_available = len(cached_docs)
    except Exception:
        # Fallback to glob count
        cache_dir = Path("/data/extraction_cache")
        if cache_dir.exists():
            cache_files = list(cache_dir.glob("*.knowcache.json"))
            cache_files.extend(cache_dir.glob("*.v5cache.json"))
            response.documents_available = len(cache_files)

    # Get job status
    try:
        from knowbase.ingestion.queue.dispatcher import get_claimfirst_status
        job_status = get_claimfirst_status()
        if job_status:
            response.job_running = job_status.get("status") == "running"
            response.current_job_id = job_status.get("job_id")
            response.current_phase = job_status.get("phase")
    except Exception:
        pass

    return response


@router.get(
    "/documents",
    summary="Documents disponibles pour traitement",
    description="""
    Liste les documents disponibles dans le cache d'extraction.

    Ces documents ont été extraits par Pass 0 et sont prêts pour
    le traitement Claim-First.
    """
)
async def list_available_documents(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=100, ge=1, le=500),
) -> Dict[str, Any]:
    """Liste les documents disponibles pour traitement."""
    import json
    import re
    from datetime import datetime

    cache_dir = Path("/data/extraction_cache")
    documents = []

    if cache_dir.exists():
        # Support both .knowcache.json (legacy) and .v5cache.json (burst mode)
        all_cache_files = list(cache_dir.glob("*.knowcache.json"))
        all_cache_files.extend(cache_dir.glob("*.v5cache.json"))

        cache_files = sorted(
            all_cache_files,
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )[:limit]

        for cache_file in cache_files:
            # Extract document_id from JSON content (consistent with cache_loader)
            doc_id = None
            filename = None
            cached_at = None

            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    # Read first 5KB for metadata (like cache_loader does)
                    content = f.read(5000)

                # Extract document_id from JSON content
                doc_id_match = re.search(r'"document_id":\s*"([^"]+)"', content)
                if doc_id_match:
                    doc_id = doc_id_match.group(1)

                # Try to extract source filename
                source_match = re.search(r'"source_path":\s*"([^"]+)"', content)
                if source_match:
                    source_path = source_match.group(1)
                    filename = Path(source_path).name
                elif doc_id:
                    filename = doc_id

                cached_at = datetime.fromtimestamp(
                    cache_file.stat().st_mtime
                ).isoformat()

            except Exception:
                pass

            # Fallback: use filename-based doc_id if not found in content
            if not doc_id:
                doc_id = cache_file.stem.replace(".knowcache", "").replace(".v5cache", "")
                filename = doc_id

            documents.append({
                "doc_id": doc_id,
                "filename": filename or doc_id,
                "cached_at": cached_at,
                "cache_file": cache_file.name,  # Include for reference
            })

    return {
        "count": len(documents),
        "documents": documents,
    }


@router.get(
    "/imported-doc-ids",
    summary="Doc IDs déjà importés dans le KG",
    description="Retourne les doc_ids ayant des Claims dans Neo4j, avec le nombre de claims par document.",
)
async def get_imported_doc_ids(
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """Retourne les doc_ids déjà importés via ClaimFirst."""
    import os
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})
                WHERE c.doc_id IS NOT NULL
                RETURN c.doc_id AS doc_id, count(c) AS claim_count
                ORDER BY claim_count DESC
                """,
                tid=tenant_id,
            )
            imported = {r["doc_id"]: r["claim_count"] for r in result}
    finally:
        driver.close()

    return {
        "imported": imported,
        "count": len(imported),
    }


@router.post(
    "/jobs",
    response_model=ClaimFirstJobResponse,
    summary="Lancer un job Claim-First",
    description="""
    Lance un job Claim-First en background.

    Le job traite les documents spécifiés avec le pipeline Claim-First:
    1. Charge le cache Pass 0
    2. Extrait les Claims (pointer mode, verbatim garanti)
    3. Extrait les Entities (patterns déterministes)
    4. Matche les Facets
    5. Link Passage→Claim, Claim→Entity, Claim→Facet
    6. Cluster les Claims similaires
    7. Détecte les relations CONTRADICTS/REFINES/QUALIFIES
    8. Persiste dans Neo4j

    **Prérequis**: Les documents doivent être dans le cache d'extraction.
    """
)
async def create_claimfirst_job(
    request: ClaimFirstJobRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> ClaimFirstJobResponse:
    """Crée un job Claim-First."""
    from knowbase.ingestion.queue.dispatcher import enqueue_claimfirst_process
    from knowbase.stratified.pass0.cache_loader import list_cached_documents

    if not request.doc_ids:
        raise HTTPException(status_code=400, detail="doc_ids ne peut pas être vide")

    # Build mapping of document_id -> cache info using cache_loader
    # (handles both .knowcache.json and .v5cache.json)
    cached_docs = list_cached_documents(request.cache_dir)
    available_doc_ids = {doc["document_id"] for doc in cached_docs}

    # Verify requested documents exist in cache
    missing = [doc_id for doc_id in request.doc_ids if doc_id not in available_doc_ids]

    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Documents non trouvés dans le cache: {', '.join(missing)}"
        )

    logger.info(
        f"[ClaimFirst] Job créé par {admin.get('email', 'admin')}: "
        f"{len(request.doc_ids)} documents"
    )

    # Enqueue the job
    job = enqueue_claimfirst_process(
        doc_ids=request.doc_ids,
        tenant_id=tenant_id,
        cache_dir=request.cache_dir,
    )

    return ClaimFirstJobResponse(
        job_id=job.id,
        status="queued",
        total=len(request.doc_ids),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=ClaimFirstJobResponse,
    summary="Statut d'un job Claim-First",
    description="Récupère le statut détaillé d'un job en cours ou terminé."
)
async def get_claimfirst_job(
    job_id: str,
    admin: dict = Depends(require_admin),
) -> ClaimFirstJobResponse:
    """Récupère le statut d'un job Claim-First."""
    from knowbase.ingestion.queue.dispatcher import fetch_job, get_claimfirst_status

    # Get RQ job status
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} non trouvé")

    # Get detailed status from Redis
    status = get_claimfirst_status()

    response = ClaimFirstJobResponse(
        job_id=job_id,
        status=job.get_status(),
    )

    if status and status.get("job_id") == job_id:
        response.phase = status.get("phase")
        response.current_document = status.get("current_document")
        response.processed = status.get("processed", 0)
        response.total = status.get("total", 0)
        response.errors = status.get("errors", [])

    # Timestamps
    if job.started_at:
        response.started_at = job.started_at.isoformat()
    if job.ended_at:
        response.completed_at = job.ended_at.isoformat()

    return response


@router.delete(
    "/jobs/{job_id}",
    summary="Annuler un job Claim-First",
    description="Annule un job en cours d'exécution."
)
async def cancel_claimfirst_job(
    job_id: str,
    admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Annule un job Claim-First."""
    from knowbase.ingestion.queue.dispatcher import fetch_job
    from knowbase.claimfirst.worker_job import cancel_claimfirst_job as _cancel

    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} non trouvé")

    status = job.get_status()
    if status in ("finished", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Impossible d'annuler un job {status}"
        )

    # Cancel the job
    success = _cancel(job_id)

    if not success:
        raise HTTPException(status_code=500, detail="Échec de l'annulation")

    logger.info(f"[ClaimFirst] Job {job_id} annulé par {admin.get('email', 'admin')}")

    return {
        "success": True,
        "job_id": job_id,
        "message": "Job annulé",
    }


@router.get(
    "/stats",
    response_model=ClaimFirstStatsResponse,
    summary="Statistiques détaillées Claim-First",
    description="""
    Récupère des statistiques détaillées du pipeline Claim-First.

    Inclut:
    - Distribution des Claims par type (FACTUAL, PRESCRIPTIVE, etc.)
    - Distribution des Entities par type (PRODUCT, SERVICE, etc.)
    - Distribution des Facets par kind (DOMAIN, RISK, etc.)
    - Métriques de qualité (confiance moyenne, claims avec units)
    """
)
async def get_claimfirst_stats(
    tenant_id: str = Depends(get_tenant_id),
    admin: dict = Depends(require_admin),
) -> ClaimFirstStatsResponse:
    """Récupère les statistiques détaillées."""
    import os
    from neo4j import GraphDatabase

    response = ClaimFirstStatsResponse()

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            # Node counts (Passage retiré — Chantier 0 Phase 1A)
            node_labels = ["Claim", "EntityClaimFirst", "Facet", "ClaimCluster"]
            for label in node_labels:
                query = f"MATCH (n:{label} {{tenant_id: $tid}}) RETURN count(n) as c"
                try:
                    result = session.run(query, tid=tenant_id)
                    record = result.single()
                    response.node_counts[label] = record["c"] if record else 0
                except Exception:
                    response.node_counts[label] = 0

            # Relation counts (SUPPORTED_BY retiré — Chantier 0 Phase 1A)
            rel_types = ["ABOUT", "HAS_FACET", "IN_CLUSTER",
                        "CONTRADICTS", "REFINES", "QUALIFIES"]
            for rel_type in rel_types:
                query = f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as c"
                try:
                    result = session.run(query)
                    record = result.single()
                    response.relation_counts[rel_type] = record["c"] if record else 0
                except Exception:
                    response.relation_counts[rel_type] = 0

            # Claims by type
            try:
                result = session.run("""
                    MATCH (c:Claim {tenant_id: $tid})
                    RETURN c.claim_type as type, count(c) as cnt
                """, tid=tenant_id)
                for record in result:
                    response.claims_by_type[record["type"] or "UNKNOWN"] = record["cnt"]
            except Exception:
                pass

            # Entities by type
            try:
                result = session.run("""
                    MATCH (e:EntityClaimFirst {tenant_id: $tid})
                    RETURN e.entity_type as type, count(e) as cnt
                """, tid=tenant_id)
                for record in result:
                    response.entities_by_type[record["type"] or "OTHER"] = record["cnt"]
            except Exception:
                pass

            # Facets by kind
            try:
                result = session.run("""
                    MATCH (f:Facet {tenant_id: $tid})
                    RETURN f.facet_kind as kind, count(f) as cnt
                """, tid=tenant_id)
                for record in result:
                    response.facets_by_kind[record["kind"] or "UNKNOWN"] = record["cnt"]
            except Exception:
                pass

            # Quality metrics
            try:
                result = session.run("""
                    MATCH (c:Claim {tenant_id: $tid})
                    RETURN
                        avg(c.confidence) as avg_conf,
                        sum(CASE WHEN size(c.unit_ids) > 0 THEN 1 ELSE 0 END) as with_units,
                        count(c) as total
                """, tid=tenant_id)
                record = result.single()
                if record:
                    response.avg_claim_confidence = round(record["avg_conf"] or 0, 3)
                    response.claims_with_units = record["with_units"] or 0
                    response.claims_total = record["total"] or 0
            except Exception:
                pass

        driver.close()

    except Exception as e:
        logger.warning(f"[ClaimFirst] Stats query failed: {e}")

    return response


@router.post(
    "/process-all",
    response_model=ClaimFirstJobResponse,
    summary="Traiter tous les documents disponibles",
    description="""
    Lance un job Claim-First pour TOUS les documents du cache.

    **Attention**: Cette opération peut prendre beaucoup de temps
    si le cache contient de nombreux documents.
    """
)
async def process_all_documents(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> ClaimFirstJobResponse:
    """Traite tous les documents disponibles."""
    from knowbase.ingestion.queue.dispatcher import enqueue_claimfirst_process
    from knowbase.stratified.pass0.cache_loader import list_cached_documents

    cache_dir = "/data/extraction_cache"
    if not Path(cache_dir).exists():
        raise HTTPException(status_code=400, detail="Cache d'extraction introuvable")

    # Get all doc_ids from cache using cache_loader (reads document_id from JSON content)
    cached_docs = list_cached_documents(cache_dir)
    if not cached_docs:
        raise HTTPException(status_code=400, detail="Aucun document dans le cache")

    doc_ids = [doc["document_id"] for doc in cached_docs if doc.get("document_id")]

    logger.info(
        f"[ClaimFirst] Process-all lancé par {admin.get('email', 'admin')}: "
        f"{len(doc_ids)} documents"
    )

    job = enqueue_claimfirst_process(
        doc_ids=doc_ids,
        tenant_id=tenant_id,
    )

    return ClaimFirstJobResponse(
        job_id=job.id,
        status="queued",
        total=len(doc_ids),
    )


# =============================================================================
# Temporal Query Endpoints (Applicability Axis)
# =============================================================================

@router.post(
    "/query/temporal",
    response_model=TemporalQueryResponse,
    summary="Requête temporelle (Since when? / Still applicable?)",
    description="""
    Exécute une requête temporelle sur le corpus de claims.

    Types de requêtes:
    - **since_when**: Depuis quand cette capability existe?
    - **still_applicable**: Cette claim est-elle encore applicable?
    - **compare**: Différences entre contextes A et B?

    INV-19: Timeline refusée si ClaimKey non validé.
    INV-23: Toute réponse cite ses claims sources.
    """
)
async def temporal_query(
    request: TemporalQueryRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> TemporalQueryResponse:
    """Exécute une requête temporelle."""
    import os
    from neo4j import GraphDatabase

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        from knowbase.claimfirst.query.temporal_query_engine import TemporalQueryEngine

        engine = TemporalQueryEngine(
            neo4j_driver=driver,
            tenant_id=tenant_id,
        )

        result: Dict[str, Any] = {}

        if request.query_type == "since_when":
            if not request.capability:
                raise HTTPException(400, "capability required for since_when")

            since_result = engine.query_since_when(
                capability=request.capability,
                axis_key=request.axis_key,
            )
            result = since_result.model_dump()

        elif request.query_type == "still_applicable":
            if not request.claim_id:
                raise HTTPException(400, "claim_id required for still_applicable")

            # Charger la claim
            with driver.session() as session:
                claim_result = session.run(
                    "MATCH (c:Claim {claim_id: $claim_id}) RETURN c.text as text",
                    claim_id=request.claim_id,
                )
                record = claim_result.single()
                if not record:
                    raise HTTPException(404, f"Claim {request.claim_id} not found")
                claim_text = record["text"]

            still_result = engine.query_still_applicable(
                claim_id=request.claim_id,
                claim_text=claim_text,
                axes={},  # Charger les axes depuis Neo4j si nécessaire
            )
            result = still_result.model_dump()

        elif request.query_type == "compare":
            if not request.context_a or not request.context_b:
                raise HTTPException(400, "context_a and context_b required for compare")

            compare_result = engine.compare_contexts(
                context_a=request.context_a,
                context_b=request.context_b,
                axis_key=request.axis_key,
            )
            result = compare_result

        else:
            raise HTTPException(400, f"Unknown query_type: {request.query_type}")

        driver.close()

        return TemporalQueryResponse(
            query_type=request.query_type,
            success=True,
            result=result,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ClaimFirst] Temporal query failed: {e}")
        return TemporalQueryResponse(
            query_type=request.query_type,
            success=False,
            error=str(e),
        )


@router.post(
    "/validate",
    response_model=TextValidationResponse,
    summary="Valider un texte contre le corpus",
    description="""
    Valide un texte utilisateur contre le corpus de claims.

    Retourne:
    - **CONFIRMED**: Le texte est supporté par des claims
    - **INCORRECT**: Le texte contredit des claims
    - **UNCERTAIN**: Pas assez d'évidence
    - **NOT_DOCUMENTED**: Sujet non documenté

    INV-23: Cite explicitement les claims sources.
    """
)
async def validate_text(
    request: TextValidationRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> TextValidationResponse:
    """Valide un texte contre le corpus."""
    import os
    from neo4j import GraphDatabase

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        from knowbase.claimfirst.query.text_validator import TextValidator

        validator = TextValidator(
            neo4j_driver=driver,
            tenant_id=tenant_id,
        )

        result = validator.validate(
            user_statement=request.user_statement,
            target_context=request.target_context,
            subject_filter=request.subject_filter,
        )

        driver.close()

        return TextValidationResponse(
            status=result.status.value,
            confidence=result.confidence,
            supporting_claims=result.supporting_claims,
            contradicting_claims=result.contradicting_claims,
            explanation=result.explanation,
        )

    except Exception as e:
        logger.error(f"[ClaimFirst] Text validation failed: {e}")
        return TextValidationResponse(
            status="UNCERTAIN",
            confidence=0.0,
            explanation=f"Validation error: {e}",
        )


@router.get(
    "/axes",
    response_model=List[AxisInfo],
    summary="Liste des axes d'applicabilité détectés",
    description="""
    Retourne tous les axes d'applicabilité détectés dans le corpus.

    Chaque axe contient:
    - axis_key: Clé neutre (release_id, year, etc.)
    - ordering_confidence: CERTAIN, INFERRED, ou UNKNOWN
    - known_values: Valeurs détectées
    """
)
async def list_axes(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=50, ge=1, le=200),
) -> List[AxisInfo]:
    """Liste les axes d'applicabilité détectés."""
    import os
    from neo4j import GraphDatabase

    axes = []

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            result = session.run(
                """
                MATCH (ax:ApplicabilityAxis {tenant_id: $tenant_id})
                RETURN ax
                ORDER BY ax.doc_count DESC
                LIMIT $limit
                """,
                tenant_id=tenant_id,
                limit=limit,
            )

            for record in result:
                ax = record["ax"]
                axes.append(AxisInfo(
                    axis_id=ax.get("axis_id"),
                    axis_key=ax.get("axis_key"),
                    axis_display_name=ax.get("axis_display_name"),
                    is_orderable=ax.get("is_orderable", False),
                    ordering_confidence=ax.get("ordering_confidence", "unknown"),
                    known_values=ax.get("known_values") or [],
                    doc_count=ax.get("doc_count", 0),
                ))

        driver.close()

    except Exception as e:
        logger.warning(f"[ClaimFirst] Axes query failed: {e}")

    return axes


@router.post(
    "/archive-isolated",
    summary="Archiver les claims isolées",
    description="""
    Identifie et archive les claims sans relations structurantes
    (pas de CHAINS_TO, ABOUT, REFINES, QUALIFIES, CONTRADICTS)
    et sans structured_form.

    Mode dry-run par défaut. Passer execute=true pour archiver.

    Chantier 0 - Phase 1B.
    """
)
async def archive_isolated_claims(
    execute: bool = Query(default=False, description="Exécuter l'archivage (sinon dry-run)"),
    tenant_id: str = Depends(get_tenant_id),
    admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Archive les claims isolées."""
    import os
    from neo4j import GraphDatabase

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            # Compter claims totales
            result = session.run(
                "MATCH (c:Claim {tenant_id: $tid}) RETURN count(c) AS c",
                tid=tenant_id,
            )
            total_claims = result.single()["c"]

            # Identifier les claims isolées
            result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})
                WHERE c.structured_form_json IS NULL
                  AND NOT EXISTS { (c)-[:CHAINS_TO]->() }
                  AND NOT EXISTS { ()-[:CHAINS_TO]->(c) }
                  AND NOT EXISTS { (c)-[:ABOUT]->() }
                  AND NOT EXISTS { (c)-[:REFINES]->() }
                  AND NOT EXISTS { ()-[:REFINES]->(c) }
                  AND NOT EXISTS { (c)-[:QUALIFIES]->() }
                  AND NOT EXISTS { ()-[:QUALIFIES]->(c) }
                  AND NOT EXISTS { (c)-[:CONTRADICTS]->() }
                  AND NOT EXISTS { ()-[:CONTRADICTS]->(c) }
                RETURN c.claim_id AS claim_id
                """,
                tid=tenant_id,
            )
            isolated_ids = [r["claim_id"] for r in result]

            if not execute:
                driver.close()
                return {
                    "mode": "dry-run",
                    "total_claims": total_claims,
                    "isolated_count": len(isolated_ids),
                    "isolated_percentage": round(100 * len(isolated_ids) / total_claims, 1) if total_claims else 0,
                    "message": f"{len(isolated_ids)} claims isolées détectées. Relancer avec execute=true pour archiver.",
                }

            # Archiver par batch
            archived = 0
            batch_size = 500
            for i in range(0, len(isolated_ids), batch_size):
                batch = isolated_ids[i:i + batch_size]
                result = session.run(
                    """
                    UNWIND $ids AS cid
                    MATCH (c:Claim {claim_id: cid, tenant_id: $tid})
                    SET c.archived = true,
                        c.archived_at = datetime(),
                        c.archived_reason = 'isolated_claim_phase0'
                    RETURN count(c) AS archived
                    """,
                    ids=batch,
                    tid=tenant_id,
                )
                archived += result.single()["archived"]

            # Vérification
            result = session.run(
                "MATCH (c:Claim {tenant_id: $tid, archived: true}) RETURN count(c) AS c",
                tid=tenant_id,
            )
            total_archived = result.single()["c"]

        driver.close()

        logger.info(
            f"[ClaimFirst] Archivage: {archived} claims archivées par {admin.get('email', 'admin')}"
        )

        return {
            "mode": "execute",
            "total_claims": total_claims,
            "newly_archived": archived,
            "total_archived": total_archived,
            "message": f"{archived} claims isolées archivées avec succès.",
        }

    except Exception as e:
        logger.error(f"[ClaimFirst] Archive failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/detect-cross-doc",
    summary="Détecter les chaînes cross-document",
    description="""
    Détecte les chaînes CHAINS_TO entre claims de documents différents
    en joignant par entity (object→subject via S/P/O).

    Mode dry-run par défaut. Passer execute=true pour persister.

    Doit être exécuté après l'import de tous les documents.
    """
)
async def detect_cross_doc_chains(
    execute: bool = Query(default=False, description="Persister les chaînes (sinon dry-run)"),
    tenant_id: str = Depends(get_tenant_id),
    admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Détecte et persiste les chaînes cross-document."""
    import json
    import os
    from collections import defaultdict
    from neo4j import GraphDatabase

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            # 1. Charger claims avec structured_form
            result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})
                WHERE c.structured_form_json IS NOT NULL
                RETURN c.claim_id AS claim_id, c.doc_id AS doc_id,
                       c.structured_form_json AS sf_json, c.confidence AS confidence
                ORDER BY c.doc_id
                """,
                tid=tenant_id,
            )
            claims = []
            for r in result:
                try:
                    sf = json.loads(r["sf_json"])
                except (json.JSONDecodeError, TypeError):
                    continue
                claims.append({
                    "claim_id": r["claim_id"],
                    "doc_id": r["doc_id"],
                    "structured_form": sf,
                    "confidence": r["confidence"] or 0.5,
                })

            doc_ids = list({c["doc_id"] for c in claims})

            if len(doc_ids) < 2:
                driver.close()
                return {
                    "mode": "dry-run",
                    "claims_with_sf": len(claims),
                    "documents": len(doc_ids),
                    "chains_detected": 0,
                    "message": "Moins de 2 documents — pas de cross-doc possible.",
                }

            # 2. Entity index
            eidx_result = session.run(
                "MATCH (e:Entity {tenant_id: $tid}) RETURN e.normalized_name AS norm, e.entity_id AS eid",
                tid=tenant_id,
            )
            entity_index = {r["norm"]: r["eid"] for r in eidx_result if r["norm"]}

            # 3. Hub detection
            doc_count_r = session.run(
                "MATCH (c:Claim {tenant_id: $tid}) WHERE c.structured_form_json IS NOT NULL RETURN count(DISTINCT c.doc_id) AS td",
                tid=tenant_id,
            )
            total_docs = doc_count_r.single()["td"]

            hub_result = session.run(
                """
                MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim)
                WHERE c.structured_form_json IS NOT NULL
                WITH e, count(DISTINCT c.doc_id) AS nb_docs, count(c) AS nb_claims
                RETURN e.normalized_name AS name, nb_docs, nb_claims
                ORDER BY nb_claims DESC
                """,
                tid=tenant_id,
            )
            hub_entities = set()
            for r in hub_result:
                nb_claims = r["nb_claims"]
                nb_docs = r["nb_docs"]
                ratio = nb_claims / nb_docs if nb_docs > 0 else 0
                if nb_claims > 200 or (nb_docs >= total_docs and ratio > 150.0):
                    hub_entities.add(r["name"])

            # 4. Detect
            from knowbase.claimfirst.composition.chain_detector import ChainDetector

            idf_map = ChainDetector.compute_idf(claims, entity_index=entity_index)
            detector = ChainDetector()
            links = detector.detect_cross_doc(
                claims, hub_entities=hub_entities,
                entity_index=entity_index, idf_map=idf_map,
            )

            # Existing counts
            existing_cross = session.run(
                "MATCH (:Claim {tenant_id: $tid})-[r:CHAINS_TO {cross_doc: true}]->() RETURN count(r) AS c",
                tid=tenant_id,
            ).single()["c"]
            existing_intra = session.run(
                "MATCH (:Claim {tenant_id: $tid})-[r:CHAINS_TO]->() WHERE coalesce(r.cross_doc, false) = false RETURN count(r) AS c",
                tid=tenant_id,
            ).single()["c"]

            if not execute:
                driver.close()
                return {
                    "mode": "dry-run",
                    "claims_with_sf": len(claims),
                    "documents": len(doc_ids),
                    "chains_detected": len(links),
                    "hubs_excluded": len(hub_entities),
                    "existing_intra": existing_intra,
                    "existing_cross": existing_cross,
                    "message": f"{len(links)} chaînes cross-doc détectées. Relancer avec execute=true pour persister.",
                }

            # 5. Persist
            persisted = 0
            for link in links:
                jk_idf = idf_map.get(link.join_key, 0.0)
                r = session.run(
                    """
                    MATCH (c1:Claim {claim_id: $src, tenant_id: $tid})
                    MATCH (c2:Claim {claim_id: $tgt, tenant_id: $tid})
                    MERGE (c1)-[r:CHAINS_TO]->(c2)
                    SET r.confidence = 1.0,
                        r.basis = $basis,
                        r.join_key = $jk,
                        r.join_key_idf = $idf,
                        r.method = 'spo_join_cross_doc',
                        r.join_method = $jm,
                        r.derived = true,
                        r.cross_doc = true,
                        r.source_doc_id = $sdid,
                        r.target_doc_id = $tdid,
                        r.join_key_freq = $freq
                    RETURN r IS NOT NULL AS ok
                    """,
                    src=link.source_claim_id,
                    tgt=link.target_claim_id,
                    tid=tenant_id,
                    basis=f"join_key={link.join_key}",
                    jk=link.join_key,
                    idf=jk_idf,
                    jm=link.join_method,
                    sdid=link.source_doc_id,
                    tdid=link.target_doc_id,
                    freq=link.join_key_freq,
                )
                if r.single():
                    persisted += 1

            # Final counts
            final_cross = session.run(
                "MATCH (:Claim {tenant_id: $tid})-[r:CHAINS_TO {cross_doc: true}]->() RETURN count(r) AS c",
                tid=tenant_id,
            ).single()["c"]

        driver.close()

        logger.info(
            f"[ClaimFirst] Cross-doc: {persisted} chaînes créées par {admin.get('email', 'admin')}"
        )

        return {
            "mode": "execute",
            "claims_with_sf": len(claims),
            "documents": len(doc_ids),
            "chains_persisted": persisted,
            "total_cross_doc": final_cross,
            "total_intra_doc": existing_intra,
            "message": f"{persisted} chaînes cross-doc créées. Total: {final_cross} cross-doc + {existing_intra} intra-doc.",
        }

    except Exception as e:
        logger.error(f"[ClaimFirst] Cross-doc detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/canonicalize-entities",
    summary="Canonicaliser les entités existantes",
    description="""
    Fusionne les entités dupliquées dans Neo4j :
    - Variantes version : "S/4HANA 2023" → "S/4HANA"
    - Containment : "S4HANA" ⊂ "SAP S4HANA"
    - Annotation des hubs (entités avec >50 claims ABOUT)

    Mode dry-run par défaut. Passer execute=true pour appliquer.
    Doit être exécuté après l'import de tous les documents.
    """
)
async def canonicalize_entities(
    execute: bool = Query(default=False, description="Appliquer les fusions (sinon dry-run)"),
    hub_threshold: int = Query(default=50, description="Seuil de claims pour annoter un hub"),
    tenant_id: str = Depends(get_tenant_id),
    admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Canonicalise les entités existantes dans Neo4j."""
    import os
    from neo4j import GraphDatabase

    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        # Import inline pour éviter les dépendances circulaires
        from knowbase.claimfirst.models.entity import (
            Entity,
            strip_version_qualifier,
            is_valid_entity_name,
        )

        with driver.session() as session:
            # 1. Charger les entities
            result = session.run(
                """
                MATCH (e:Entity {tenant_id: $tid})
                OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
                WITH e, count(c) AS claim_count
                RETURN e.entity_id AS entity_id,
                       e.name AS name,
                       e.normalized_name AS normalized_name,
                       e.aliases AS aliases,
                       e.entity_type AS entity_type,
                       claim_count
                ORDER BY e.name
                """,
                tid=tenant_id,
            )
            entities = [dict(record) for record in result]

            if not entities:
                driver.close()
                return {
                    "mode": "dry-run",
                    "entities_initial": 0,
                    "version_merges": 0,
                    "containment_merges": 0,
                    "hubs_annotated": 0,
                    "message": "Aucune entité à traiter.",
                }

            # 2. Identifier les groupes version
            from collections import defaultdict
            groups: dict = defaultdict(list)
            for e in entities:
                base_name, version = strip_version_qualifier(e["name"])
                base_normalized = Entity.normalize(base_name)
                groups[base_normalized].append((e, version))

            version_groups = {}
            for base_norm, members in groups.items():
                if len(members) > 1:
                    version_groups[base_norm] = [m[0] for m in members]

            version_merge_count = sum(
                len(members) - 1
                for members in version_groups.values()
            )

            # 3. Identifier les containments
            by_norm: dict = {}
            for e in entities:
                norm = e.get("normalized_name") or Entity.normalize(e["name"])
                by_norm[norm] = e

            parents_by_child: dict = defaultdict(list)
            norms = sorted(by_norm.keys(), key=len)
            for i, short_norm in enumerate(norms):
                if len(short_norm) < 4:
                    continue
                for long_norm in norms[i + 1:]:
                    words_long = long_norm.split()
                    words_short = short_norm.split()
                    extra_words = len(words_long) - len(words_short)
                    if extra_words > 2 or extra_words < 1:
                        continue
                    if words_long[-len(words_short):] == words_short:
                        parents_by_child[short_norm].append(long_norm)

            containment_pairs = []
            for child_norm, parent_norms in parents_by_child.items():
                if len(parent_norms) == 1:
                    source = by_norm[child_norm]
                    target = by_norm[parent_norms[0]]
                    if is_valid_entity_name(source["name"]) and is_valid_entity_name(target["name"]):
                        containment_pairs.append((source, target))

            if not execute:
                driver.close()
                return {
                    "mode": "dry-run",
                    "entities_initial": len(entities),
                    "version_merges": version_merge_count,
                    "containment_merges": len(containment_pairs),
                    "total_merges": version_merge_count + len(containment_pairs),
                    "entities_after": len(entities) - version_merge_count - len(containment_pairs),
                    "message": (
                        f"{version_merge_count} fusions version + {len(containment_pairs)} fusions containment détectées. "
                        f"Relancer avec execute=true pour appliquer."
                    ),
                }

            # 4. Exécuter les fusions version
            version_merged = 0
            for base_norm, members in version_groups.items():
                canonical = None
                for m in members:
                    _, version = strip_version_qualifier(m["name"])
                    if version is None:
                        canonical = m
                        break
                if canonical is None:
                    canonical = max(members, key=lambda m: m["claim_count"])
                for m in members:
                    if m["entity_id"] != canonical["entity_id"]:
                        session.run(
                            """
                            MATCH (source:Entity {entity_id: $source_id, tenant_id: $tid})
                            MATCH (target:Entity {entity_id: $target_id, tenant_id: $tid})
                            OPTIONAL MATCH (c:Claim)-[r:ABOUT]->(source)
                            WITH source, target, collect(c) AS claims, collect(r) AS rels
                            FOREACH (r IN rels | DELETE r)
                            WITH source, target, claims
                            UNWIND claims AS c
                            MERGE (c)-[:ABOUT]->(target)
                            WITH source, target
                            SET target.aliases = CASE
                                WHEN target.aliases IS NULL THEN [source.name]
                                WHEN NOT source.name IN target.aliases THEN target.aliases + source.name
                                ELSE target.aliases
                            END
                            WITH source, target
                            DETACH DELETE source
                            """,
                            source_id=m["entity_id"],
                            target_id=canonical["entity_id"],
                            tid=tenant_id,
                        )
                        version_merged += 1

            # 5. Exécuter les fusions containment
            containment_merged = 0
            for source, target in containment_pairs:
                session.run(
                    """
                    MATCH (source:Entity {entity_id: $source_id, tenant_id: $tid})
                    MATCH (target:Entity {entity_id: $target_id, tenant_id: $tid})
                    OPTIONAL MATCH (c:Claim)-[r:ABOUT]->(source)
                    WITH source, target, collect(c) AS claims, collect(r) AS rels
                    FOREACH (r IN rels | DELETE r)
                    WITH source, target, claims
                    UNWIND claims AS c
                    MERGE (c)-[:ABOUT]->(target)
                    WITH source, target
                    SET target.aliases = CASE
                        WHEN target.aliases IS NULL THEN [source.name]
                        WHEN NOT source.name IN target.aliases THEN target.aliases + source.name
                        ELSE target.aliases
                    END
                    WITH source, target
                    DETACH DELETE source
                    """,
                    source_id=source["entity_id"],
                    target_id=target["entity_id"],
                    tid=tenant_id,
                )
                containment_merged += 1

            # 6. Annoter les hubs
            hub_result = session.run(
                """
                MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim)
                WITH e, count(c) AS degree
                WHERE degree > $threshold
                SET e.is_hub = true, e.hub_degree = degree
                RETURN count(e) AS hubs_annotated
                """,
                tid=tenant_id,
                threshold=hub_threshold,
            )
            hubs_annotated = hub_result.single()["hubs_annotated"]

            # Compter le résultat final
            final_count = session.run(
                "MATCH (e:Entity {tenant_id: $tid}) RETURN count(e) AS cnt",
                tid=tenant_id,
            ).single()["cnt"]

        driver.close()

        logger.info(
            f"[ClaimFirst] Canonicalization: {version_merged} version + {containment_merged} containment merges, "
            f"{hubs_annotated} hubs annotated by {admin.get('email', 'admin')}"
        )

        return {
            "mode": "execute",
            "entities_initial": len(entities),
            "version_merges": version_merged,
            "containment_merges": containment_merged,
            "total_merges": version_merged + containment_merged,
            "hubs_annotated": hubs_annotated,
            "entities_after": final_count,
            "message": (
                f"{version_merged + containment_merged} entités fusionnées "
                f"({version_merged} version, {containment_merged} containment), "
                f"{hubs_annotated} hubs annotés. {final_count} entités restantes."
            ),
        }

    except Exception as e:
        logger.error(f"[ClaimFirst] Canonicalization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
