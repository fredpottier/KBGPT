# Phase 2 OSMOSE - Types Relations & Metadata Layer

from enum import Enum
from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class RelationType(str, Enum):
    """Types de relations Phase 2.8 (14 types core + 3 spéciaux)"""

    # STRUCTURELLES (Hiérarchies & Taxonomies)
    PART_OF = "PART_OF"
    SUBTYPE_OF = "SUBTYPE_OF"

    # DÉPENDANCES (Fonctionnelles & Techniques)
    REQUIRES = "REQUIRES"
    USES = "USES"

    # INTÉGRATIONS (Connexions Systèmes)
    INTEGRATES_WITH = "INTEGRATES_WITH"
    EXTENDS = "EXTENDS"

    # CAPACITÉS (Fonctionnalités Activées)
    ENABLES = "ENABLES"

    # TEMPORELLES (Évolution & Cycles de Vie)
    VERSION_OF = "VERSION_OF"
    PRECEDES = "PRECEDES"
    REPLACES = "REPLACES"
    DEPRECATES = "DEPRECATES"

    # VARIANTES (Alternatives & Compétition)
    ALTERNATIVE_TO = "ALTERNATIVE_TO"

    # GOUVERNANCE / SCOPE (Phase 2.8)
    APPLIES_TO = "APPLIES_TO"

    # CAUSALITÉ / CONTRAINTE (Phase 2.10)
    CAUSES = "CAUSES"
    PREVENTS = "PREVENTS"

    # TYPES SPÉCIAUX (Phase 2.8)
    UNKNOWN = "UNKNOWN"  # Non mappé - conserve predicate_raw
    ASSOCIATED_WITH = "ASSOCIATED_WITH"  # Lien faible confirmé
    CONFLICTS_WITH = "CONFLICTS_WITH"  # Contradiction détectée


class ExtractionMethod(str, Enum):
    """Méthode extraction utilisée"""
    PATTERN = "pattern"  # Pattern-based (regex + spaCy)
    LLM = "llm"  # LLM-assisted seul
    HYBRID = "hybrid"  # Pattern + LLM
    INFERRED = "inferred"  # Inférence transitive


class RelationStrength(str, Enum):
    """Force de la relation"""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class RelationStatus(str, Enum):
    """Statut de la relation"""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    INFERRED = "inferred"


class RelationMetadata(BaseModel):
    """Metadata layer pour relations Neo4j"""

    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score [0.0-1.0]")
    extraction_method: ExtractionMethod
    source_doc_id: str
    source_chunk_ids: List[str] = Field(default_factory=list)
    language: str = Field(default="EN", description="Langue détection (EN, FR, DE, ES)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    valid_from: Optional[date] = Field(default=None, description="Validité temporelle début")
    valid_until: Optional[date] = Field(default=None, description="Validité temporelle fin")
    strength: RelationStrength = Field(default=RelationStrength.MODERATE)
    status: RelationStatus = Field(default=RelationStatus.ACTIVE)
    require_validation: bool = Field(default=False, description="True pour ENABLES Phase 2.5")

    # Métadonnées spécifiques REPLACES
    breaking_changes: Optional[List[str]] = Field(default=None)
    migration_effort: Optional[str] = Field(default=None, description="LOW|MEDIUM|HIGH")
    backward_compatible: Optional[bool] = Field(default=None)

    # Métadonnées temporelles (VERSION_OF, PRECEDES, REPLACES, DEPRECATES)
    timeline_position: Optional[int] = Field(default=None, description="Position dans séquence chronologique")
    release_date: Optional[date] = Field(default=None)
    eol_date: Optional[date] = Field(default=None, description="End of Life (pour DEPRECATES)")


class TypedRelation(BaseModel):
    """Relation typée extraite entre deux concepts"""

    relation_id: str = Field(description="Identifiant unique relation")
    source_concept: str = Field(description="Concept source (A)")
    target_concept: str = Field(description="Concept target (B)")
    relation_type: RelationType
    metadata: RelationMetadata

    # Justification
    evidence: Optional[str] = Field(default=None, description="Snippet textuel justification")
    context: Optional[str] = Field(default=None, description="Context chunk complet")

    class Config:
        use_enum_values = True


class RelationExtractionResult(BaseModel):
    """Résultat extraction relations pour un document"""

    document_id: str
    relations: List[TypedRelation]
    extraction_time_seconds: float
    total_relations_extracted: int
    relations_by_type: dict[RelationType, int]
    extraction_method_stats: dict[ExtractionMethod, int]


# =============================================================================
# Phase 2.8 - RawAssertion + CanonicalRelation (Architecture 2-Layer)
# =============================================================================

class RelationMaturity(str, Enum):
    """Niveau de maturité d'une relation (Phase 2.8 + 2.10)"""
    CANDIDATE = "CANDIDATE"           # Extraite mais non validée
    VALIDATED = "VALIDATED"           # Validée par diversité sources ou définition explicite
    REJECTED = "REJECTED"             # Rejetée (confidence trop faible)
    CONFLICTING = "CONFLICTING"       # Assertions contradictoires détectées (renommé de CONFLICTED)
    # Phase 2.10 - Nouveaux états
    AMBIGUOUS_TYPE = "AMBIGUOUS_TYPE"     # type_confidence ≈ alt_type_confidence (delta < 0.15)
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"  # conditional_ratio > 0.70


class RawAssertionFlags(BaseModel):
    """Flags sémantiques pour une assertion (Phase 2.8)"""
    is_negated: bool = Field(default=False, description="Assertion négative")
    is_hedged: bool = Field(default=False, description="Assertion incertaine (may, might, could)")
    is_conditional: bool = Field(default=False, description="Assertion conditionnelle (if, when)")
    cross_sentence: bool = Field(default=False, description="Relation extraite sur plusieurs phrases")


class RawAssertion(BaseModel):
    """
    Assertion relationnelle brute extraite d'un chunk (Phase 2.8).

    Journal append-only, immuable. Source of truth pour reconsolidation.
    """

    # Identité
    raw_assertion_id: str = Field(description="ULID unique")
    tenant_id: str = Field(default="default")
    raw_fingerprint: str = Field(description="Hash pour dédup: sha1(tenant|doc|chunk|subject|object|predicate|evidence)")

    # Extraction - Prédicat brut
    predicate_raw: str = Field(description="Prédicat brut extrait (ex: 'requires', 'governs')")
    predicate_norm: str = Field(description="Prédicat normalisé (lower/trim/hyphen)")

    # Phase 2.10 - Typing fermé à l'extraction
    relation_type: Optional[RelationType] = Field(
        default=None,
        description="Type de relation choisi par le LLM (V3) ou mappé post-hoc (V2)"
    )
    type_confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Confiance du LLM sur le type choisi"
    )
    alt_type: Optional[RelationType] = Field(
        default=None,
        description="Type alternatif si ambiguïté réelle"
    )
    alt_type_confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Confiance sur le type alternatif"
    )
    relation_subtype_raw: Optional[str] = Field(
        default=None,
        description="Nuance sémantique fine (ex: 'requires compliance with') - audit only"
    )
    context_hint: Optional[str] = Field(
        default=None,
        description="Scope/contexte local extrait (ex: 'for medical devices')"
    )

    # Concepts (dénormalisés pour perf ETL)
    subject_concept_id: str = Field(description="ID concept source")
    object_concept_id: str = Field(description="ID concept cible")
    subject_surface_form: Optional[str] = Field(default=None, description="Forme trouvée dans le texte")
    object_surface_form: Optional[str] = Field(default=None, description="Forme trouvée dans le texte")

    # Evidence
    evidence_text: str = Field(description="Phrase source justifiant la relation")
    evidence_span_start: Optional[int] = Field(default=None)
    evidence_span_end: Optional[int] = Field(default=None)

    # Scores
    confidence_extractor: float = Field(ge=0.0, le=1.0, description="Confidence LLM/pattern")
    quality_penalty: float = Field(default=0.0, description="Pénalité qualité (négatif)")
    confidence_final: float = Field(ge=0.0, le=1.0, description="confidence_extractor + quality_penalty clippé")

    # Flags sémantiques
    flags: RawAssertionFlags = Field(default_factory=RawAssertionFlags)

    # Source
    source_doc_id: str
    source_chunk_id: str
    source_segment_id: Optional[str] = Field(default=None, description="Ex: slide_7")
    source_language: str = Field(default="en")

    # Traçabilité
    extractor_name: str = Field(default="llm_relation_extractor")
    extractor_version: str = Field(default="v1.0.0")
    prompt_hash: Optional[str] = Field(default=None, description="Hash du prompt utilisé")
    model_used: Optional[str] = Field(default=None, description="Ex: gpt-4o-mini")
    schema_version: str = Field(default="2.10.0")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class PredicateProfile(BaseModel):
    """Profil des prédicats pour une CanonicalRelation (Phase 2.8)"""
    top_predicates_raw: List[str] = Field(default_factory=list, description="Top prédicats bruts")
    predicate_cluster_id: Optional[str] = Field(default=None, description="ID cluster dominant")
    cluster_label_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class CanonicalRelation(BaseModel):
    """
    Relation canonique agrégée (Phase 2.8).

    Vue reconstruite à partir des RawAssertions. Clé: (subject, object, predicate_norm).
    """

    # Identité (hash stable)
    canonical_relation_id: str = Field(description="sha1(tenant|subject|predicate_norm|object)[:16]")
    tenant_id: str = Field(default="default")

    # Relation normalisée
    relation_type: RelationType = Field(description="Inferred or explicit relation type category")
    predicate_norm: str = Field(default="", description="Normalized predicate - grouping key")
    subject_concept_id: str = Field(description="Cache - source of truth = edges RELATES_FROM")
    object_concept_id: str = Field(description="Cache - source of truth = edges RELATES_TO")

    # Agrégation
    distinct_documents: int = Field(default=0)
    distinct_chunks: int = Field(default=0)
    total_assertions: int = Field(default=0)
    first_seen_utc: datetime = Field(default_factory=datetime.utcnow)
    last_seen_utc: datetime = Field(default_factory=datetime.utcnow)
    extractor_versions: List[str] = Field(default_factory=list)

    # Profil prédicats
    predicate_profile: PredicateProfile = Field(default_factory=PredicateProfile)

    # Scores agrégés
    confidence_mean: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_p50: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # Maturité
    maturity: RelationMaturity = Field(default=RelationMaturity.CANDIDATE)
    status: RelationStatus = Field(default=RelationStatus.ACTIVE)

    # Versioning
    mapping_version: str = Field(default="v1.0")
    last_rebuilt_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# =============================================================================
# Phase 2.11 - RawClaim + CanonicalClaim (Assertions Unaires)
# =============================================================================

class ClaimValueType(str, Enum):
    """Type de valeur d'un claim"""
    PERCENTAGE = "percentage"    # 99.7%, 15%
    NUMBER = "number"            # 64, 10000
    CURRENCY = "currency"        # 500€, $1000
    BOOLEAN = "boolean"          # true, false, enabled, disabled
    TEXT = "text"                # ISO 27001, Enterprise Edition
    DURATION = "duration"        # 4h, 30 days, < 200ms
    VERSION = "version"          # v2.3.1, 2024 Q2
    DATE = "date"                # 2024-01-15


class ClaimMaturity(str, Enum):
    """Maturité épistémique d'un CanonicalClaim"""
    VALIDATED = "VALIDATED"               # Multi-source, cohérent
    CANDIDATE = "CANDIDATE"               # Source unique
    CONFLICTING = "CONFLICTING"           # Valeurs contradictoires
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"  # Dépend du contexte
    SUPERSEDED = "SUPERSEDED"             # Remplacé par version plus récente


class RawClaimFlags(BaseModel):
    """Flags pour qualifier un RawClaim (Phase 2.11)"""
    negated: bool = Field(default=False, description="Le claim nie explicitement")
    hedged: bool = Field(default=False, description="Incertitude (environ, approximativement)")
    conditional: bool = Field(default=False, description="Condition (si option X)")
    ambiguous_scope: bool = Field(default=False, description="Scope mal défini")


class RawClaim(BaseModel):
    """
    Assertion unaire brute extraite d'un document (Phase 2.11).

    Un claim est une assertion de fait sur un sujet : Subject → Attribut = Valeur
    Exemple: "Le SLA de S/4HANA est 99.7%" → sujet=S/4HANA, type=SLA_AVAILABILITY, value=99.7%
    """

    # Identifiants
    raw_claim_id: str = Field(description="ULID unique")
    tenant_id: str = Field(default="default")
    raw_fingerprint: str = Field(description="Hash dédup: sha1(tenant|doc|subject|claim_type|scope_key|value)")

    # Sujet
    subject_concept_id: str = Field(description="ID du concept concerné")
    subject_surface_form: Optional[str] = Field(default=None, description="Texte original dans le doc")

    # Claim
    claim_type: str = Field(description="Type de claim (SLA_AVAILABILITY, THRESHOLD, PRICING, etc.)")
    value_raw: str = Field(description="Valeur brute (ex: '99.7%', '64 Go')")
    value_type: ClaimValueType = Field(description="Type de valeur")
    value_numeric: Optional[float] = Field(default=None, description="Valeur numérique si applicable")
    unit: Optional[str] = Field(default=None, description="Unité (%, Go, €, ms, etc.)")

    # Scope (contexte d'applicabilité)
    scope_raw: str = Field(default="", description="Texte libre du scope (audit)")
    scope_struct: dict = Field(default_factory=dict, description="Clé/valeur extensible")
    scope_key: str = Field(default="", description="Hash canonique du scope_struct pour groupement")

    # Temporalité
    valid_time_hint: Optional[str] = Field(default=None, description="Indication temporelle (Q4 2023, depuis v2.0)")

    # Provenance
    source_doc_id: str
    source_chunk_id: str
    source_segment_id: Optional[str] = Field(default=None)
    evidence_text: str = Field(description="Citation exacte justifiant le claim")
    page_number: Optional[int] = Field(default=None)

    # Qualité
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence extraction")
    flags: RawClaimFlags = Field(default_factory=RawClaimFlags)

    # Traçabilité
    extractor_name: str = Field(default="llm_claim_extractor")
    extractor_version: str = Field(default="v1.0.0")
    model_used: Optional[str] = Field(default=None)
    schema_version: str = Field(default="2.11.0")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class ClaimSource(BaseModel):
    """Source d'un claim consolidé"""
    document_id: str
    excerpt: str
    page_number: Optional[int] = None
    date: Optional[date] = None


class CanonicalClaim(BaseModel):
    """
    Claim consolidé et canonique (Phase 2.11).

    Vue agrégée à partir des RawClaims. Clé: (subject, claim_type, scope_key).
    """

    # Identifiants
    canonical_claim_id: str = Field(description="Hash stable: sha1(tenant|subject|claim_type|scope_key)[:16]")
    tenant_id: str = Field(default="default")

    # Sujet
    subject_concept_id: str = Field(description="Concept canonique")

    # Claim canonique
    claim_type: str = Field(description="Type normalisé")
    value: str = Field(description="Valeur canonique (normalisée)")
    value_numeric: Optional[float] = Field(default=None, description="Valeur numérique si applicable")
    unit: Optional[str] = Field(default=None, description="Unité normalisée")
    value_type: ClaimValueType = Field(default=ClaimValueType.TEXT)

    # Scope structuré
    scope_struct: dict = Field(default_factory=dict, description="Clé/valeur extensible")
    scope_key: str = Field(description="Hash canonique pour groupement")

    # Temporalité
    valid_from: Optional[date] = Field(default=None)
    valid_until: Optional[date] = Field(default=None)

    # Multi-sourcing
    distinct_documents: int = Field(default=0)
    total_assertions: int = Field(default=0, description="Nombre de RawClaims")
    confidence_p50: float = Field(default=0.0, ge=0.0, le=1.0, description="Médiane des confidences")

    # Maturité
    maturity: ClaimMaturity = Field(default=ClaimMaturity.CANDIDATE)
    status: str = Field(default="active", description="active | superseded | deprecated")

    # Relations entre claims
    conflicts_with: List[str] = Field(default_factory=list, description="IDs des claims en conflit")
    refines: Optional[str] = Field(default=None, description="ID du claim parent (sous-scope)")
    supersedes: Optional[str] = Field(default=None, description="ID du claim remplacé (temporel)")

    # Sources
    sources: List[ClaimSource] = Field(default_factory=list)

    # Métadonnées
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_utc: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
