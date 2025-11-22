"""
🌊 OSMOSE Semantic Intelligence V2.1 - Modèles de données

Pydantic models pour Phase 1 V2.1 - Concept-First, Language-Agnostic

Architecture:
- Focus: Documents descriptifs (guidelines, standards, architecture)
- Multilingue: Cross-lingual concept unification automatique
- Concept-based: ENTITY, PRACTICE, STANDARD, TOOL, ROLE
"""

from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import uuid4
from enum import Enum


# ===================================
# DOCUMENT ROLE (STABLE ENUM)
# ===================================
# Note: Concept types are intentionally NOT an enum to remain domain-agnostic.
# Types are discovered dynamically by LLM based on document content.
# Examples: "product", "technology", "molecule", "campaign", "regulation", etc.

class DocumentRole(str, Enum):
    """Rôle du document par rapport au concept"""
    DEFINES = "defines"              # Document définit le concept (standard, guideline)
    IMPLEMENTS = "implements"        # Document implémente le concept (project, solution)
    AUDITS = "audits"               # Document audite le concept (audit report, compliance)
    PROVES = "proves"               # Document prouve conformité (certificate, attestation)
    REFERENCES = "references"        # Document mentionne le concept (reference)


# ===================================
# CONCEPTS
# ===================================

class Concept(BaseModel):
    """
    Concept extrait d'un topic.

    Un concept représente une entité sémantique identifiée dans le texte.
    Le type est découvert dynamiquement par le LLM selon le contexte métier.

    Exemples cross-domaines:
    - SAP/ERP: type="product" (SAP S/4HANA), type="module" (FI-CO)
    - Life Science: type="molecule" (mRNA-1273), type="pathway" (JAK-STAT)
    - Retail: type="campaign" (Black Friday), type="segment" (Gen Z Urban)
    - Cybersecurity: type="practice" (threat modeling), type="standard" (ISO 27001)
    """
    concept_id: str = Field(default_factory=lambda: f"concept_{uuid4().hex[:12]}")

    # Identification
    name: str                           # Nom du concept
    type: str                           # Type sémantique (libre, domain-agnostic)
    definition: str = ""                # Définition (peut être vide, enrichi après)
    context: str                        # Contexte d'extraction (100-200 chars)

    # Multilingue
    language: str                       # ISO 639-1 (en, fr, de, etc.) - détecté automatiquement

    # Extraction
    confidence: float = Field(ge=0.0, le=1.0)
    source_topic_id: str                # Topic source
    extraction_method: str              # NER, CLUSTERING, LLM

    # Relations
    related_concepts: List[str] = []    # Noms de concepts liés (détectés pendant extraction)

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)  # Phase 1.8.1d: Métadonnées additionnelles (slide_index, etc.)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CanonicalConcept(BaseModel):
    """
    Concept canonique unifié cross-lingual.

    Résultat de la canonicalization: plusieurs concepts similaires (même concept
    en différentes langues ou variantes) sont unifiés en un seul concept canonique.

    Exemple:
    - Concepts sources:
      * "authentication" (EN)
      * "authentification" (FR)
      * "Authentifizierung" (DE)
    - Concept canonique:
      * canonical_name: "authentication" (priorité anglais)
      * aliases: ["authentification", "Authentifizierung"]
      * languages: ["en", "fr", "de"]
    """
    canonical_id: str = Field(default_factory=lambda: f"canonical_{uuid4().hex[:12]}")

    # Identification canonique
    canonical_name: str                 # Nom canonique (priorité anglais)
    aliases: List[str]                  # Toutes variantes linguistiques
    languages: List[str]                # Langues représentées (["en", "fr", "de"])

    # Type et définition
    type: str                           # Type sémantique (libre, domain-agnostic)
    definition: str                     # Définition unifiée (fusion LLM)

    # Hiérarchie
    hierarchy_parent: Optional[str] = None      # Concept parent (ex: "Security Testing")
    hierarchy_children: List[str] = []           # Concepts enfants (ex: ["SAST", "DAST"])

    # Relations sémantiques
    related_concepts: List[str] = []    # Autres concepts liés (noms canoniques)

    # Sources
    source_concepts: List[Concept]      # Concepts sources qui ont été unifiés
    support: int                        # Nombre de mentions total (len(source_concepts))

    # Phase 1.8.1d: Traçabilité document
    document_ids: List[str] = []        # IDs documents sources (traçabilité multi-document)

    # Confidence
    confidence: float = Field(ge=0.0, le=1.0)  # Moyenne des confidences sources

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ===================================
# TOPICS
# ===================================

class Window(BaseModel):
    """Fenêtre de texte (sliding window)"""
    text: str
    start: int
    end: int


class Topic(BaseModel):
    """
    Topic sémantiquement cohérent.

    Un topic est un segment de document avec une cohésion sémantique élevée.
    Résultat du TopicSegmenter (windowing + clustering).
    """
    topic_id: str = Field(default_factory=lambda: f"topic_{uuid4().hex[:12]}")

    # Source
    document_id: str
    section_path: str                   # Ex: "1.2.3 Security Architecture"

    # Contenu
    windows: List[Window]               # Fenêtres de texte (3000 chars, 25% overlap)
    anchors: List[str]                  # Entités clés (NER) + keywords (TF-IDF)

    # Cohésion
    cohesion_score: float = Field(ge=0.0, le=1.0)  # Similarité intra-topic

    # Concepts extraits (après ConceptExtractor)
    concepts: List[Concept] = []

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ===================================
# PROFILING (Conservé - Utile pour budget allocation)
# ===================================

class ComplexityZone(BaseModel):
    """
    Zone de complexité dans le document.

    Utilisé pour budget allocation: zones complexes → plus de budget LLM.
    """
    zone_id: str = Field(default_factory=lambda: f"zone_{uuid4().hex[:8]}")
    start_position: int
    end_position: int
    complexity_score: float = Field(ge=0.0, le=1.0)
    complexity_level: Literal["simple", "medium", "complex"]
    reasoning: str
    key_concepts: List[str] = []


class SemanticProfile(BaseModel):
    """
    Profil sémantique complet d'un document.

    Résultat du SemanticDocumentProfiler.
    Utilisé pour:
    - Budget allocation (zones complexes)
    - Domain classification
    - Métriques qualité
    """
    document_id: str
    document_path: str
    tenant_id: str

    # Analyse de complexité
    overall_complexity: float = Field(ge=0.0, le=1.0)
    complexity_zones: List[ComplexityZone] = []

    # Classification domaine
    domain: str = "general"             # finance, pharma, consulting, general
    domain_confidence: float = 0.0

    # Métriques
    total_topics: int = 0
    total_concepts: int = 0
    total_canonical_concepts: int = 0
    languages_detected: List[str] = []  # ["en", "fr"] si document multilingue

    # Performance
    processing_time_ms: float = 0.0

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ===================================
# PROTO-KG (STAGING) - V2.1
# ===================================

class CandidateEntity(BaseModel):
    """
    Entité candidate pour le Proto-KG.

    Représente un CanonicalConcept en attente de validation (gatekeeper).
    Status workflow: PENDING_REVIEW → AUTO_PROMOTED | HUMAN_PROMOTED | REJECTED
    """
    candidate_id: str = Field(default_factory=lambda: f"ent_{uuid4().hex[:12]}")
    tenant_id: str

    # Identification
    canonical_name: str                 # Nom canonique
    aliases: List[str] = []             # Variantes linguistiques
    languages: List[str] = []           # Langues ["en", "fr", "de"]
    concept_type: str                   # Type concept (libre, domain-agnostic)

    # Définition
    definition: str = ""

    # Contexte source
    document_ids: List[str] = []        # Documents sources
    topic_ids: List[str] = []           # Topics sources

    # Métriques
    confidence: float = Field(ge=0.0, le=1.0)
    support: int = 1                    # Nombre mentions
    cross_lingual: bool = False         # Multi-langues?

    # Status workflow
    status: Literal["PENDING_REVIEW", "AUTO_PROMOTED", "HUMAN_PROMOTED", "REJECTED"] = "PENDING_REVIEW"
    promotion_reason: Optional[str] = None
    semantic_quality_score: float = 0.0  # Score gatekeeper

    # Métadonnées
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CandidateRelation(BaseModel):
    """
    Relation candidate pour le Proto-KG.

    Relation entre deux concepts canoniques.
    Types: PARENT_OF, CHILD_OF, RELATES_TO, USES, REQUIRES, IMPLEMENTS
    """
    candidate_id: str = Field(default_factory=lambda: f"rel_{uuid4().hex[:12]}")
    tenant_id: str

    # Identification
    source_canonical_name: str          # Concept source (canonical name)
    target_canonical_name: str          # Concept cible (canonical name)
    relation_type: str                  # PARENT_OF, CHILD_OF, RELATES_TO, etc.

    # Contexte source
    document_id: str
    topic_id: str
    context_snippet: str

    # Métriques
    confidence: float = Field(ge=0.0, le=1.0)
    strength: float = Field(ge=0.0, le=1.0)  # Force relation (embeddings similarity)

    # Status workflow
    status: Literal["PENDING_REVIEW", "AUTO_PROMOTED", "HUMAN_PROMOTED", "REJECTED"] = "PENDING_REVIEW"
    promotion_reason: Optional[str] = None

    # Métadonnées
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ===================================
# CROSS-DOCUMENT LINKING
# ===================================

class ConceptConnection(BaseModel):
    """
    Connexion concept ↔ document.

    Représente le fait qu'un document mentionne un concept avec un rôle spécifique.
    """
    connection_id: str = Field(default_factory=lambda: f"conn_{uuid4().hex[:12]}")

    # Document
    document_id: str
    document_title: str
    document_role: DocumentRole         # DEFINES, IMPLEMENTS, AUDITS, PROVES, REFERENCES

    # Concept
    canonical_concept_name: str

    # Métriques
    similarity: float = Field(ge=0.0, le=1.0)  # Similarité embeddings
    context: str                        # Contexte mention dans document

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
