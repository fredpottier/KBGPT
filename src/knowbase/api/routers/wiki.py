"""
Router Wiki Generation Console — Phase 3 du Concept Assembly Engine.

Expose le pipeline ConceptResolver → EvidencePackBuilder → SectionPlanner →
ConstrainedGenerator via une API REST asynchrone avec BackgroundTasks.

⚠️ Job store en mémoire (POC only) — perdu au restart.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from knowbase.api.dependencies import get_tenant_id
from knowbase.api.schemas.wiki import (
    WikiArticleResponse,
    WikiConceptResult,
    WikiConceptSearchResponse,
    WikiGenerateRequest,
    WikiGenerateResponse,
    WikiJobStatus,
    WikiResolutionInfo,
)

logger = logging.getLogger("[OSMOSE] wiki_router")

router = APIRouter(prefix="/api/wiki", tags=["wiki"])

# ── Job store en mémoire (POC) ──────────────────────────────────────────


@dataclass
class WikiJobState:
    job_id: str
    concept_name: str
    language: str
    tenant_id: str
    status: str = "pending"  # pending | running | completed | completed_with_warnings | failed
    progress: Optional[str] = None
    error: Optional[str] = None
    markdown: Optional[str] = None
    article_data: Optional[dict] = None
    resolution_info: Optional[dict] = None
    created_at: str = ""
    completed_at: Optional[str] = None


_wiki_jobs: Dict[str, WikiJobState] = {}
_active_jobs: Dict[str, str] = {}  # clé logique → job_id

COMPLETED_REUSE_SECONDS = 300  # 5 min


def _job_key(tenant_id: str, concept_name: str, language: str) -> str:
    return f"{tenant_id}:{concept_name.lower().strip()}:{language.lower().strip()}"


def _is_reusable(job: WikiJobState) -> bool:
    """Un job est réutilisable s'il est en cours ou complété récemment."""
    if job.status in ("pending", "running"):
        return True
    if job.status in ("completed", "completed_with_warnings") and job.completed_at:
        elapsed = (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(job.completed_at)
        ).total_seconds()
        return elapsed < COMPLETED_REUSE_SECONDS
    return False


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post(
    "/generate",
    response_model=WikiGenerateResponse,
    summary="Lancer la génération d'un article wiki",
)
async def generate_article(
    request: WikiGenerateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
) -> WikiGenerateResponse:
    key = _job_key(tenant_id, request.concept_name, request.language)

    # Idempotence : réutiliser un job existant (sauf si force=True)
    if not request.force and key in _active_jobs:
        existing_id = _active_jobs[key]
        if existing_id in _wiki_jobs and _is_reusable(_wiki_jobs[existing_id]):
            job = _wiki_jobs[existing_id]
            return WikiGenerateResponse(
                job_id=job.job_id,
                status=job.status,
                message=f"Job existant réutilisé (statut: {job.status})",
            )

    job_id = str(uuid.uuid4())
    job = WikiJobState(
        job_id=job_id,
        concept_name=request.concept_name,
        language=request.language,
        tenant_id=tenant_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _wiki_jobs[job_id] = job
    _active_jobs[key] = job_id

    background_tasks.add_task(
        _run_wiki_pipeline, job_id, request.concept_name, request.language, tenant_id
    )

    return WikiGenerateResponse(
        job_id=job_id,
        status="pending",
        message=f"Génération lancée pour '{request.concept_name}' en {request.language}",
    )


@router.get(
    "/status/{job_id}",
    response_model=WikiJobStatus,
    summary="Statut d'un job de génération wiki",
)
async def get_job_status(job_id: str) -> WikiJobStatus:
    job = _wiki_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' introuvable")
    return WikiJobStatus(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        error=job.error,
    )


@router.get(
    "/article/{job_id}",
    response_model=WikiArticleResponse,
    summary="Récupérer l'article wiki généré",
)
async def get_article(job_id: str) -> WikiArticleResponse:
    job = _wiki_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' introuvable")

    if job.status in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Article pas encore prêt (statut: {job.status})",
        )

    if job.status == "failed":
        raise HTTPException(
            status_code=422,
            detail=f"Génération échouée : {job.error}",
        )

    data = job.article_data or {}
    resolution = job.resolution_info or {}

    return WikiArticleResponse(
        job_id=job.job_id,
        concept_name=job.concept_name,
        language=job.language,
        markdown=job.markdown or "",
        sections_count=data.get("sections_count", 0),
        total_citations=data.get("total_citations", 0),
        generation_confidence=data.get("generation_confidence", 0.0),
        all_gaps=data.get("all_gaps", []),
        source_count=data.get("source_count", 0),
        unit_count=data.get("unit_count", 0),
        resolution=WikiResolutionInfo(
            resolution_method=resolution.get("resolution_method", "unknown"),
            resolution_confidence=resolution.get("resolution_confidence", 0.0),
            matched_entities=resolution.get("matched_entities", 0),
            ambiguity_notes=resolution.get("ambiguity_notes", []),
        ),
        generated_at=data.get("generated_at", ""),
    )


@router.get(
    "/concepts/search",
    response_model=WikiConceptSearchResponse,
    summary="Recherche de concepts disponibles (autocomplétion)",
)
async def search_concepts(
    q: str = Query(..., min_length=1, description="Terme de recherche"),
    limit: int = Query(default=10, ge=1, le=50),
    tenant_id: str = Depends(get_tenant_id),
) -> WikiConceptSearchResponse:
    """Recherche lexicale CONTAINS sur les entités Neo4j.

    ⚠️ Fallback POC — à remplacer par le Concept Matching Engine.
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    neo4j_client = get_neo4j_client()
    cypher = """
    MATCH (e:Entity {tenant_id: $tenant_id})
    WHERE toLower(e.name) CONTAINS toLower($search_term)
    OPTIONAL MATCH (c:Claim)-[:ABOUT]->(e)
    WITH e.name AS name, e.entity_type AS entity_type, count(c) AS claim_count
    ORDER BY claim_count DESC
    LIMIT $limit
    RETURN name, entity_type, claim_count
    """
    results = []
    with neo4j_client.driver.session() as session:
        records = session.run(cypher, search_term=q, tenant_id=tenant_id, limit=limit)
        for r in records:
            results.append(
                WikiConceptResult(
                    entity_name=r["name"],
                    entity_type=r["entity_type"] or "concept",
                    claim_count=r["claim_count"],
                )
            )

    return WikiConceptSearchResponse(results=results, total=len(results))


# ── Pipeline background ─────────────────────────────────────────────────


def _run_wiki_pipeline(
    job_id: str, concept_name: str, language: str, tenant_id: str
) -> None:
    """Exécute le pipeline wiki complet en arrière-plan."""
    job = _wiki_jobs[job_id]
    try:
        job.status = "running"

        # 1. Résolution du concept
        job.progress = "Résolution du concept..."
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.wiki.concept_resolver import ConceptResolver

        neo4j_client = get_neo4j_client()
        resolver = ConceptResolver(neo4j_client.driver)
        resolved = resolver.resolve(concept_name, tenant_id)

        job.resolution_info = {
            "resolution_method": resolved.resolution_method,
            "resolution_confidence": resolved.resolution_confidence,
            "matched_entities": len(resolved.entity_ids),
            "ambiguity_notes": resolved.ambiguity_notes,
        }

        # 2. Construction de l'evidence pack
        job.progress = "Construction de l'evidence pack..."
        from knowbase.common.clients.embeddings import get_embedding_manager
        from knowbase.common.clients import get_qdrant_client
        from knowbase.wiki.evidence_pack_builder import EvidencePackBuilder

        qdrant_client = get_qdrant_client()
        embedding_manager = get_embedding_manager()
        builder = EvidencePackBuilder(neo4j_client.driver, qdrant_client, embedding_manager)
        pack = builder.build(resolved, tenant_id)

        # 3. Planification des sections
        job.progress = "Planification des sections..."
        from knowbase.wiki.section_planner import SectionPlanner

        planner = SectionPlanner()
        plan = planner.plan(pack)

        # 4. Génération de l'article
        section_count = len(plan.sections)
        job.progress = f"Génération de l'article ({section_count} sections)..."
        from knowbase.wiki.constrained_generator import ConstrainedGenerator

        generator = ConstrainedGenerator(language)
        article = generator.generate(pack, plan)
        markdown = generator.render_markdown(article)

        # 5. Déterminer statut terminal
        confidence = article.average_confidence
        gap_count = len(article.all_gaps)
        is_fuzzy = resolved.resolution_method == "fuzzy"

        if confidence < 0.5 or gap_count > 3 or is_fuzzy:
            terminal_status = "completed_with_warnings"
        else:
            terminal_status = "completed"

        job.status = terminal_status
        job.markdown = markdown
        job.article_data = {
            "sections_count": len(article.sections),
            "total_citations": article.total_citations,
            "generation_confidence": round(confidence, 3),
            "all_gaps": article.all_gaps,
            "source_count": len(pack.source_index),
            "unit_count": len(pack.units),
            "generated_at": article.generated_at,
        }
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.progress = None

        logger.info(
            f"[OSMOSE:Wiki] Article généré pour '{concept_name}' — "
            f"statut={terminal_status}, confiance={confidence:.2f}, "
            f"sections={len(article.sections)}, citations={article.total_citations}"
        )

    except ValueError as e:
        job.status = "failed"
        job.error = str(e)
        job.progress = None
        logger.warning(f"[OSMOSE:Wiki] Concept introuvable : {e}")

    except Exception as e:
        job.status = "failed"
        job.error = f"Erreur interne : {str(e)}"
        job.progress = None
        logger.error(f"[OSMOSE:Wiki] Erreur pipeline pour '{concept_name}': {e}", exc_info=True)
