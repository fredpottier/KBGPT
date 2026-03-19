"""
Router Wiki — Knowledge Atlas (Phase 4) + Generation Console (Phase 3).

Phase 3 : ConceptResolver → EvidencePackBuilder → SectionPlanner → ConstrainedGenerator
Phase 4 : Persistence Neo4j + navigation Atlas + intelligence visuelle

⚠️ Job store en mémoire (POC) — perdu au restart. Articles persistés en Neo4j.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from knowbase.api.dependencies import get_tenant_id
from knowbase.api.schemas.wiki import (
    WikiArticleDetail,
    WikiArticleListItem,
    WikiArticleListResponse,
    WikiArticleResponse,
    WikiBatchGenerateRequest,
    WikiBatchJobItem,
    WikiBatchLinkRequest,
    WikiBatchLinkStatus,
    WikiBatchStatus,
    WikiBlindSpot,
    WikiCategoriesResponse,
    WikiCategoryItem,
    WikiClaimItem,
    WikiClaimsResponse,
    WikiConceptResult,
    WikiConceptSearchResponse,
    WikiCorpusNarrative,
    WikiCorpusNarrativeDocType,
    WikiCorpusNarrativeEntity,
    WikiCorpusNarrativeEntityType,
    WikiCorpusStats,
    WikiDomainArticle,
    WikiDomainContext,
    WikiGenerateRequest,
    WikiGenerateResponse,
    WikiHomeResponse,
    WikiJobStatus,
    WikiKnowledgeDomain,
    WikiLinkingJobItem,
    WikiRecentArticle,
    WikiResolutionInfo,
    WikiScoredConcept,
    WikiScoringResponse,
    WikiDomainArticleDetail,
    WikiDomainConcept,
    WikiDomainDocument,
    WikiDomainGap,
    WikiDomainPageResponse,
    WikiDomainQuestion,
    WikiDomainStats,
    WikiLinkedArticle,
    WikiReadingPathItem,
    WikiSourceDetail,
    WikiStartHere,
    WikiTier1Concept,
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
    article_slug: Optional[str] = None
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


# ── Phase 3 — Endpoints Génération ──────────────────────────────────────


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
                article_slug=job.article_slug,
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
        article_slug=job.article_slug,
    )


@router.get(
    "/article/{job_id}",
    response_model=WikiArticleResponse,
    summary="Récupérer l'article wiki généré (par job_id)",
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
        article_slug=job.article_slug,
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


# ── Phase 4 — Endpoints Knowledge Atlas ─────────────────────────────────


def _get_persister():
    """Lazy import du WikiArticlePersister."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.wiki.persistence import WikiArticlePersister

    return WikiArticlePersister(get_neo4j_client().driver)


@router.get(
    "/home",
    response_model=WikiHomeResponse,
    summary="Homepage Atlas (stats + Tier 1 + récents + gaps)",
)
async def get_home(
    tenant_id: str = Depends(get_tenant_id),
) -> WikiHomeResponse:
    persister = _get_persister()
    data = persister.get_home_data(tenant_id)

    # Charger le domain context depuis PostgreSQL
    domain_ctx = None
    try:
        from knowbase.ontology.domain_context_store import DomainContextStore

        store = DomainContextStore()
        profile = store.get_profile(tenant_id)
        if profile:
            domain_ctx = WikiDomainContext(
                domain_summary=profile.domain_summary or "",
                industry=profile.industry or "",
                sub_domains=profile.sub_domains or [],
                key_concepts=profile.key_concepts or [],
                target_users=profile.target_users or [],
            )
    except Exception as e:
        logger.warning("Impossible de charger le domain context: %s", e)

    # Construire le corpus narrative
    raw_narrative = data.get("corpus_narrative", {})
    corpus_narrative = WikiCorpusNarrative(
        top_entity_types=[
            WikiCorpusNarrativeEntityType(**t) for t in raw_narrative.get("top_entity_types", [])
        ],
        top_entities=[
            WikiCorpusNarrativeEntity(**e) for e in raw_narrative.get("top_entities", [])
        ],
        doc_type_distribution=[
            WikiCorpusNarrativeDocType(**d) for d in raw_narrative.get("doc_type_distribution", [])
        ],
        entity_count_with_articles=raw_narrative.get("entity_count_with_articles", 0),
        entity_count_without_articles=raw_narrative.get("entity_count_without_articles", 0),
    )

    return WikiHomeResponse(
        corpus_stats=WikiCorpusStats(**data["corpus_stats"]),
        domain_context=domain_ctx,
        corpus_narrative=corpus_narrative,
        knowledge_domains=[
            WikiKnowledgeDomain(
                name=d["name"],
                domain_key=d["domain_key"],
                question=d.get("question") or "",
                doc_count=d.get("doc_count", 0),
                sub_domains=d.get("sub_domains", []),
                articles=[WikiDomainArticle(**a) for a in d.get("articles", [])],
                article_count=d.get("article_count", 0),
            )
            for d in data["knowledge_domains"]
        ],
        recent_articles=[WikiRecentArticle(**a) for a in data["recent_articles"]],
        tier1_concepts=[WikiTier1Concept(**c) for c in data.get("tier1_concepts", [])],
        blind_spots=[WikiBlindSpot(**s) for s in data.get("blind_spots", [])],
        start_here=[WikiStartHere(**s) for s in data.get("start_here", [])],
        contradiction_count=data.get("contradiction_count", 0),
    )


@router.get(
    "/domain/{facet_key}",
    response_model=WikiDomainPageResponse,
    summary="Page domaine/facette — concepts, articles, documents, gaps, questions",
)
async def get_domain_page(
    facet_key: str,
    tenant_id: str = Depends(get_tenant_id),
) -> WikiDomainPageResponse:
    persister = _get_persister()
    data = persister.get_domain_data(facet_key, tenant_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Domaine '{facet_key}' introuvable")

    return WikiDomainPageResponse(
        facet_id=data["facet_id"],
        name=data["name"],
        kind=data["kind"],
        lifecycle=data["lifecycle"],
        doc_count=data["doc_count"],
        question=data["question"],
        domain_key=data["domain_key"],
        top_concepts=[WikiDomainConcept(**c) for c in data["top_concepts"]],
        articles=[WikiDomainArticleDetail(**a) for a in data["articles"]],
        documents=[WikiDomainDocument(**d) for d in data["documents"]],
        stats=WikiDomainStats(**data["stats"]),
        gaps=[WikiDomainGap(**g) for g in data["gaps"]],
        suggested_questions=[WikiDomainQuestion(**q) for q in data["suggested_questions"]],
    )


@router.get(
    "/articles",
    response_model=WikiArticleListResponse,
    summary="Liste paginée des articles wiki",
)
async def list_articles(
    limit: int = Query(default=20, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    tier: Optional[int] = Query(default=None, ge=1, le=3),
    tenant_id: str = Depends(get_tenant_id),
) -> WikiArticleListResponse:
    persister = _get_persister()
    data = persister.list_articles(
        tenant_id=tenant_id,
        category=category,
        search=search,
        tier=tier,
        limit=limit,
        offset=offset,
    )

    articles = [WikiArticleListItem(**a) for a in data["articles"]]
    return WikiArticleListResponse(
        articles=articles,
        total=data["total"],
        limit=data["limit"],
        offset=data["offset"],
    )


@router.get(
    "/articles/{slug}",
    response_model=WikiArticleDetail,
    summary="Article complet par slug",
)
async def get_article_by_slug(
    slug: str,
    tenant_id: str = Depends(get_tenant_id),
) -> WikiArticleDetail:
    persister = _get_persister()
    data = persister.get_by_slug(slug, tenant_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Article '{slug}' introuvable")

    # Convertir source_details en WikiSourceDetail
    source_details = []
    raw_sources = data.get("source_details") or []
    if isinstance(raw_sources, list):
        for s in raw_sources:
            if isinstance(s, dict):
                source_details.append(WikiSourceDetail(**s))

    related_concepts = data.get("related_concepts") or []

    # Reading path + linked articles (non-blocking)
    reading_path = []
    linked_articles = []
    try:
        reading_path = [
            WikiReadingPathItem(**rp)
            for rp in persister.get_reading_path(slug, tenant_id)
        ]
        linked_articles = [
            WikiLinkedArticle(**la)
            for la in persister.get_linked_articles(slug, tenant_id)
        ]
    except Exception as e:
        logger.warning(f"Reading path/linked articles failed (non-blocking): {e}")

    return WikiArticleDetail(
        slug=data.get("slug", slug),
        title=data.get("title", slug),
        tenant_id=data.get("tenant_id", tenant_id),
        language=data.get("language", "français"),
        entity_type=data.get("entity_type", "concept"),
        category_key=data.get("category_key", "other"),
        markdown=data.get("markdown", ""),
        linked_markdown=data.get("linked_markdown"),
        outgoing_links=data.get("outgoing_links", []),
        linked_at=data.get("linked_at"),
        sections_count=data.get("sections_count", 0),
        total_citations=data.get("total_citations", 0),
        generation_confidence=data.get("generation_confidence", 0.0),
        all_gaps=data.get("all_gaps", []),
        source_count=data.get("source_count", 0),
        unit_count=data.get("unit_count", 0),
        source_details=source_details,
        related_concepts=related_concepts,
        resolution_method=data.get("resolution_method", "unknown"),
        resolution_confidence=data.get("resolution_confidence", 0.0),
        importance_score=data.get("importance_score", 0.0),
        importance_tier=data.get("importance_tier", 3),
        status=data.get("status", "published"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        reading_path=reading_path,
        linked_articles=linked_articles,
    )


@router.get(
    "/articles/{slug}/claims",
    response_model=WikiClaimsResponse,
    summary="Claims liés à un article (drill-down)",
)
async def get_article_claims(
    slug: str,
    limit: int = Query(default=10, ge=1, le=50),
    tenant_id: str = Depends(get_tenant_id),
) -> WikiClaimsResponse:
    persister = _get_persister()
    claims_data = persister.get_article_claims(slug, tenant_id, limit=limit)
    claims = [WikiClaimItem(**c) for c in claims_data]
    return WikiClaimsResponse(claims=claims, total=len(claims))


@router.get(
    "/categories",
    response_model=WikiCategoriesResponse,
    summary="Catégories avec nombre d'articles",
)
async def get_categories(
    tenant_id: str = Depends(get_tenant_id),
) -> WikiCategoriesResponse:
    persister = _get_persister()
    cats = persister.get_categories(tenant_id)
    return WikiCategoriesResponse(
        categories=[WikiCategoryItem(**c) for c in cats]
    )


@router.delete(
    "/articles/{slug}",
    summary="Supprimer un article wiki",
)
async def delete_article(
    slug: str,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    persister = _get_persister()
    deleted = persister.delete_article(slug, tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Article '{slug}' introuvable")
    return {"deleted": True, "slug": slug}


@router.post(
    "/admin/regenerate-summary",
    summary="Regénère le résumé éditorial du corpus via LLM (admin)",
)
async def regenerate_corpus_summary(
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Regénère domain_summary à partir des données structurées du corpus."""
    persister = _get_persister()
    data = persister.get_home_data(tenant_id)
    narrative = data.get("corpus_narrative", {})
    stats = data.get("corpus_stats", {})
    domains = data.get("knowledge_domains", [])

    # Construire le contexte pour le LLM
    top_entities = [e["name"] for e in narrative.get("top_entities", [])[:8]]
    doc_types = [d["type"] for d in narrative.get("doc_type_distribution", [])[:5]]
    domain_names = [d["name"] for d in domains[:6]]

    prompt = f"""Tu es un rédacteur éditorial pour un Atlas de connaissances.
Écris un résumé de 2-3 phrases décrivant le contenu de ce corpus documentaire.
Le résumé doit être informatif, professionnel, et donner envie d'explorer les articles.
Pas de formule de politesse, pas de "bienvenue", va droit au sujet.

Données du corpus :
- {stats.get('total_documents', 0)} documents sources
- {stats.get('total_claims', 0)} faits extraits
- {stats.get('total_articles', 0)} articles de synthèse
- Types de documents : {', '.join(doc_types) if doc_types else 'non spécifié'}
- Concepts les plus documentés : {', '.join(top_entities) if top_entities else 'non spécifié'}
- Domaines thématiques : {', '.join(domain_names) if domain_names else 'non spécifié'}

Résumé (en français, 2-3 phrases max) :"""

    try:
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()
        summary = router.complete(prompt, task=TaskType.SHORT_ENRICHMENT)
        summary = summary.strip().strip('"').strip()

        if len(summary) < 30:
            raise ValueError(f"Résumé trop court: {summary}")

        # Persister dans le DomainContextProfile
        from knowbase.ontology.domain_context_store import DomainContextStore

        store = DomainContextStore()
        profile = store.get_profile(tenant_id)
        if profile:
            profile.domain_summary = summary
            store.save_profile(profile)
            logger.info(f"[ATLAS] domain_summary regénéré ({len(summary)} chars)")
            return {"success": True, "domain_summary": summary}
        else:
            raise HTTPException(status_code=404, detail="Aucun DomainContextProfile pour ce tenant")

    except Exception as e:
        logger.error(f"[ATLAS] Erreur regénération résumé: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Admin : Scoring & Batch Generation ──────────────────────────────────

# Batch state en mémoire (POC)
_batch_states: Dict[str, WikiBatchStatus] = {}


# ── Admin : Concept Linking ────────────────────────────────────────────

_link_batch_states: Dict[str, WikiBatchLinkStatus] = {}


@router.post(
    "/admin/batch-link",
    response_model=WikiBatchLinkStatus,
    summary="Lancer le linking batch sur tout le corpus (admin)",
)
async def batch_link(
    request: WikiBatchLinkRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
) -> WikiBatchLinkStatus:
    """Lance le linking batch des articles : injection de liens inter-concepts par LLM."""
    persister = _get_persister()

    # Lister les articles à linker
    articles_data = persister.list_articles(tenant_id, limit=5000)
    all_articles = articles_data.get("articles", [])

    slugs_to_link = []
    for a in all_articles:
        slug = a.get("slug", "")
        if not slug:
            continue
        if not request.force:
            full = persister.get_by_slug(slug, tenant_id)
            if full and full.get("linked_markdown"):
                continue
        slugs_to_link.append(a)

    batch_id = str(uuid.uuid4())
    jobs = [
        WikiLinkingJobItem(
            slug=a.get("slug", ""),
            title=a.get("title", ""),
            status="queued",
        )
        for a in slugs_to_link
    ]

    batch = WikiBatchLinkStatus(
        batch_id=batch_id,
        status="running" if jobs else "completed",
        total=len(jobs),
        jobs=jobs,
    )
    _link_batch_states[batch_id] = batch

    if jobs:
        background_tasks.add_task(
            _run_batch_linking, batch_id, tenant_id, request.max_concurrent, request.force
        )
        logger.info(
            f"[OSMOSE:Wiki:Linking] Batch {batch_id} lancé : {len(jobs)} articles"
        )

    return batch


@router.get(
    "/admin/link-status",
    response_model=WikiBatchLinkStatus,
    summary="Statut du linking batch en cours",
)
async def get_link_status() -> WikiBatchLinkStatus:
    """Retourne le statut du dernier batch de linking."""
    if not _link_batch_states:
        raise HTTPException(status_code=404, detail="Aucun batch de linking en cours")
    # Retourner le plus récent
    batch_id = list(_link_batch_states.keys())[-1]
    return _link_batch_states[batch_id]


@router.get(
    "/admin/scoring",
    response_model=WikiScoringResponse,
    summary="Scoring d'importance de tous les concepts (admin)",
)
async def get_scoring(
    tenant_id: str = Depends(get_tenant_id),
) -> WikiScoringResponse:
    """Calcule et retourne le scoring d'importance de tous les concepts."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.wiki.importance_scorer import ImportanceScorer

    neo4j_client = get_neo4j_client()
    scorer = ImportanceScorer(neo4j_client.driver)
    scored = scorer.score_all_concepts(tenant_id)

    # Vérifier quels concepts ont déjà un article (via relation ABOUT, pas par titre)
    entity_article_map: Dict[str, str] = {}
    try:
        with neo4j_client.driver.session() as session:
            result = session.run(
                """
                MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e:Entity)
                RETURN e.entity_id AS entity_id, wa.slug AS slug
                """,
                tid=tenant_id,
            )
            for r in result:
                entity_article_map[r["entity_id"]] = r["slug"]
    except Exception as e:
        logger.warning(f"Could not load entity→article mapping: {e}")

    concepts = []
    for s in scored:
        slug = entity_article_map.get(s.entity_id)
        has_article = slug is not None
        concepts.append(
            WikiScoredConcept(
                entity_name=s.entity_name,
                entity_type=s.entity_type,
                entity_id=s.entity_id,
                claim_count=s.claim_count,
                doc_count=s.doc_count,
                graph_degree=s.graph_degree,
                importance_score=s.importance_score,
                importance_tier=s.importance_tier,
                has_article=has_article,
                article_slug=slug,
            )
        )

    return WikiScoringResponse(
        concepts=concepts,
        total=len(concepts),
        tier1_count=sum(1 for c in concepts if c.importance_tier == 1),
        tier2_count=sum(1 for c in concepts if c.importance_tier == 2),
        tier3_count=sum(1 for c in concepts if c.importance_tier == 3),
        articles_count=sum(1 for c in concepts if c.has_article),
    )


@router.post(
    "/admin/batch-generate",
    response_model=WikiBatchStatus,
    summary="Lancer la génération batch d'articles (admin)",
)
async def batch_generate(
    request: WikiBatchGenerateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
) -> WikiBatchStatus:
    """Lance la génération batch des articles pour les concepts Tier 1..max_tier."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.wiki.importance_scorer import ImportanceScorer

    neo4j_client = get_neo4j_client()
    scorer = ImportanceScorer(neo4j_client.driver)
    scored = scorer.score_all_concepts(tenant_id)

    # Filtrer par tier
    candidates = [s for s in scored if s.importance_tier <= request.max_tier]

    # Vérifier articles existants (via relation ABOUT, pas par titre)
    if request.skip_existing:
        existing_entity_ids: set = set()
        try:
            with neo4j_client.driver.session() as session:
                result = session.run(
                    """
                    MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e:Entity)
                    RETURN e.entity_id AS entity_id
                    """,
                    tid=tenant_id,
                )
                existing_entity_ids = {r["entity_id"] for r in result}
        except Exception as e:
            logger.warning(f"Could not load existing article entities: {e}")
        candidates = [c for c in candidates if c.entity_id not in existing_entity_ids]

    # Stratégie "toile" — prioriser les concepts connectés aux articles existants
    candidates = scorer.compute_web_priority(candidates, tenant_id)

    # Limiter
    candidates = candidates[: request.max_articles]

    if not candidates:
        batch_id = str(uuid.uuid4())
        return WikiBatchStatus(
            batch_id=batch_id,
            status="completed",
            total=0,
            language=request.language,
        )

    # Créer le batch
    batch_id = str(uuid.uuid4())
    jobs = [
        WikiBatchJobItem(
            concept_name=c.entity_name,
            entity_type=c.entity_type,
            importance_tier=c.importance_tier,
            status="queued",
        )
        for c in candidates
    ]

    batch = WikiBatchStatus(
        batch_id=batch_id,
        status="running",
        total=len(jobs),
        queued=len(jobs),
        language=request.language,
        jobs=jobs,
    )
    _batch_states[batch_id] = batch

    # Lancer en background
    background_tasks.add_task(
        _run_batch_generation, batch_id, request.language, tenant_id
    )

    logger.info(
        f"[OSMOSE:Wiki] Batch {batch_id} lancé : {len(jobs)} articles "
        f"(tier<={request.max_tier}, lang={request.language})"
    )

    return batch


@router.get(
    "/admin/batch-status/{batch_id}",
    response_model=WikiBatchStatus,
    summary="Statut d'un batch de génération",
)
async def get_batch_status(batch_id: str) -> WikiBatchStatus:
    batch = _batch_states.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' introuvable")
    return batch


# ── Pipeline background ─────────────────────────────────────────────────


def _run_wiki_pipeline(
    job_id: str, concept_name: str, language: str, tenant_id: str
) -> None:
    """Exécute le pipeline wiki complet en arrière-plan + persistence Neo4j."""
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

        # 6. Persistence Neo4j (non-bloquant pour le statut du job)
        job.progress = "Persistence de l'article..."
        article_slug = plan.slug
        try:
            from knowbase.wiki.persistence import WikiArticlePersister
            from knowbase.wiki.importance_scorer import ImportanceScorer, compute_importance

            persister = WikiArticlePersister(neo4j_client.driver)

            # Calcul de l'importance pour cette entité
            scorer = ImportanceScorer(neo4j_client.driver)
            all_scored = scorer.score_all_concepts(tenant_id)
            scored_map = {s.entity_name.lower(): s for s in all_scored}
            entity_scored = scored_map.get(resolved.canonical_name.lower())

            importance_score = entity_scored.importance_score if entity_scored else compute_importance(
                resolved.claim_count, len(resolved.doc_ids), 0
            )
            importance_tier = entity_scored.importance_tier if entity_scored else 3

            # Construire source_details depuis le pack
            source_details = [
                {
                    "doc_id": s.doc_id,
                    "doc_title": s.doc_title,
                    "doc_type": s.doc_type,
                    "unit_count": s.unit_count,
                    "contribution_pct": round(s.contribution_pct, 1),
                }
                for s in pack.source_index
            ]

            # Construire related_concepts (co-occurrence) + enrichir depuis le markdown
            related_concepts_data = [
                {
                    "entity_name": rc.entity_name,
                    "entity_type": rc.entity_type,
                    "co_occurrence_count": rc.co_occurrence_count,
                }
                for rc in pack.related_concepts[:8]
            ]
            related_concepts_data = persister.enrich_related_from_markdown(
                markdown=markdown,
                existing_related=related_concepts_data,
                concept_name=resolved.canonical_name,
                tenant_id=tenant_id,
            )

            persister.save_article(
                slug=article_slug,
                title=resolved.canonical_name,
                tenant_id=tenant_id,
                entity_type=resolved.entity_type,
                language=language,
                markdown=markdown,
                sections_count=len(article.sections),
                total_citations=article.total_citations,
                generation_confidence=round(confidence, 3),
                all_gaps=article.all_gaps,
                source_count=len(pack.source_index),
                unit_count=len(pack.units),
                source_details=source_details,
                resolution_method=resolved.resolution_method,
                resolution_confidence=resolved.resolution_confidence,
                importance_score=importance_score,
                importance_tier=importance_tier,
                entity_ids=resolved.entity_ids,
                related_concepts=related_concepts_data,
            )

            job.article_slug = article_slug
            logger.info(
                f"[OSMOSE:Wiki] Article '{article_slug}' persisté en Neo4j "
                f"(tier={importance_tier})"
            )

            # V2 : Linking incrémental — linker ce nouvel article + re-linker les impactés
            job.progress = "Linking incrémental..."
            try:
                from knowbase.wiki.concept_linker import ConceptLinker

                linker = ConceptLinker(neo4j_client.driver, tenant_id)
                link_summary = linker.link_incrementally(article_slug)

                new_result = link_summary.get("new_article")
                impacted = link_summary.get("impacted", [])
                link_count = new_result.link_count if new_result and new_result.success else 0

                logger.info(
                    f"[OSMOSE:Wiki] Linking incrémental pour '{article_slug}' : "
                    f"{link_count} liens, {len(impacted)} articles re-linkés"
                )
            except Exception as link_err:
                # Le linking incrémental est best-effort — ne bloque pas la génération
                logger.warning(
                    f"[OSMOSE:Wiki] Linking incrémental échoué pour '{article_slug}': {link_err}"
                )

        except Exception as persist_err:
            # La persistence échoue silencieusement — l'article est toujours disponible via job_id
            logger.error(
                f"[OSMOSE:Wiki] Erreur persistence pour '{concept_name}': {persist_err}",
                exc_info=True,
            )

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
        # Propager VLLMUnavailableError pour que le batch puisse s'arrêter
        from knowbase.common.llm_router import VLLMUnavailableError
        if isinstance(e, VLLMUnavailableError):
            job.status = "failed"
            job.error = "vLLM indisponible"
            job.progress = None
            logger.error(f"[OSMOSE:Wiki] vLLM down — pipeline arrêté pour '{concept_name}'")
            raise  # remonter au batch

        job.status = "failed"
        job.error = f"Erreur interne : {str(e)}"
        job.progress = None
        logger.error(f"[OSMOSE:Wiki] Erreur pipeline pour '{concept_name}': {e}", exc_info=True)


def _run_batch_generation(batch_id: str, language: str, tenant_id: str) -> None:
    """Exécute la génération batch séquentielle des articles wiki."""
    from knowbase.common.llm_router import VLLMUnavailableError

    batch = _batch_states[batch_id]

    for i, batch_job in enumerate(batch.jobs):
        concept_name = batch_job.concept_name
        batch_job.status = "running"
        batch.running = sum(1 for j in batch.jobs if j.status == "running")
        batch.queued = sum(1 for j in batch.jobs if j.status == "queued")

        logger.info(
            f"[OSMOSE:Wiki:Batch] [{i + 1}/{batch.total}] Génération '{concept_name}'..."
        )

        # Créer un job unitaire et exécuter le pipeline
        job_id = str(uuid.uuid4())
        job = WikiJobState(
            job_id=job_id,
            concept_name=concept_name,
            language=language,
            tenant_id=tenant_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        _wiki_jobs[job_id] = job
        batch_job.job_id = job_id

        try:
            _run_wiki_pipeline(job_id, concept_name, language, tenant_id)

            if job.status in ("completed", "completed_with_warnings"):
                batch_job.status = "completed"
                batch_job.article_slug = job.article_slug
                batch.completed += 1
            else:
                batch_job.status = "failed"
                batch_job.error = job.error
                batch.failed += 1

        except VLLMUnavailableError:
            # vLLM down — arrêter tout le batch proprement
            batch_job.status = "failed"
            batch_job.error = "vLLM indisponible"
            batch.failed += 1

            # Marquer tous les jobs restants comme annulés
            for remaining_job in batch.jobs[i + 1:]:
                remaining_job.status = "cancelled"

            batch.running = 0
            batch.queued = 0
            batch.status = "suspended"

            cancelled_count = len(batch.jobs) - (i + 1)
            logger.error(
                f"[OSMOSE:Wiki:Batch] vLLM DOWN — batch {batch_id} suspendu "
                f"après {batch.completed} OK, {batch.failed} échecs. "
                f"{cancelled_count} articles annulés."
            )
            return

        except Exception as e:
            batch_job.status = "failed"
            batch_job.error = str(e)
            batch.failed += 1
            logger.error(f"[OSMOSE:Wiki:Batch] Erreur '{concept_name}': {e}")

        batch.running = sum(1 for j in batch.jobs if j.status == "running")
        batch.queued = sum(1 for j in batch.jobs if j.status == "queued")

    # Terminé
    batch.running = 0
    batch.queued = 0
    if batch.failed > 0:
        batch.status = "completed_with_errors"
    else:
        batch.status = "completed"

    logger.info(
        f"[OSMOSE:Wiki:Batch] Batch {batch_id} terminé : "
        f"{batch.completed} OK, {batch.failed} échecs sur {batch.total}"
    )

    # Regénérer le résumé éditorial du corpus après un batch réussi
    if batch.completed > 0:
        try:
            _regenerate_summary_sync(tenant_id)
        except Exception as e:
            logger.warning(f"[OSMOSE:Wiki:Batch] Résumé éditorial non regénéré: {e}")


def _regenerate_summary_sync(tenant_id: str) -> None:
    """Regénère le domain_summary via LLM (appel synchrone pour background tasks)."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.wiki.persistence import WikiArticlePersister

    neo4j_client = get_neo4j_client()
    persister = WikiArticlePersister(neo4j_client.driver)
    data = persister.get_home_data(tenant_id)
    narrative = data.get("corpus_narrative", {})
    stats = data.get("corpus_stats", {})
    domains = data.get("knowledge_domains", [])

    top_entities = [e["name"] for e in narrative.get("top_entities", [])[:8]]
    doc_types = [d["type"] for d in narrative.get("doc_type_distribution", [])[:5]]
    domain_names = [d["name"] for d in domains[:6]]

    prompt = f"""Tu es un rédacteur éditorial pour un Atlas de connaissances.
Écris un résumé de 2-3 phrases décrivant le contenu de ce corpus documentaire.
Le résumé doit être informatif, professionnel, et donner envie d'explorer les articles.
Pas de formule de politesse, pas de "bienvenue", va droit au sujet.

Données du corpus :
- {stats.get('total_documents', 0)} documents sources
- {stats.get('total_claims', 0)} faits extraits
- {stats.get('total_articles', 0)} articles de synthèse
- Types de documents : {', '.join(doc_types) if doc_types else 'non spécifié'}
- Concepts les plus documentés : {', '.join(top_entities) if top_entities else 'non spécifié'}
- Domaines thématiques : {', '.join(domain_names) if domain_names else 'non spécifié'}

Résumé (en français, 2-3 phrases max) :"""

    from knowbase.common.llm_router import get_llm_router, TaskType

    router_llm = get_llm_router()
    summary = router_llm.complete(prompt, task=TaskType.SHORT_ENRICHMENT)
    summary = summary.strip().strip('"').strip()

    if len(summary) >= 30:
        from knowbase.ontology.domain_context_store import DomainContextStore

        store = DomainContextStore()
        profile = store.get_profile(tenant_id)
        if profile:
            profile.domain_summary = summary
            store.save_profile(profile)
            logger.info(f"[ATLAS] domain_summary auto-regénéré ({len(summary)} chars)")


def _run_batch_linking(
    batch_id: str, tenant_id: str, max_concurrent: int, force: bool
) -> None:
    """Exécute le linking batch séquentiel des articles wiki."""
    import asyncio

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.common.llm_router import VLLMUnavailableError
    from knowbase.wiki.concept_linker import (
        ConceptCandidateSelector,
        ConceptLinker,
        ConceptRegistryBuilder,
    )
    from knowbase.wiki.persistence import WikiArticlePersister

    batch = _link_batch_states[batch_id]
    neo4j_client = get_neo4j_client()
    persister = WikiArticlePersister(neo4j_client.driver)
    linker = ConceptLinker(neo4j_client.driver, tenant_id)
    selector = ConceptCandidateSelector()

    # Construire le registre une seule fois
    registry = ConceptRegistryBuilder.build_from_neo4j(neo4j_client.driver, tenant_id)

    if not registry:
        batch.status = "completed"
        logger.warning("[OSMOSE:Wiki:Linking] Registre vide — rien à linker")
        return

    for i, job in enumerate(batch.jobs):
        slug = job.slug
        job.status = "running"

        logger.info(
            f"[OSMOSE:Wiki:Linking] [{i + 1}/{batch.total}] Linking '{slug}'..."
        )

        article = persister.get_by_slug(slug, tenant_id)
        if not article or not article.get("markdown"):
            job.status = "skipped"
            batch.skipped += 1
            continue

        markdown = article["markdown"]
        candidates = selector.select_candidates(markdown, registry, slug)
        job.candidates_count = len(candidates)

        try:
            # Exécuter l'appel async dans un event loop
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    linker.link_article(slug, markdown, candidates)
                )
            finally:
                loop.close()

            if result.success:
                persister.update_linked_markdown(
                    slug=slug,
                    tenant_id=tenant_id,
                    linked_markdown=result.linked_markdown,
                    outgoing_links=result.outgoing_links,
                    linking_metadata={
                        "registry_size": len(registry),
                        "candidates_count": len(candidates),
                        "unresolved_mentions": result.unresolved_mentions,
                        "ambiguous_mentions": result.ambiguous_mentions,
                    },
                )
                job.status = "completed"
                job.link_count = result.link_count
                batch.completed += 1
            else:
                job.status = "failed"
                job.error = result.error
                batch.failed += 1

        except VLLMUnavailableError:
            job.status = "failed"
            job.error = "vLLM indisponible"
            batch.failed += 1

            for remaining_job in batch.jobs[i + 1:]:
                remaining_job.status = "cancelled"

            batch.status = "suspended"
            logger.error(
                f"[OSMOSE:Wiki:Linking] vLLM DOWN — batch {batch_id} suspendu "
                f"après {batch.completed} OK. "
                f"{len(batch.jobs) - (i + 1)} articles annulés."
            )
            return

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            batch.failed += 1
            logger.error(f"[OSMOSE:Wiki:Linking] Erreur '{slug}': {e}")

    batch.status = "completed"
    logger.info(
        f"[OSMOSE:Wiki:Linking] Batch {batch_id} terminé : "
        f"{batch.completed} OK, {batch.failed} échecs, "
        f"{batch.skipped} ignorés sur {batch.total}"
    )
