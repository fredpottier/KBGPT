# Phase 2 OSMOSE - Types Relations & Metadata Layer
# Phase 2.11 - Ajout SupportSpan et CorefResolutionPath pour intégration Pass 0.5

from enum import Enum
from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class RelationType(str, Enum):
    """
    Types de relations Phase 2.8+ (18 types core + 3 spéciaux).

    ADR 2024-12-30: 12 prédicats du set fermé pour Pass 2:
    defines, requires, enables, prevents, causes, applies_to,
    part_of, depends_on (alias REQUIRES), mitigates, conflicts_with,
    example_of, governed_by
    """

    # STRUCTURELLES (Hiérarchies & Taxonomies)
    PART_OF = "PART_OF"
    SUBTYPE_OF = "SUBTYPE_OF"

    # DÉPENDANCES (Fonctionnelles & Techniques)
    REQUIRES = "REQUIRES"  # Inclut "depends_on" comme alias
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
    ALTERNATIVE_TO = "ALTERNATIVE_TO"  # Substituabilité explicite ("instead of", "replaces")
    CHOICE_BETWEEN = "CHOICE_BETWEEN"  # ADR Discursive: choice-set linguistique ("X or Y")

    # GOUVERNANCE / SCOPE (Phase 2.8)
    APPLIES_TO = "APPLIES_TO"
    GOVERNED_BY = "GOVERNED_BY"  # ADR 2024-12-30: régulation

    # CAUSALITÉ / CONTRAINTE (Phase 2.10)
    CAUSES = "CAUSES"
    PREVENTS = "PREVENTS"
    MITIGATES = "MITIGATES"  # ADR 2024-12-30: atténuation risque

    # DÉFINITIONNEL (ADR 2024-12-30)
    DEFINES = "DEFINES"  # A defines B

    # INSTANCE (ADR 2024-12-30)
    EXAMPLE_OF = "EXAMPLE_OF"  # A is an example of B

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


# =============================================================================
# ADR Relations Discursivement Déterminées - Enums
# =============================================================================

class AssertionKind(str, Enum):
    """
    Mode d'obtention d'une assertion.

    Ref: ADR_DISCURSIVE_RELATIONS.md

    - EXPLICIT: la relation est directement exprimée comme énoncé relationnel dans le texte
    - DISCURSIVE: la relation est reconstructible par un lecteur rigoureux à partir des
                  preuves fournies, sans connaissance externe, inférence transitive,
                  ou complétion causale
    """
    EXPLICIT = "EXPLICIT"      # Relation directement exprimée
    DISCURSIVE = "DISCURSIVE"  # Reconstructible sans ajout externe


class DiscursiveBasis(str, Enum):
    """
    Base textuelle rendant une assertion discursive déterminable.

    Les assertions discursives DOIVENT déclarer la base textuelle qui les rend déterminables.

    Bases déterministes fortes (→ STRICT): ALTERNATIVE, DEFAULT, EXCEPTION
    Bases moins déterministes (→ STRICT si bundle fort, sinon EXTENDED): SCOPE, COREF, ENUMERATION

    Ref: ADR_DISCURSIVE_RELATIONS.md
    """
    ALTERNATIVE = "ALTERNATIVE"   # "X ou Y" explicite (or, either...or)
    DEFAULT = "DEFAULT"           # Comportement par défaut (by default, par défaut)
    EXCEPTION = "EXCEPTION"       # "sauf si", "à moins que" (unless, except)
    SCOPE = "SCOPE"               # Maintien de portée entre spans
    COREF = "COREF"               # Résolution référentielle (pronoms)
    ENUMERATION = "ENUMERATION"   # Listes explicites


class DiscursiveAbstainReason(str, Enum):
    """
    Raison structurée pour un ABSTAIN sur une assertion discursive.

    Tout ABSTAIN doit être motivé par une raison structurée pour la gouvernance.

    Ref: ADR_DISCURSIVE_RELATIONS.md, ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md
    """
    # Raisons générales
    WEAK_BUNDLE = "WEAK_BUNDLE"                     # Bundle trop court/peu diversifié
    SCOPE_BREAK = "SCOPE_BREAK"                     # Rupture de portée référentielle (structural)
    COREF_UNRESOLVED = "COREF_UNRESOLVED"           # Coréférence non résolue
    TYPE2_RISK = "TYPE2_RISK"                       # Risque de relation déduite (Type 2)
    WHITELIST_VIOLATION = "WHITELIST_VIOLATION"    # RelationType interdit pour DISCURSIVE
    AMBIGUOUS_PREDICATE = "AMBIGUOUS_PREDICATE"    # Prédicat ambigu

    # ADR SCOPE - Niveau Miner (déterministe, sans LLM)
    NO_SCOPE_SETTER = "NO_SCOPE_SETTER"            # Section sans scope_setter valide
    NO_BRIDGE_EVIDENCE = "NO_BRIDGE_EVIDENCE"      # Pas de phrase/fenêtre contenant A et B ensemble

    # ADR SCOPE - Niveau Verifier (LLM)
    SCOPE_BREAK_LINGUISTIC = "SCOPE_BREAK_LINGUISTIC"  # Rupture de portée linguistique détectée


class SemanticGrade(str, Enum):
    """
    Grade indiquant la nature des preuves d'une SemanticRelation.

    Purement descriptif - n'implique aucune hiérarchie de fiabilité.
    Indique l'origine des preuves, pas leur qualité.

    Ref: ADR_DISCURSIVE_RELATIONS.md
    """
    EXPLICIT = "EXPLICIT"      # Uniquement des preuves EXPLICIT
    DISCURSIVE = "DISCURSIVE"  # Uniquement des preuves DISCURSIVE
    MIXED = "MIXED"            # Combinaison EXPLICIT + DISCURSIVE


class DefensibilityTier(str, Enum):
    """
    Tier de défendabilité d'une relation pour le filtrage runtime.

    STRICT ≠ EXPLICIT. Le terme "Strict" réfère à la défendabilité épistémique,
    pas à la méthode d'extraction. Une traversée Strict inclut toute relation dont
    l'existence est pleinement défendable à partir du texte.

    Ref: ADR_DISCURSIVE_RELATIONS.md
    """
    STRICT = "STRICT"           # Utilisable en mode strict (production)
    EXTENDED = "EXTENDED"       # Utilisable en mode élargi (exploration)
    EXPERIMENTAL = "EXPERIMENTAL"  # Réservé (INFERRED, hors scope V1)


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
    # ADR_GRAPH_FIRST_ARCHITECTURE Phase A: Lien vers Navigation Layer
    evidence_context_ids: List[str] = Field(
        default_factory=list,
        description="context_id des SectionContext où l'evidence a été trouvée (ex: sec:doc1:hash1)"
    )
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


# =============================================================================
# Phase 2.11 - AnchorType et SupportSpan (Intégration Pass 0.5 Coreference)
# =============================================================================

class AnchorType(str, Enum):
    """
    Type d'ancrage d'un concept dans une assertion.

    Distingue l'ancrage lexical (direct) de l'ancrage référentiel (via coréférence).

    - LEXICAL: Le texte nomme explicitement le concept ("TLS", "S/4HANA")
    - REFERENTIAL: Le texte réfère au concept via pronom/anaphore ("Il" → TLS)

    Ref: ADR Linguistic Coreference Layer (Pass 0.5)
    """
    LEXICAL = "LEXICAL"        # Le texte nomme explicitement le concept
    REFERENTIAL = "REFERENTIAL"  # Le texte réfère au concept via pronom/anaphore


class SupportSpanModel(BaseModel):
    """
    Span de support référentiel pour un sujet/objet pronominal (Pydantic).

    Quand une assertion a un sujet/objet pronominal (ex: "Il sécurise..."),
    le SupportSpan capture:
    - Le span exact du pronom dans le texte (evidence intacte)
    - L'ID du MentionSpan correspondant dans le CorefGraph
    - Le type d'ancrage (toujours REFERENTIAL pour un SupportSpan)

    Invariants respectés:
    - L1: Evidence-preserving (span exact, pas de réécriture)
    - L5: Chemin de résolution auditable

    Ref: ADR Linguistic Coreference Layer (Pass 0.5)
    """
    span_start: int = Field(description="Position début du pronom dans le texte")
    span_end: int = Field(description="Position fin du pronom dans le texte")
    surface_form: str = Field(description="Forme de surface du pronom (Il, elle, it, etc.)")
    mention_span_id: str = Field(description="ID du MentionSpan dans le CorefGraph")
    anchor_type: AnchorType = Field(default=AnchorType.REFERENTIAL, description="Toujours REFERENTIAL")
    mention_type: Optional[str] = Field(default=None, description="Type de mention (PRONOUN, NP, etc.)")
    sentence_index: Optional[int] = Field(default=None, description="Index de la phrase")

    class Config:
        use_enum_values = True


class CorefResolutionStepModel(BaseModel):
    """
    Étape dans le chemin de résolution de coréférence (Pydantic).

    Trace un pas dans la chaîne: MentionSpan(Il) → CorefLink → MentionSpan(TLS)
    """
    step_type: str = Field(description="Type d'étape: COREF_LINK | COREF_DECISION | CHAIN_MEMBERSHIP")
    source_id: str = Field(description="ID du noeud source")
    target_id: str = Field(description="ID du noeud cible")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confiance de l'étape")
    method: str = Field(default="", description="Méthode: spacy_coref | coreferee | rule_based | llm_arbiter")


class CorefResolutionPathModel(BaseModel):
    """
    Chemin complet de résolution de coréférence (Pydantic).

    Trace comment un pronom a été résolu vers un concept:
    MentionSpan("Il") → CorefLink → MentionSpan("TLS") → ProtoConcept(TLS)

    Ce chemin est la preuve auditable que la résolution est légitime
    et non une inférence sémantique inventée.

    Exemple:
        - source_mention_id: "mention_il_001"
        - target_mention_id: "mention_tls_001"
        - resolved_concept_id: "proto_tls_001"
        - steps: [CorefResolutionStepModel(COREF_LINK, ...)]
        - resolution_confidence: 0.92
    """
    # Point de départ (pronom/anaphore)
    source_mention_id: str = Field(description="ID du MentionSpan source")
    source_surface: str = Field(description="Surface du pronom (ex: 'Il')")

    # Point d'arrivée (mention lexicale)
    target_mention_id: str = Field(description="ID du MentionSpan cible")
    target_surface: str = Field(description="Surface de la mention cible (ex: 'TLS')")

    # Concept résolu
    resolved_concept_id: str = Field(description="ID du concept résolu")
    resolved_concept_name: str = Field(description="Nom du concept résolu")

    # Chemin de résolution (audit trail)
    steps: List[CorefResolutionStepModel] = Field(default_factory=list, description="Étapes de résolution")

    # Confiance globale de la résolution
    resolution_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confiance globale")

    # Méthode utilisée
    resolution_method: str = Field(default="", description="spacy_coref | coreferee | rule_based | hybrid")

    # Flags d'audit
    is_ambiguous: bool = Field(default=False, description="True si plusieurs candidats possibles")
    abstained: bool = Field(default=False, description="True si résolution impossible (abstention)")


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

    # ==========================================================================
    # Phase 2.11 - Support Spans pour sujets/objets pronominaux (Pass 0.5)
    # ==========================================================================

    # Type d'ancrage pour le sujet et l'objet
    subject_anchor_type: AnchorType = Field(
        default=AnchorType.LEXICAL,
        description="Type d'ancrage du sujet: LEXICAL (direct) ou REFERENTIAL (via coréférence)"
    )
    object_anchor_type: AnchorType = Field(
        default=AnchorType.LEXICAL,
        description="Type d'ancrage de l'objet: LEXICAL (direct) ou REFERENTIAL (via coréférence)"
    )

    # Support spans (si sujet/objet pronominal)
    # Contient le span exact du pronom dans le texte
    subject_support_span: Optional[SupportSpanModel] = Field(
        default=None,
        description="Si sujet pronominal, span du pronom et lien vers MentionSpan"
    )
    object_support_span: Optional[SupportSpanModel] = Field(
        default=None,
        description="Si objet pronominal, span du pronom et lien vers MentionSpan"
    )

    # Chemins de résolution coréférence (audit trail)
    # Trace comment le pronom a été résolu vers le concept
    subject_resolution_path: Optional[CorefResolutionPathModel] = Field(
        default=None,
        description="Chemin de résolution coréf pour sujet pronominal"
    )
    object_resolution_path: Optional[CorefResolutionPathModel] = Field(
        default=None,
        description="Chemin de résolution coréf pour objet pronominal"
    )

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

    # ==========================================================================
    # ADR Relations Discursivement Déterminées - Champs
    # ==========================================================================

    assertion_kind: AssertionKind = Field(
        default=AssertionKind.EXPLICIT,
        description="Mode d'obtention: EXPLICIT (direct) ou DISCURSIVE (reconstructible)"
    )
    discursive_basis: List[DiscursiveBasis] = Field(
        default_factory=list,
        description="Base(s) textuelle(s) rendant l'assertion discursive déterminable"
    )
    abstain_reason: Optional[DiscursiveAbstainReason] = Field(
        default=None,
        description="Si ABSTAIN, raison structurée pour la gouvernance"
    )

    # Source
    source_doc_id: str
    source_chunk_id: str
    source_segment_id: Optional[str] = Field(default=None, description="Ex: slide_7")
    source_language: str = Field(default="en")

    # ADR_GRAPH_FIRST_ARCHITECTURE Phase B: Lien vers Navigation Layer
    evidence_context_ids: List[str] = Field(
        default_factory=list,
        description="context_id des SectionContext où l'evidence a été trouvée (ex: sec:doc1:hash1)"
    )

    # Traçabilité
    extractor_name: str = Field(default="llm_relation_extractor")
    extractor_version: str = Field(default="v1.0.0")
    prompt_hash: Optional[str] = Field(default=None, description="Hash du prompt utilisé")
    model_used: Optional[str] = Field(default=None, description="Ex: gpt-4o-mini")
    schema_version: str = Field(default="2.12.0")  # ADR Relations Discursivement Déterminées
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

    # ADR Relations Discursivement Déterminées - Compteurs séparés
    explicit_support_count: int = Field(
        default=0,
        description="Nombre de RawAssertion EXPLICIT supportant cette relation"
    )
    discursive_support_count: int = Field(
        default=0,
        description="Nombre de RawAssertion DISCURSIVE supportant cette relation"
    )
    distinct_sections: int = Field(
        default=0,
        description="Nombre de SectionContext distincts (pour bundle_diversity)"
    )

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
# ADR Relations Discursivement Déterminées - SemanticRelation
# =============================================================================

class SupportStrength(BaseModel):
    """
    Métriques agrégées pour évaluer la force d'une CanonicalRelation.

    Utilisé pour décider de la promotion vers SemanticRelation et
    l'attribution du DefensibilityTier.

    Ref: ADR_DISCURSIVE_RELATIONS.md
    """
    support_count: int = Field(default=0, description="Nombre total de RawAssertion")
    explicit_count: int = Field(default=0, description="Nombre de RawAssertion EXPLICIT")
    discursive_count: int = Field(default=0, description="Nombre de RawAssertion DISCURSIVE")
    doc_coverage: int = Field(default=0, description="Nombre de documents distincts")
    distinct_sections: int = Field(default=0, description="Nombre de SectionContext distincts")
    bundle_diversity: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Score de diversité: min(1.0, distinct_sections / 3)"
    )


class SemanticRelation(BaseModel):
    """
    Relation sémantique promue, traversable par le runtime Graph-First.

    Troisième couche du pipeline: RawAssertion → CanonicalRelation → SemanticRelation

    Porte:
    - semantic_grade: transparence sur l'origine des preuves (EXPLICIT/DISCURSIVE/MIXED)
    - defensibility_tier: autorisation d'usage runtime (STRICT/EXTENDED)

    Le runtime STRICT traverse les relations défendables (defensibility_tier=STRICT),
    indépendamment de leur semantic_grade.

    Ref: ADR_DISCURSIVE_RELATIONS.md
    """

    # Identité
    semantic_relation_id: str = Field(description="ULID unique")
    canonical_relation_id: str = Field(description="ID de la CanonicalRelation source")
    tenant_id: str = Field(default="default")

    # Relation
    relation_type: RelationType = Field(description="Type de relation")
    subject_concept_id: str = Field(description="ID concept source")
    object_concept_id: str = Field(description="ID concept cible")

    # ADR Relations Discursivement Déterminées
    semantic_grade: SemanticGrade = Field(
        description="Nature des preuves: EXPLICIT, DISCURSIVE, ou MIXED (transparence)"
    )
    defensibility_tier: DefensibilityTier = Field(
        description="Tier de défendabilité: STRICT (production) ou EXTENDED (exploration)"
    )

    # Métriques de support (snapshot à la promotion)
    support_strength: SupportStrength = Field(
        default_factory=SupportStrength,
        description="Métriques de support au moment de la promotion"
    )

    # Scores
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence agrégée")

    # Traçabilité
    promoted_at: datetime = Field(default_factory=datetime.utcnow)
    promotion_reason: Optional[str] = Field(
        default=None,
        description="Raison de la promotion (pour audit)"
    )

    class Config:
        use_enum_values = True


def compute_semantic_grade(explicit_count: int, discursive_count: int) -> SemanticGrade:
    """
    Calcule le SemanticGrade à partir des compteurs.

    - Si explicit_count > 0 et discursive_count == 0 → EXPLICIT
    - Si explicit_count == 0 et discursive_count > 0 → DISCURSIVE
    - Si explicit_count > 0 et discursive_count > 0 → MIXED
    """
    if explicit_count > 0 and discursive_count == 0:
        return SemanticGrade.EXPLICIT
    elif explicit_count == 0 and discursive_count > 0:
        return SemanticGrade.DISCURSIVE
    else:
        return SemanticGrade.MIXED


def compute_bundle_diversity(distinct_sections: int) -> float:
    """
    Calcule bundle_diversity de façon déterministe.

    bundle_diversity = min(1.0, distinct_sections / 3)

    | Sections | diversity |
    |----------|-----------|
    | 1        | 0.33      |
    | 2        | 0.66      |
    | ≥ 3      | 1.0       |
    """
    return min(1.0, distinct_sections / 3)


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


# =============================================================================
# ADR SCOPE Discursive Candidate Mining - Structures de données
# =============================================================================

class EvidenceSpanRole(str, Enum):
    """
    Rôle d'un span dans un EvidenceBundle SCOPE.

    Ref: ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md
    """
    SCOPE_SETTER = "SCOPE_SETTER"   # DocItem définissant le scope (heading ou premier)
    MENTION = "MENTION"              # DocItem contenant une mention de concept
    BRIDGE = "BRIDGE"                # DocItem contenant BOTH concepts A et B (phrase pont)


class EvidenceSpan(BaseModel):
    """
    Span de preuve unitaire pour une assertion SCOPE.

    Ref: ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md - INV-SCOPE-03

    Un EvidenceBundle SCOPE doit contenir ≥2 EvidenceSpans distincts.
    """
    doc_item_id: str = Field(description="ID du DocItem dans Neo4j")
    role: EvidenceSpanRole = Field(description="Rôle du span: SCOPE_SETTER ou MENTION")
    text_excerpt: str = Field(description="Extrait textuel (pour audit)")
    concept_id: Optional[str] = Field(
        default=None,
        description="ID du concept mentionné (si role=MENTION)"
    )
    concept_surface_form: Optional[str] = Field(
        default=None,
        description="Forme de surface du concept dans le texte"
    )

    class Config:
        use_enum_values = True


class EvidenceBundle(BaseModel):
    """
    Bundle de preuves multi-span pour une assertion SCOPE.

    Ref: ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md

    Invariants:
    - INV-SCOPE-03: ≥2 DocItems distincts obligatoires
    - Le bundle est sérialisé en JSON dans RawAssertion.evidence_bundle (pas de nœud)

    Bridge sentence:
    - Un span BRIDGE contient BOTH concepts A et B dans le même DocItem
    - C'est l'évidence la plus forte pour la vérification LLM
    - Si has_bridge=False, le LLM aura du mal à trouver un marqueur explicite
    """
    basis: DiscursiveBasis = Field(
        default=DiscursiveBasis.SCOPE,
        description="Base discursive (toujours SCOPE pour ce type)"
    )
    spans: List[EvidenceSpan] = Field(
        description="Liste des spans (≥2 obligatoire)"
    )
    section_id: str = Field(description="ID de la section source")
    document_id: str = Field(description="ID du document source")
    has_bridge: bool = Field(
        default=False,
        description="True si un span BRIDGE (A+B ensemble) a été trouvé"
    )

    def is_valid(self) -> bool:
        """Vérifie INV-SCOPE-03: ≥2 DocItems distincts."""
        unique_doc_items = {span.doc_item_id for span in self.spans}
        return len(unique_doc_items) >= 2

    def get_scope_setter(self) -> Optional[EvidenceSpan]:
        """Retourne le span SCOPE_SETTER."""
        for span in self.spans:
            if span.role == EvidenceSpanRole.SCOPE_SETTER:
                return span
        return None

    def get_bridge(self) -> Optional[EvidenceSpan]:
        """Retourne le span BRIDGE (contenant A ET B) si présent."""
        for span in self.spans:
            if span.role == EvidenceSpanRole.BRIDGE:
                return span
        return None

    def get_mentions(self) -> List[EvidenceSpan]:
        """Retourne les spans MENTION."""
        return [s for s in self.spans if s.role == EvidenceSpanRole.MENTION]

    def to_json(self) -> str:
        """Sérialise pour stockage dans RawAssertion."""
        import json
        return json.dumps(self.model_dump(), default=str)

    class Config:
        use_enum_values = True


class CandidatePairStatus(str, Enum):
    """
    Statut d'un CandidatePair dans le pipeline SCOPE.

    Ref: ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md
    """
    PENDING = "PENDING"           # En attente de vérification
    VERIFIED = "VERIFIED"         # Vérifié par LLM → RawAssertion créée
    ABSTAINED = "ABSTAINED"       # ABSTAIN (Miner ou Verifier)
    REJECTED = "REJECTED"         # Rejeté par validation (C3bis, C4, INV-SEP)


class CandidatePair(BaseModel):
    """
    Paire de concepts candidate générée par SCOPE mining.

    Ref: ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md

    Sortie du Miner, entrée du Verifier.

    Invariants:
    - INV-SCOPE-01: Ce n'est PAS une relation, c'est un candidat à vérifier
    - INV-SCOPE-04: Si abstained, abstain_reason doit être renseigné
    """
    # Identité
    candidate_id: str = Field(description="ULID unique du candidat")

    # Concepts (pivot, other)
    pivot_concept_id: str = Field(description="ID du concept pivot (plus saillant)")
    other_concept_id: str = Field(description="ID de l'autre concept")
    pivot_surface_form: Optional[str] = Field(default=None)
    other_surface_form: Optional[str] = Field(default=None)

    # Evidence
    evidence_bundle: EvidenceBundle = Field(description="Bundle de preuves multi-span")

    # Contexte
    section_id: str = Field(description="ID de la section source")
    document_id: str = Field(description="ID du document source")

    # Salience (pour audit)
    pivot_salience_score: float = Field(
        default=0.0, ge=0.0,
        description="Score de saillance du pivot dans la section"
    )
    other_salience_score: float = Field(
        default=0.0, ge=0.0,
        description="Score de saillance de l'autre concept"
    )

    # Statut
    status: CandidatePairStatus = Field(default=CandidatePairStatus.PENDING)

    # ABSTAIN (si status=ABSTAINED)
    abstain_reason: Optional[DiscursiveAbstainReason] = Field(
        default=None,
        description="Raison si ABSTAIN (INV-SCOPE-04)"
    )
    abstain_justification: Optional[str] = Field(
        default=None,
        description="Justification textuelle (pour audit)"
    )

    # Verifier output (si status=VERIFIED)
    verified_relation_type: Optional[RelationType] = Field(
        default=None,
        description="Type de relation validé par le Verifier"
    )
    verified_direction: Optional[str] = Field(
        default=None,
        description="Direction: 'pivot_to_other' ou 'other_to_pivot'"
    )
    verified_confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Confidence du Verifier"
    )

    # Phase B: Validation fields
    assertion_kind: AssertionKind = Field(
        default=AssertionKind.DISCURSIVE,
        description="Type d'assertion (DISCURSIVE pour SCOPE candidates)"
    )
    extraction_method: ExtractionMethod = Field(
        default=ExtractionMethod.PATTERN,
        description="Méthode d'extraction utilisée"
    )
    discursive_basis: List[DiscursiveBasis] = Field(
        default_factory=list,
        description="Bases discursives pour la validation"
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Raison de rejet si status=REJECTED"
    )

    # Traçabilité
    created_at: datetime = Field(default_factory=datetime.utcnow)
    verified_at: Optional[datetime] = Field(default=None)

    # Aliases pour compatibilité (subject/object vs pivot/other)
    @property
    def subject_id(self) -> str:
        """Alias pour pivot_concept_id."""
        return self.pivot_concept_id

    @property
    def object_id(self) -> str:
        """Alias pour other_concept_id."""
        return self.other_concept_id

    @property
    def relation_type(self) -> Optional[RelationType]:
        """Alias pour verified_relation_type."""
        return self.verified_relation_type

    class Config:
        use_enum_values = True


# =============================================================================
# ADR SCOPE - Budgets et Configuration
# =============================================================================

class ScopeMiningConfig(BaseModel):
    """
    Configuration du SCOPE Candidate Mining.

    Ref: ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md - INV-SCOPE-05

    Ces paramètres sont des garde-fous épistémiques, pas des optimisations.
    Modifier ces valeurs nécessite une justification documentée.
    """
    # Budgets (INV-SCOPE-05)
    top_k_pivots: int = Field(
        default=5,
        ge=1, le=20,
        description="Nombre max de pivots par section (limite explosion combinatoire)"
    )
    max_concepts_per_scope: int = Field(
        default=30,
        ge=5, le=100,
        description="Nombre max de concepts par section (évite bruit)"
    )
    max_pairs_per_scope: int = Field(
        default=50,
        ge=10, le=200,
        description="Budget strict de paires par section"
    )
    require_min_spans: int = Field(
        default=2,
        ge=2, le=5,
        description="Nombre minimum de spans pour un bundle valide (INV-SCOPE-03)"
    )

    # Scope setter selection
    min_text_length_for_scope_setter: int = Field(
        default=20,
        ge=5,
        description="Longueur min du texte pour scope_setter (si pas de heading)"
    )

    # Whitelist SCOPE V1
    allowed_relation_types: List[RelationType] = Field(
        default_factory=lambda: [RelationType.APPLIES_TO, RelationType.REQUIRES],
        description="Types de relations autorisés pour SCOPE V1"
    )

    class Config:
        use_enum_values = True


# =============================================================================
# ADR NormativeRule & SpecFact - Enums et Modèles
# =============================================================================

class NormativeModality(str, Enum):
    """
    Force de l'obligation normative.

    Ref: ADR_NORMATIVE_RULES_SPEC_FACTS.md

    Invariant INV-AGN-01: Ces modalités sont domain-agnostic.
    Elles s'appliquent à tout domaine (IT, médical, automobile, etc.)
    """
    MUST = "MUST"           # Obligation (shall, must, required, mandatory)
    MUST_NOT = "MUST_NOT"   # Interdiction (must not, shall not, no X allowed)
    SHOULD = "SHOULD"       # Recommandation forte (should, recommended)
    SHOULD_NOT = "SHOULD_NOT"  # Déconseillé (should not)
    MAY = "MAY"             # Permission/Option (may, can, optional)


class ConstraintType(str, Enum):
    """
    Type de contrainte sur une valeur.

    Ref: ADR_NORMATIVE_RULES_SPEC_FACTS.md

    Invariant INV-AGN-01: Ces types sont domain-agnostic.
    """
    EQUALS = "EQUALS"       # Valeur exacte (= X)
    MIN = "MIN"             # Minimum (>= X, at least)
    MAX = "MAX"             # Maximum (<= X, at most, no more than)
    RANGE = "RANGE"         # Entre min et max ([X, Y])
    ENUM = "ENUM"           # Liste de valeurs possibles (X or Y or Z)
    PATTERN = "PATTERN"     # Format (regex, format string)


class SpecType(str, Enum):
    """
    Type de spécification pour un SpecFact.

    Ref: ADR_NORMATIVE_RULES_SPEC_FACTS.md
    """
    VALUE = "VALUE"             # Valeur simple
    MIN = "MIN"                 # Minimum
    MAX = "MAX"                 # Maximum
    DEFAULT = "DEFAULT"         # Valeur par défaut
    RECOMMENDED = "RECOMMENDED" # Valeur recommandée


class StructureType(str, Enum):
    """
    Type de structure source pour un SpecFact.

    Ref: ADR_NORMATIVE_RULES_SPEC_FACTS.md - INV-NORM-03
    """
    TABLE = "TABLE"                     # Tableau avec headers
    KEY_VALUE_LIST = "KEY_VALUE_LIST"   # Label: Value ou Label = Value
    BULLET_LIST = "BULLET_LIST"         # - Label: Value
    DEFINITION_LIST = "DEFINITION_LIST" # dt/dd ou terme: définition


class ScopeAnchor(BaseModel):
    """
    Ancrage non-traversable d'une règle/fact dans le scope.

    Ref: ADR_NORMATIVE_RULES_SPEC_FACTS.md

    Permet de répondre à "Montre-moi les règles applicables à X"
    SANS créer de relation fausse.

    Invariant: scope_tags sont dérivés des scope setters documentaires,
    jamais inférés par LLM.
    """
    doc_id: str = Field(description="ID du document source")
    section_id: Optional[str] = Field(default=None, description="ID de la section")
    scope_setter_ids: List[str] = Field(
        default_factory=list,
        description="Titres, captions qui définissent le scope"
    )
    scope_tags: List[str] = Field(
        default_factory=list,
        description="Tags dérivés des scope setters, pas du LLM"
    )


class NormativeRule(BaseModel):
    """
    Règle normative extraite d'un document.

    Ref: ADR_NORMATIVE_RULES_SPEC_FACTS.md

    Une NormativeRule capture une obligation, interdiction ou recommandation
    explicite avec un marqueur modal détectable.

    Invariants:
    - INV-NORM-01: Preuve locale obligatoire (evidence_span)
    - INV-NORM-02: Marqueur modal explicite requis
    - INV-NORM-04: Pas de sujet inventé (subject_text = ce qui est mentionné)
    - INV-AGN-01: Domain-agnostic (pas de prédicats métier)

    NON-TRAVERSABLE: Les règles ne sont pas des edges du graphe.
    Elles sont indexables, filtrables par scope, requêtables, citables.
    """
    rule_id: str = Field(description="ULID unique")
    tenant_id: str = Field(default="default")

    # Le sujet de la règle (ce qui est contraint)
    subject_text: str = Field(
        description="Ex: 'HTTP connections', 'password length' (explicite dans le texte)"
    )
    subject_concept_id: Optional[str] = Field(
        default=None,
        description="Si mappable à un concept connu"
    )

    # La modalité (force de l'obligation)
    modality: NormativeModality = Field(
        description="MUST, SHOULD, MAY, MUST_NOT, etc."
    )

    # La contrainte ou valeur
    constraint_type: ConstraintType = Field(
        description="EQUALS, MIN, MAX, RANGE, ENUM, PATTERN"
    )
    constraint_value: str = Field(
        description="Ex: 'TLS 1.2', '256', '8 characters'"
    )
    constraint_unit: Optional[str] = Field(
        default=None,
        description="Ex: 'GB', 'seconds', 'characters'"
    )

    # Condition (si clause conditionnelle détectée)
    constraint_condition_span: Optional[str] = Field(
        default=None,
        description="Ex: 'when connecting externally', 'if using cloud'"
    )

    # Evidence (preuve locale - INV-NORM-01)
    evidence_span: str = Field(
        description="La phrase source exacte contenant le marqueur modal"
    )
    evidence_section: Optional[str] = Field(
        default=None,
        description="Le scope setter (titre section)"
    )

    # Scope anchors (pour retrouver, pas prouver)
    scope_anchors: List[ScopeAnchor] = Field(
        default_factory=list,
        description="Ancrages non-traversables pour filtrage par scope"
    )

    # Source
    source_doc_id: str
    source_chunk_id: str
    source_segment_id: Optional[str] = Field(default=None)

    # Traçabilité
    extraction_method: ExtractionMethod = Field(
        description="PATTERN ou HYBRID (jamais LLM seul pour décider si normatif)"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    extractor_version: str = Field(default="v1.0.0")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class SpecFact(BaseModel):
    """
    Fait structuré extrait d'un tableau ou liste clé-valeur.

    Ref: ADR_NORMATIVE_RULES_SPEC_FACTS.md

    Un SpecFact capture une valeur ou spécification extraite d'une
    structure tabulaire ou liste clé-valeur explicite.

    Invariants:
    - INV-NORM-01: Preuve locale obligatoire (evidence_text)
    - INV-NORM-03: Structure explicite requise
    - INV-NORM-04: Pas de sujet inventé
    - INV-AGN-01: Domain-agnostic

    NON-TRAVERSABLE: Les facts ne sont pas des edges du graphe.
    """
    fact_id: str = Field(description="ULID unique")
    tenant_id: str = Field(default="default")

    # L'attribut spécifié
    attribute_name: str = Field(
        description="Ex: 'RAM', 'Timeout', 'Port'"
    )
    attribute_concept_id: Optional[str] = Field(
        default=None,
        description="Si mappable à un concept connu"
    )

    # Le type de spécification
    spec_type: SpecType = Field(
        description="VALUE, MIN, MAX, DEFAULT, RECOMMENDED"
    )

    # La valeur
    value: str = Field(description="Ex: '256', '30', '8080'")
    value_numeric: Optional[float] = Field(
        default=None,
        description="Valeur numérique si applicable"
    )
    unit: Optional[str] = Field(
        default=None,
        description="Ex: 'GB', 'seconds', ''"
    )

    # Contexte structurel (la preuve - INV-NORM-03)
    source_structure: StructureType = Field(
        description="TABLE, KEY_VALUE_LIST, BULLET_LIST"
    )
    structure_context: Optional[str] = Field(
        default=None,
        description="Ex: 'System Requirements table'"
    )
    row_header: Optional[str] = Field(
        default=None,
        description="Pour les tableaux"
    )
    column_header: Optional[str] = Field(
        default=None,
        description="Pour les tableaux"
    )

    # Evidence (preuve locale - INV-NORM-01)
    evidence_text: str = Field(
        description="Le texte brut de la cellule/ligne"
    )
    evidence_section: Optional[str] = Field(
        default=None,
        description="Scope setter"
    )

    # Scope anchors
    scope_anchors: List[ScopeAnchor] = Field(
        default_factory=list,
        description="Ancrages non-traversables pour filtrage par scope"
    )

    # Source
    source_doc_id: str
    source_chunk_id: str
    source_segment_id: Optional[str] = Field(default=None)

    # Traçabilité
    extraction_method: ExtractionMethod = Field(
        description="PATTERN (structure détectée)"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    extractor_version: str = Field(default="v1.0.0")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# =============================================================================
# Fonctions utilitaires pour déduplication
# =============================================================================

def normalize_for_dedup(text: str) -> str:
    """Normalise un texte pour la déduplication."""
    import re
    # Lowercase, supprimer ponctuation, normaliser espaces
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', '_', text)
    return text


def dedup_key_rule(rule: NormativeRule) -> str:
    """
    Clé unique pour déduplication NormativeRule.

    Ref: ADR_NORMATIVE_RULES_SPEC_FACTS.md

    Format: subject|modality|constraint_type|value|unit
    """
    return "|".join([
        normalize_for_dedup(rule.subject_text),
        rule.modality.value if hasattr(rule.modality, 'value') else str(rule.modality),
        rule.constraint_type.value if hasattr(rule.constraint_type, 'value') else str(rule.constraint_type),
        normalize_for_dedup(rule.constraint_value),
        rule.constraint_unit or ""
    ])


def dedup_key_fact(fact: SpecFact) -> str:
    """
    Clé unique pour déduplication SpecFact.

    Ref: ADR_NORMATIVE_RULES_SPEC_FACTS.md

    Format: attribute|spec_type|value|unit
    """
    return "|".join([
        normalize_for_dedup(fact.attribute_name),
        fact.spec_type.value if hasattr(fact.spec_type, 'value') else str(fact.spec_type),
        normalize_for_dedup(fact.value),
        fact.unit or ""
    ])