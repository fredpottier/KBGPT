"""
🌊 OSMOSE Semantic Intelligence - Modèles de données

Pydantic models pour la Phase 1 - Semantic Core
"""

from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import uuid4


# ===================================
# SEMANTIC PROFILING
# ===================================

class ComplexityZone(BaseModel):
    """Zone de complexité dans le document"""
    zone_id: str = Field(default_factory=lambda: f"zone_{uuid4().hex[:8]}")
    start_position: int
    end_position: int
    complexity_score: float = Field(ge=0.0, le=1.0)
    complexity_level: Literal["simple", "medium", "complex"]
    reasoning: str
    key_concepts: List[str] = []


class NarrativeThread(BaseModel):
    """Fil narratif détecté dans le document"""
    thread_id: str = Field(default_factory=lambda: f"thread_{uuid4().hex[:8]}")
    description: str
    start_position: int
    end_position: int
    confidence: float = Field(ge=0.0, le=1.0)
    keywords: List[str] = []
    causal_links: List[str] = []
    temporal_markers: List[str] = []
    cross_document_refs: List[str] = []


class SemanticProfile(BaseModel):
    """Profil sémantique complet d'un document"""
    document_id: str
    document_path: str
    tenant_id: str

    # Analyse de complexité
    overall_complexity: float = Field(ge=0.0, le=1.0)
    complexity_zones: List[ComplexityZone] = []

    # Fils narratifs
    narrative_threads: List[NarrativeThread] = []
    has_narrative_evolution: bool = False

    # Classification domaine
    domain: str = "general"
    domain_confidence: float = 0.0

    # Métadonnées
    total_concepts: int = 0
    total_entities: int = 0
    language: str = "en"
    processing_time_ms: float = 0.0

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ===================================
# PROTO-KG (STAGING)
# ===================================

class CandidateEntity(BaseModel):
    """Entité candidate pour le Proto-KG"""
    candidate_id: str = Field(default_factory=lambda: f"ent_{uuid4().hex[:12]}")
    tenant_id: str

    # Identification
    entity_name: str
    entity_type: str
    aliases: List[str] = []

    # Contexte source
    document_path: str
    chunk_id: str
    context_snippet: str

    # Sémantique
    confidence: float = Field(ge=0.0, le=1.0)
    narrative_thread_id: Optional[str] = None
    complexity_zone: Optional[str] = None

    # Status workflow
    status: Literal["PENDING_REVIEW", "AUTO_PROMOTED", "HUMAN_PROMOTED", "REJECTED"] = "PENDING_REVIEW"
    promotion_reason: Optional[str] = None

    # Métriques
    mention_count: int = 1
    cross_document_mentions: int = 0

    # Métadonnées
    semantic_metadata: Dict = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CandidateRelation(BaseModel):
    """Relation candidate pour le Proto-KG"""
    candidate_id: str = Field(default_factory=lambda: f"rel_{uuid4().hex[:12]}")
    tenant_id: str

    # Identification
    source_entity: str  # candidate_id de l'entité source
    target_entity: str  # candidate_id de l'entité cible
    relation_type: str
    relation_label: str

    # Contexte source
    document_path: str
    chunk_id: str
    context_snippet: str

    # Sémantique
    confidence: float = Field(ge=0.0, le=1.0)
    is_causal: bool = False
    is_temporal: bool = False
    narrative_thread_id: Optional[str] = None

    # Status workflow
    status: Literal["PENDING_REVIEW", "AUTO_PROMOTED", "HUMAN_PROMOTED", "REJECTED"] = "PENDING_REVIEW"
    promotion_reason: Optional[str] = None

    # Métadonnées
    semantic_metadata: Dict = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ===================================
# SEGMENTATION INTELLIGENTE
# ===================================

class SemanticCluster(BaseModel):
    """Cluster sémantique de chunks"""
    cluster_id: str = Field(default_factory=lambda: f"cluster_{uuid4().hex[:8]}")
    chunk_ids: List[str]
    centroid_vector: Optional[List[float]] = None
    avg_similarity: float = 0.0
    complexity_level: str = "medium"
    has_narrative_continuity: bool = False
    narrative_thread_ids: List[str] = []


class SegmentationResult(BaseModel):
    """Résultat de la segmentation intelligente"""
    document_id: str
    clusters: List[SemanticCluster]
    total_chunks: int
    preserved_narrative_context: bool = False
    reasoning: str
