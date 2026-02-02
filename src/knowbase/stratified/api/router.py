"""
OSMOSE Pipeline V2 - API Router
================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Endpoints API pour Pipeline V2:
- POST /v2/ingest - Déclenche Pass 0 + Pass 1
- POST /v2/enrich - Déclenche Pass 2
- POST /v2/consolidate - Déclenche Pass 3
- GET /v2/documents/{id}/graph - Retourne graphe sémantique
- GET /v2/documents/{id}/assertions - Retourne AssertionLog
- GET /v2/search - Recherche sur graphe V2
"""

import json
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["Pipeline V2"])


# ============================================================================
# REDIS STATE MANAGEMENT pour Progress Tracking
# ============================================================================

REPROCESS_STATE_KEY = "osmose:v2:reprocess:state"
REPROCESS_STATE_TTL = 3600  # 1 heure


def _get_redis_client():
    """Récupère le client Redis."""
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        return get_redis_client()
    except Exception as e:
        logger.warning(f"[OSMOSE:V2] Redis unavailable: {e}")
        return None


def _save_reprocess_state(state: dict) -> bool:
    """Sauvegarde l'état du reprocess dans Redis."""
    client = _get_redis_client()
    if not client:
        logger.warning("[OSMOSE:V2] Cannot save state: Redis client is None")
        return False
    if not client.is_connected():
        logger.warning("[OSMOSE:V2] Cannot save state: Redis not connected")
        return False
    try:
        client.client.setex(
            REPROCESS_STATE_KEY,
            REPROCESS_STATE_TTL,
            json.dumps(state)
        )
        logger.debug(f"[OSMOSE:V2] State saved to Redis: status={state.get('status')}")
        return True
    except Exception as e:
        logger.error(f"[OSMOSE:V2] Failed to save state to Redis: {e}")
        return False


def _load_reprocess_state() -> Optional[dict]:
    """Charge l'état du reprocess depuis Redis."""
    client = _get_redis_client()
    if client and client.is_connected():
        try:
            data = client.client.get(REPROCESS_STATE_KEY)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"[OSMOSE:V2] Failed to load state from Redis: {e}")
    return None


def _delete_reprocess_state() -> bool:
    """Supprime l'état du reprocess de Redis."""
    client = _get_redis_client()
    if client and client.is_connected():
        try:
            client.client.delete(REPROCESS_STATE_KEY)
            return True
        except Exception as e:
            logger.error(f"[OSMOSE:V2] Failed to delete state from Redis: {e}")
    return False


def _update_reprocess_state(**kwargs) -> bool:
    """
    Met à jour partiellement l'état du reprocess dans Redis.

    Args:
        **kwargs: Champs à mettre à jour (current_phase, progress_percent, etc.)

    Returns:
        True si succès
    """
    state = _load_reprocess_state()
    if state is None:
        state = {
            "status": "running",
            "total_documents": 0,
            "processed": 0,
            "failed": 0,
            "current_document": None,
            "current_phase": None,
            "progress_percent": 0.0,
            "started_at": datetime.utcnow().isoformat(),
            "errors": []
        }

    state.update(kwargs)
    return _save_reprocess_state(state)


def _is_reprocess_cancelled() -> bool:
    """Vérifie si le reprocess a été annulé."""
    state = _load_reprocess_state()
    return state is not None and state.get("status") == "cancelled"



# ============================================================================
# SCHEMAS
# ============================================================================

class IngestRequest(BaseModel):
    """Requête d'ingestion V2."""
    doc_id: str
    doc_title: str
    content: str
    source_url: Optional[str] = None
    run_pass2: bool = False  # Optionnel: enchaîner Pass 2


class IngestResponse(BaseModel):
    """Réponse d'ingestion V2."""
    doc_id: str
    status: str
    pass0_status: str
    pass1_status: str
    pass2_status: Optional[str] = None
    stats: dict = Field(default_factory=dict)


class EnrichRequest(BaseModel):
    """Requête d'enrichissement V2."""
    doc_id: str


class EnrichResponse(BaseModel):
    """Réponse d'enrichissement V2."""
    doc_id: str
    status: str
    relations_extracted: int = 0
    stats: dict = Field(default_factory=dict)


class ConsolidateRequest(BaseModel):
    """Requête de consolidation V2."""
    mode: str = "batch"  # batch ou incremental
    doc_id: Optional[str] = None  # Requis pour incremental
    tenant_id: Optional[str] = "default"


class ConsolidateResponse(BaseModel):
    """Réponse de consolidation V2."""
    status: str
    canonical_concepts: int = 0
    canonical_themes: int = 0
    stats: dict = Field(default_factory=dict)


class GraphNode(BaseModel):
    """Nœud du graphe sémantique."""
    id: str
    type: str
    name: str
    properties: dict = Field(default_factory=dict)


class GraphRelation(BaseModel):
    """Relation du graphe sémantique."""
    source: str
    target: str
    type: str
    properties: dict = Field(default_factory=dict)


class DocumentGraph(BaseModel):
    """Graphe sémantique d'un document."""
    doc_id: str
    nodes: List[GraphNode] = Field(default_factory=list)
    relations: List[GraphRelation] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)


class AssertionLogEntry(BaseModel):
    """Entrée du journal d'assertions."""
    assertion_id: str
    text: str
    type: str
    status: str
    reason: str
    confidence: Optional[float] = None
    concept_id: Optional[str] = None


class AssertionLogResponse(BaseModel):
    """Réponse du journal d'assertions."""
    doc_id: str
    entries: List[AssertionLogEntry] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)


class SearchRequest(BaseModel):
    """Requête de recherche V2."""
    query: str
    top_k: int = 10
    include_informations: bool = True


class SearchResult(BaseModel):
    """Résultat de recherche V2."""
    concept_id: str
    concept_name: str
    score: float
    informations: List[dict] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Réponse de recherche V2."""
    query: str
    results: List[SearchResult] = Field(default_factory=list)
    total: int = 0


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    request: IngestRequest,
    background_tasks: BackgroundTasks
):
    """
    Ingère un document avec Pipeline V2.

    Exécute Pass 0 (Structural Graph) + Pass 1 (Lecture Stratifiée).
    Optionnellement enchaîne Pass 2 (Enrichissement).
    """
    try:
        # TODO: Implémenter l'intégration avec les orchestrateurs
        # Pour l'instant, retourne un mock

        logger.info(f"[API:V2] Ingestion demandée: {request.doc_id}")

        # Placeholder response
        return IngestResponse(
            doc_id=request.doc_id,
            status="accepted",
            pass0_status="pending",
            pass1_status="pending",
            pass2_status="pending" if request.run_pass2 else None,
            stats={"message": "Ingestion queued"}
        )

    except Exception as e:
        logger.error(f"[API:V2] Erreur ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/enrich", response_model=EnrichResponse)
async def enrich_document(request: EnrichRequest):
    """
    Enrichit un document avec Pass 2.

    Extrait les relations entre concepts.
    """
    try:
        logger.info(f"[API:V2] Enrichissement demandé: {request.doc_id}")

        # TODO: Implémenter l'intégration avec Pass2OrchestratorV2

        return EnrichResponse(
            doc_id=request.doc_id,
            status="accepted",
            relations_extracted=0,
            stats={"message": "Enrichissement queued"}
        )

    except Exception as e:
        logger.error(f"[API:V2] Erreur enrichissement: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/consolidate", response_model=ConsolidateResponse)
async def consolidate_corpus(request: ConsolidateRequest):
    """
    Consolide le corpus avec Pass 3.

    Modes:
    - batch: Traite tout le corpus
    - incremental: Intègre un nouveau document
    """
    try:
        logger.info(f"[API:V2] Consolidation demandée: mode={request.mode}")

        # Initialiser Pass3 Orchestrator
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings
        from knowbase.stratified.pass3.orchestrator import Pass3OrchestratorV2, Pass3Mode

        settings = get_settings()
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        orchestrator = Pass3OrchestratorV2(
            neo4j_driver=neo4j_client.driver,
            tenant_id=request.tenant_id or "default",
            allow_fallback=True  # Fallback heuristique si pas de LLM
        )

        # Exécuter Pass 3 selon le mode
        if request.mode == "batch":
            result = orchestrator.process_batch(persist=True)
        else:
            # Mode incremental nécessite les concepts du nouveau doc
            # Pour l'instant, utiliser batch
            result = orchestrator.process_batch(persist=True)

        logger.info(
            f"[API:V2] Pass 3 terminé: {len(result.canonical_concepts)} canonical concepts, "
            f"{len(result.canonical_themes)} canonical themes"
        )

        return ConsolidateResponse(
            status="completed",
            canonical_concepts=len(result.canonical_concepts),
            canonical_themes=len(result.canonical_themes),
            stats={
                "mode": request.mode,
                "concepts_processed": result.stats.concepts_processed,
                "themes_processed": result.stats.themes_processed,
                "concept_clusters": result.stats.concept_clusters,
                "theme_clusters": result.stats.theme_clusters,
                "canonical_concepts_created": result.stats.canonical_concepts_created,
                "canonical_themes_created": result.stats.canonical_themes_created,
            }
        )

    except Exception as e:
        logger.error(f"[API:V2] Erreur consolidation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_id}/graph", response_model=DocumentGraph)
async def get_document_graph(doc_id: str):
    """
    Retourne le graphe sémantique d'un document.

    Inclut: Subject, Themes, Concepts, Informations, Relations.
    """
    try:
        logger.info(f"[API:V2] Graphe demandé: {doc_id}")

        # TODO: Implémenter la requête Neo4j

        return DocumentGraph(
            doc_id=doc_id,
            nodes=[],
            relations=[],
            stats={"message": "Not implemented yet"}
        )

    except Exception as e:
        logger.error(f"[API:V2] Erreur graphe: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_id}/assertions", response_model=AssertionLogResponse)
async def get_assertion_log(
    doc_id: str,
    status: Optional[str] = None  # Filter by status
):
    """
    Retourne le journal d'assertions d'un document.

    Paramètres:
    - status: Filtrer par statut (PROMOTED, ABSTAINED, REJECTED)
    """
    try:
        logger.info(f"[API:V2] AssertionLog demandé: {doc_id}")

        # TODO: Implémenter la requête Neo4j

        return AssertionLogResponse(
            doc_id=doc_id,
            entries=[],
            stats={"message": "Not implemented yet"}
        )

    except Exception as e:
        logger.error(f"[API:V2] Erreur assertion log: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=SearchResponse)
async def search_v2(request: SearchRequest):
    """
    Recherche sur le graphe sémantique V2.

    Recherche par concepts et retourne les informations associées.
    """
    try:
        logger.info(f"[API:V2] Recherche: {request.query}")

        # TODO: Implémenter la recherche sémantique

        return SearchResponse(
            query=request.query,
            results=[],
            total=0
        )

    except Exception as e:
        logger.error(f"[API:V2] Erreur recherche: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Vérifie la santé de l'API V2."""
    return {
        "status": "healthy",
        "version": "v2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/stats")
async def get_stats():
    """
    Retourne les statistiques globales du Pipeline V2.
    """
    return await _get_v2_stats_from_neo4j()


@router.get("/stats/detailed")
async def get_stats_detailed():
    """
    Retourne les statistiques détaillées du Pipeline V2.
    """
    return await _get_v2_stats_from_neo4j()


async def _get_v2_stats_from_neo4j():
    """Récupère les vraies stats depuis Neo4j."""
    try:
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )

        # Query pour compter les différents types de nœuds
        query = """
        MATCH (n)
        WHERE n.tenant_id = 'default'
        WITH labels(n)[0] AS label, count(n) AS cnt
        RETURN label, cnt
        """

        results = client.execute_query(query)

        # Parser les résultats
        counts = {}
        for record in results:
            label = record.get("label", "")
            cnt = record.get("cnt", 0)
            counts[label] = cnt

        return {
            "documents_count": counts.get("DocumentVersion", 0) + counts.get("Document", 0),
            "subjects_count": counts.get("Subject", 0),
            "themes_count": counts.get("Theme", 0),
            "concepts_count": counts.get("Concept", 0),
            "informations_count": counts.get("Information", 0),
            "assertion_logs_count": counts.get("AssertionLog", 0),
            "canonical_concepts_count": counts.get("CanonicalConcept", 0),
            "relations_count": counts.get("ProvenRelation", 0),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"[OSMOSE:V2:Stats] Error fetching stats: {e}")
        return {
            "documents_count": 0,
            "subjects_count": 0,
            "themes_count": 0,
            "concepts_count": 0,
            "informations_count": 0,
            "assertion_logs_count": 0,
            "canonical_concepts_count": 0,
            "relations_count": 0,
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }


# ============================================================================
# RE-PROCESSING BATCH ENDPOINTS
# ============================================================================

class CachedDocumentInfo(BaseModel):
    """Info sur un document dans le cache."""
    cache_file: str
    cache_path: str
    document_id: str
    cache_version: str
    created_at: Optional[str] = None
    size_bytes: int = 0


class ReprocessRequest(BaseModel):
    """Requête de re-processing batch."""
    document_ids: Optional[List[str]] = None  # Si None, tous les documents
    cache_paths: Optional[List[str]] = None  # Alternative: chemins cache directs
    run_pass1: bool = True
    run_pass2: bool = True
    run_pass3: bool = False  # Consolidation à la fin
    tenant_id: str = "default"


class ReprocessStatus(BaseModel):
    """Statut du re-processing."""
    status: str  # idle, running, completed, failed
    total_documents: int = 0
    processed: int = 0
    failed: int = 0
    current_document: Optional[str] = None
    current_phase: Optional[str] = None
    progress_percent: float = 0.0
    started_at: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


# État du re-processing stocké dans Redis (voir fonctions _*_reprocess_state)


@router.get("/reprocess/cache", response_model=List[CachedDocumentInfo])
async def list_cached_documents():
    """
    Liste tous les documents disponibles dans le cache d'extraction.

    Permet de voir quels documents peuvent être re-processés avec Pipeline V2.
    """
    try:
        from knowbase.stratified.pass0.cache_loader import list_cached_documents as list_docs

        documents = list_docs("/data/extraction_cache")

        return [
            CachedDocumentInfo(
                cache_file=doc["cache_file"],
                cache_path=doc["cache_path"],
                document_id=doc["document_id"],
                cache_version=doc["cache_version"],
                created_at=doc.get("created_at"),
                size_bytes=doc.get("size_bytes", 0),
            )
            for doc in documents
        ]

    except Exception as e:
        logger.error(f"[API:V2] Erreur listing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reprocess/start")
async def start_reprocess(
    request: ReprocessRequest,
):
    """
    Démarre le re-processing batch avec Pipeline V2.

    Workflow:
    1. Charge les documents depuis le cache d'extraction
    2. Exécute Pass 1 (Lecture Stratifiée) sur chaque document
    3. Optionnellement exécute Pass 2 (Enrichissement)
    4. Optionnellement exécute Pass 3 (Consolidation) à la fin
    """
    # Vérifier si un process est déjà en cours via Redis
    existing_state = _load_reprocess_state()
    if existing_state and existing_state.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="Re-processing already running"
        )

    try:
        from knowbase.stratified.pass0.cache_loader import list_cached_documents as list_docs

        # Déterminer les documents à traiter
        documents = list_docs("/data/extraction_cache")

        if request.document_ids:
            documents = [
                d for d in documents
                if d["document_id"] in request.document_ids
            ]
        elif request.cache_paths:
            documents = [
                d for d in documents
                if d["cache_path"] in request.cache_paths
            ]

        if not documents:
            raise HTTPException(
                status_code=404,
                detail="No documents found to process"
            )

        # Initialiser l'état dans Redis
        initial_state = {
            "status": "running",
            "total_documents": len(documents),
            "processed": 0,
            "failed": 0,
            "current_document": None,
            "current_phase": "INITIALIZING",
            "progress_percent": 0.0,
            "started_at": datetime.utcnow().isoformat(),
            "errors": []
        }
        if not _save_reprocess_state(initial_state):
            logger.error("[OSMOSE:V2] CRITICAL: Failed to save initial state to Redis!")
            # Continue anyway, but warn that progress tracking won't work
        else:
            logger.info(f"[OSMOSE:V2] Reprocess started: {len(documents)} documents")

        # Enqueuer dans le worker RQ dédié (au lieu de BackgroundTasks)
        from knowbase.ingestion.queue.connection import get_queue
        queue = get_queue("reprocess")
        job = queue.enqueue(
            "knowbase.ingestion.queue.reprocess_job.reprocess_batch_job",
            documents=documents,
            run_pass1=request.run_pass1,
            run_pass2=request.run_pass2,
            run_pass3=request.run_pass3,
            tenant_id=request.tenant_id,
            job_timeout=7200,  # 2h max
        )

        return {
            "status": "started",
            "total_documents": len(documents),
            "message": f"Re-processing {len(documents)} documents with Pipeline V2"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API:V2] Erreur démarrage reprocess: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reprocess/status", response_model=ReprocessStatus)
async def get_reprocess_status():
    """Retourne le statut actuel du re-processing depuis Redis."""
    state_data = _load_reprocess_state()

    if state_data is None:
        return ReprocessStatus(status="idle")

    return ReprocessStatus(**state_data)


@router.post("/reprocess/cancel")
async def cancel_reprocess():
    """Annule le re-processing en cours."""
    state_data = _load_reprocess_state()

    if state_data is None or state_data.get("status") != "running":
        raise HTTPException(
            status_code=400,
            detail="No re-processing running"
        )

    state_data["status"] = "cancelled"
    _save_reprocess_state(state_data)

    return {"status": "cancelled", "message": "Re-processing cancelled"}


def _load_pass1_result_from_neo4j(neo4j_driver, doc_id: str, tenant_id: str):
    """
    Charge le résultat Pass 1 depuis Neo4j pour exécuter Pass 2 seul.

    Returns:
        Pass1Result ou None si pas de données
    """
    from knowbase.stratified.models import (
        Pass1Result, DocumentMeta, Subject, Theme, Concept, Information,
        ConceptRole
    )

    try:
        with neo4j_driver.session() as session:
            # 1. Charger Subject
            subject_result = session.run("""
                MATCH (d:Document {doc_id: $doc_id})-[:HAS_SUBJECT]->(s:Subject)
                RETURN s.subject_id as id, s.name as name, s.summary as summary,
                       s.structure as structure, s.language as language
            """, doc_id=doc_id).single()

            if not subject_result:
                logger.warning(f"[OSMOSE:V2] No Subject found for {doc_id}")
                return None

            subject = Subject(
                subject_id=subject_result["id"],
                name=subject_result["name"],
                summary=subject_result["summary"],
                structure=subject_result["structure"] or "CENTRAL",
                language=subject_result["language"] or "fr"
            )

            # 2. Charger Themes
            themes_result = session.run("""
                MATCH (s:Subject {subject_id: $subject_id})-[:HAS_THEME]->(t:Theme)
                RETURN t.theme_id as id, t.name as name, t.description as description
            """, subject_id=subject.subject_id)

            themes = [
                Theme(
                    theme_id=r["id"],
                    name=r["name"],
                    description=r["description"]
                )
                for r in themes_result
            ]

            # 3. Charger Concepts
            concepts_result = session.run("""
                MATCH (t:Theme)-[:HAS_CONCEPT]->(c:Concept)
                WHERE t.theme_id STARTS WITH $prefix
                RETURN c.concept_id as id, c.name as name, c.definition as definition,
                       c.role as role, c.lex_key as lex_key, c.variants as variants,
                       t.theme_id as theme_id
            """, prefix=f"theme_{doc_id}")

            concepts = []
            for r in concepts_result:
                try:
                    role = ConceptRole(r["role"]) if r["role"] else ConceptRole.STANDARD
                except ValueError:
                    role = ConceptRole.STANDARD
                concepts.append(Concept(
                    concept_id=r["id"],
                    theme_id=r["theme_id"],
                    name=r["name"],
                    definition=r["definition"],
                    role=role,
                    lex_key=r["lex_key"] or "",
                    variants=r["variants"] or []
                ))

            # 4. Charger Informations
            infos_result = session.run("""
                MATCH (c:Concept)-[:HAS_INFORMATION]->(i:Information)
                WHERE c.concept_id STARTS WITH $prefix
                OPTIONAL MATCH (i)-[:ANCHORED_IN]->(di:DocItem)
                RETURN i.information_id as id, i.text as text, i.type as type,
                       i.confidence as confidence, i.language as language,
                       c.concept_id as concept_id, collect(di.docitem_id) as anchors
            """, prefix=f"concept_{doc_id}")

            informations = []
            for r in infos_result:
                from knowbase.stratified.models import AssertionType
                try:
                    info_type = AssertionType(r["type"].upper()) if r["type"] else AssertionType.FACTUAL
                except ValueError:
                    info_type = AssertionType.FACTUAL
                informations.append(Information(
                    information_id=r["id"] or f"info_{doc_id}_{len(informations)}",
                    concept_id=r["concept_id"],
                    text=r["text"],
                    type=info_type,
                    confidence=r["confidence"] or 0.8,
                    language=r["language"] or "en",
                    anchor_docitem_ids=[a for a in r["anchors"] if a]
                ))

            # 5. Construire le Pass1Result
            doc_meta = DocumentMeta(
                doc_id=doc_id,
                title=subject.name,  # Utiliser le nom du subject comme titre
                tenant_id=tenant_id
            )

            return Pass1Result(
                tenant_id=tenant_id,
                doc=doc_meta,
                subject=subject,
                themes=themes,
                concepts=concepts,
                informations=informations,
                assertion_log=[]  # Pas besoin pour Pass 2
            )

    except Exception as e:
        logger.error(f"[OSMOSE:V2] Error loading Pass1 from Neo4j: {e}")
        return None


