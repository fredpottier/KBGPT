"""
Schemas Pydantic pour la Wiki Generation Console & Knowledge Atlas.

Phase 3 : /api/wiki/generate, /api/wiki/status, /api/wiki/article, /api/wiki/concepts/search
Phase 4 : /api/wiki/home, /api/wiki/articles, /api/wiki/categories, /api/wiki/articles/{slug}/claims
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Phase 3 — Génération ─────────────────────────────────────────────────


class WikiGenerateRequest(BaseModel):
    concept_name: str = Field(..., description="Nom du concept à générer")
    language: str = Field(default="français", description="Langue de génération")
    force: bool = Field(default=False, description="Forcer la régénération même si un job récent existe")


class WikiGenerateResponse(BaseModel):
    job_id: str
    status: str  # "pending"
    message: str
    article_slug: Optional[str] = None


class WikiJobStatus(BaseModel):
    job_id: str
    status: str  # pending | running | completed | completed_with_warnings | failed
    progress: Optional[str] = None
    error: Optional[str] = None
    article_slug: Optional[str] = None


class WikiResolutionInfo(BaseModel):
    """Diagnostics de résolution du concept (transparence sur l'ancrage)."""

    resolution_method: str = Field(..., description="exact, exact+canon, alias, fuzzy")
    resolution_confidence: float
    matched_entities: int
    ambiguity_notes: List[str] = Field(default_factory=list)


class WikiArticleResponse(BaseModel):
    job_id: str
    concept_name: str
    language: str
    markdown: str
    sections_count: int
    total_citations: int
    generation_confidence: float = Field(
        ..., description="Signal d'exploitation (pas arbitre de vérité)"
    )
    all_gaps: List[str]
    source_count: int
    unit_count: int
    resolution: WikiResolutionInfo
    generated_at: str
    article_slug: Optional[str] = None


class WikiConceptResult(BaseModel):
    entity_name: str
    entity_type: str
    claim_count: int


class WikiConceptSearchResponse(BaseModel):
    results: List[WikiConceptResult]
    total: int


# ── Phase 4 — Knowledge Atlas ────────────────────────────────────────────


class WikiSourceDetail(BaseModel):
    """Détail d'une source dans un article."""

    doc_id: str = ""
    doc_title: str = ""
    doc_type: Optional[str] = None
    unit_count: int = 0
    contribution_pct: float = 0.0


class WikiArticleListItem(BaseModel):
    """Article dans une liste (sans markdown)."""

    slug: str
    title: str
    entity_type: str = "concept"
    category_key: str = "other"
    importance_tier: int = 3
    importance_score: float = 0.0
    generation_confidence: float = 0.0
    source_count: int = 0
    unit_count: int = 0
    sections_count: int = 0
    total_citations: int = 0
    updated_at: Optional[str] = None


class WikiArticleListResponse(BaseModel):
    """Réponse paginée pour la liste d'articles."""

    articles: List[WikiArticleListItem]
    total: int
    limit: int = 20
    offset: int = 0


class WikiArticleDetail(BaseModel):
    """Article complet depuis Neo4j (persisté)."""

    slug: str
    title: str
    tenant_id: str = "default"
    language: str = "français"
    entity_type: str = "concept"
    category_key: str = "other"
    markdown: str = ""
    linked_markdown: Optional[str] = None
    outgoing_links: List[str] = Field(default_factory=list)
    linked_at: Optional[str] = None
    sections_count: int = 0
    total_citations: int = 0
    generation_confidence: float = 0.0
    all_gaps: List[str] = Field(default_factory=list)
    source_count: int = 0
    unit_count: int = 0
    source_details: List[WikiSourceDetail] = Field(default_factory=list)
    related_concepts: List[Dict[str, Any]] = Field(default_factory=list)
    resolution_method: str = "unknown"
    resolution_confidence: float = 0.0
    importance_score: float = 0.0
    importance_tier: int = 3
    status: str = "published"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    reading_path: List[WikiReadingPathItem] = Field(default_factory=list)
    linked_articles: List[WikiLinkedArticle] = Field(default_factory=list)


class WikiCorpusStats(BaseModel):
    """Statistiques globales du corpus."""

    total_documents: int = 0
    total_claims: int = 0
    total_entities: int = 0
    total_articles: int = 0
    coverage_pct: float = 0.0


class WikiDomainArticle(BaseModel):
    """Article dans un domaine de connaissance."""

    slug: str
    title: str
    tier: int = 3


class WikiKnowledgeDomain(BaseModel):
    """Domaine de connaissance pour la homepage Atlas."""

    name: str
    domain_key: str
    question: str = ""
    doc_count: int = 0
    sub_domains: List[str] = Field(default_factory=list)
    articles: List[WikiDomainArticle] = Field(default_factory=list)
    article_count: int = 0


class WikiRecentArticle(BaseModel):
    """Article récent pour la homepage."""

    slug: str
    title: str
    entity_type: str = "concept"
    category_key: str = "other"
    importance_tier: int = 3
    generation_confidence: float = 0.0
    updated_at: Optional[str] = None


class WikiCategoryItem(BaseModel):
    """Catégorie avec nombre d'articles."""

    category_key: str
    label: str
    article_count: int = 0


class WikiDomainContext(BaseModel):
    """Contexte du domaine de connaissance pour la homepage."""

    domain_summary: str = ""
    industry: str = ""
    sub_domains: List[str] = Field(default_factory=list)
    key_concepts: List[str] = Field(default_factory=list)
    target_users: List[str] = Field(default_factory=list)


class WikiTier1Concept(BaseModel):
    """Concept structurant Tier 1 pour la homepage."""

    name: str
    entity_type: str = "concept"
    importance_score: float = 0.0
    has_article: bool = False
    slug: Optional[str] = None


class WikiBlindSpot(BaseModel):
    """Zone à surveiller dans le corpus."""

    type: str  # high_contradictions | value_contradiction | scope_variation | low_coverage | missing_article
    domain: str
    detail: str
    severity: str = "warning"  # warning | info


class WikiCorpusNarrativeEntityType(BaseModel):
    """Type d'entité avec compteur."""

    type: str
    count: int = 0


class WikiCorpusNarrativeEntity(BaseModel):
    """Entité top du corpus."""

    name: str
    claim_count: int = 0
    has_article: bool = False
    slug: Optional[str] = None


class WikiCorpusNarrativeDocType(BaseModel):
    """Type de document dans la distribution."""

    type: str
    count: int = 0


class WikiCorpusNarrative(BaseModel):
    """Données structurées pour le récit narratif du corpus."""

    top_entity_types: List[WikiCorpusNarrativeEntityType] = Field(default_factory=list)
    top_entities: List[WikiCorpusNarrativeEntity] = Field(default_factory=list)
    doc_type_distribution: List[WikiCorpusNarrativeDocType] = Field(default_factory=list)
    entity_count_with_articles: int = 0
    entity_count_without_articles: int = 0


class WikiStartHere(BaseModel):
    """Article Tier 1 pour la section 'Commencer par'."""

    slug: str
    title: str
    importance_score: float = 0.0


class WikiHomeResponse(BaseModel):
    """Réponse pour la homepage Atlas."""

    corpus_stats: WikiCorpusStats
    domain_context: Optional[WikiDomainContext] = None
    corpus_narrative: Optional[WikiCorpusNarrative] = None
    knowledge_domains: List[WikiKnowledgeDomain] = Field(default_factory=list)
    recent_articles: List[WikiRecentArticle] = Field(default_factory=list)
    tier1_concepts: List[WikiTier1Concept] = Field(default_factory=list)
    blind_spots: List[WikiBlindSpot] = Field(default_factory=list)
    start_here: List[WikiStartHere] = Field(default_factory=list)
    contradiction_count: int = 0


class WikiReadingPathItem(BaseModel):
    """Element du reading path d'un article."""

    slug: str
    title: str
    importance_tier: int = 3
    concept_name: str = ""


class WikiLinkedArticle(BaseModel):
    """Article lié (voisinage sémantique)."""

    slug: str
    title: str
    importance_tier: int = 3
    shared_concepts: int = 0


class WikiDomainConcept(BaseModel):
    """Concept dans un domaine/facette."""

    name: str
    entity_type: str = "concept"
    claim_count: int = 0
    doc_count: int = 0
    article_slug: Optional[str] = None
    article_title: Optional[str] = None
    tier: Optional[int] = None


class WikiDomainArticleDetail(BaseModel):
    """Article dans un domaine/facette (avec relevance)."""

    slug: str
    title: str
    importance_tier: int = 3
    importance_score: float = 0.0
    confidence: float = 0.0
    relevance: int = 0


class WikiDomainDocument(BaseModel):
    """Document contributeur d'un domaine."""

    doc_id: str
    claim_count: int = 0


class WikiDomainStats(BaseModel):
    """Statistiques d'un domaine."""

    total_claims: int = 0
    doc_count: int = 0
    contradiction_count: int = 0
    article_count: int = 0
    gap_count: int = 0


class WikiDomainGap(BaseModel):
    """Concept sans article dans un domaine."""

    name: str
    entity_type: str = "concept"
    claim_count: int = 0


class WikiDomainQuestion(BaseModel):
    """Question fréquente suggérée pour un domaine."""

    question: str
    concept: str


class WikiDomainPageResponse(BaseModel):
    """Réponse pour la page d'un domaine/facette."""

    facet_id: str
    name: str
    kind: str = "domain"
    lifecycle: str = "validated"
    doc_count: int = 0
    question: str = ""
    domain_key: str = ""
    top_concepts: List[WikiDomainConcept] = Field(default_factory=list)
    articles: List[WikiDomainArticleDetail] = Field(default_factory=list)
    documents: List[WikiDomainDocument] = Field(default_factory=list)
    stats: WikiDomainStats = Field(default_factory=WikiDomainStats)
    gaps: List[WikiDomainGap] = Field(default_factory=list)
    suggested_questions: List[WikiDomainQuestion] = Field(default_factory=list)


class WikiClaimItem(BaseModel):
    """Claim pour le drill-down d'un article."""

    claim_id: str
    text: str
    claim_type: str = "FACTUAL"
    confidence: float = 0.0
    doc_id: Optional[str] = None
    source_title: str = ""


class WikiClaimsResponse(BaseModel):
    """Réponse pour les claims d'un article."""

    claims: List[WikiClaimItem]
    total: int


class WikiCategoriesResponse(BaseModel):
    """Réponse pour la liste des catégories."""

    categories: List[WikiCategoryItem]


# ── Phase 4 — Admin : Scoring & Batch Generation ─────────────────────────


class WikiScoredConcept(BaseModel):
    """Concept avec score d'importance (pour la page admin)."""

    entity_name: str
    entity_type: str = "concept"
    entity_id: str = ""
    claim_count: int = 0
    doc_count: int = 0
    graph_degree: int = 0
    importance_score: float = 0.0
    importance_tier: int = 3
    has_article: bool = False
    article_slug: Optional[str] = None


class WikiScoringResponse(BaseModel):
    """Réponse du scoring complet des concepts."""

    concepts: List[WikiScoredConcept]
    total: int
    tier1_count: int = 0
    tier2_count: int = 0
    tier3_count: int = 0
    articles_count: int = 0


# ── Phase 5 — Concept Linking ─────────────────────────────────────────────


class WikiBatchLinkRequest(BaseModel):
    """Requête de linking batch."""

    force: bool = Field(default=False, description="Re-linker même les articles déjà linkés")
    max_concurrent: int = Field(default=3, ge=1, le=10, description="Parallélisme borné")


class WikiLinkingJobItem(BaseModel):
    """État d'un job de linking."""

    slug: str
    title: str = ""
    status: str = "queued"  # queued | running | completed | failed | skipped | cancelled
    link_count: int = 0
    candidates_count: int = 0
    error: Optional[str] = None


class WikiBatchLinkStatus(BaseModel):
    """État global du batch de linking."""

    batch_id: str
    status: str = "running"  # running | completed | suspended
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    jobs: List[WikiLinkingJobItem] = Field(default_factory=list)


# ── Phase 4 — Admin : Scoring & Batch Generation ─────────────────────────


class WikiBatchGenerateRequest(BaseModel):
    """Requête de génération batch."""

    max_tier: int = Field(default=2, ge=1, le=3, description="Tier maximum à générer (1=Tier1 seul, 2=Tier1+2, 3=tous)")
    max_articles: int = Field(default=10, ge=1, le=10000, description="Nombre max d'articles à générer")
    language: str = Field(default="français")
    skip_existing: bool = Field(default=True, description="Ignorer les concepts ayant déjà un article")


class WikiBatchJobItem(BaseModel):
    """État d'un job dans le batch."""

    concept_name: str
    entity_type: str = "concept"
    importance_tier: int = 3
    job_id: Optional[str] = None
    status: str = "queued"  # queued | running | completed | failed
    article_slug: Optional[str] = None
    error: Optional[str] = None


class WikiBatchStatus(BaseModel):
    """État global du batch de génération."""

    batch_id: str
    status: str = "running"  # running | completed | completed_with_errors
    total: int = 0
    completed: int = 0
    failed: int = 0
    running: int = 0
    queued: int = 0
    language: str = "français"
    jobs: List[WikiBatchJobItem] = Field(default_factory=list)
