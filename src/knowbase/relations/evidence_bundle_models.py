# =============================================================================
# Evidence Bundle Models - Sprint 1 OSMOSE
# =============================================================================
# Pass 3.5 - Multi-Span Evidence Bundle Resolver
# Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3
#
# Ces modèles supportent l'assemblage de preuves fragmentées pour démontrer
# des relations. Un EvidenceBundle n'est PAS de la connaissance, c'est un
# artefact de justification structuré.
# =============================================================================

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class FragmentType(str, Enum):
    """Type de fragment d'evidence dans un bundle."""
    ENTITY_MENTION = "ENTITY_MENTION"        # Mention d'entité (sujet/objet)
    PREDICATE_LEXICAL = "PREDICATE_LEXICAL"  # Prédicat textuel extrait
    PREDICATE_VISUAL = "PREDICATE_VISUAL"    # Prédicat visuel (diagramme)
    COREFERENCE_LINK = "COREFERENCE_LINK"    # Lien de coréférence (Sprint 2)


class BundleValidationStatus(str, Enum):
    """Statut de validation d'un bundle."""
    CANDIDATE = "CANDIDATE"  # En attente de validation/promotion
    PROMOTED = "PROMOTED"    # Promu en SemanticRelation
    REJECTED = "REJECTED"    # Rejeté avec raison


class ExtractionMethodBundle(str, Enum):
    """Méthode d'extraction utilisée pour un fragment."""
    # Textuels
    CHARSPAN_EXACT = "CHARSPAN_EXACT"       # Localisation via charspan exact
    CHARSPAN_EXPAND = "CHARSPAN_EXPAND"     # Localisation via char_span expand
    FUZZY_MATCH = "FUZZY_MATCH"             # Fallback fuzzy sur label
    SPACY_DEP = "SPACY_DEP"                 # Extraction via dépendances spaCy

    # Visuels (Sprint 2)
    DIAGRAM_ELEMENT = "DIAGRAM_ELEMENT"     # Élément de diagramme Docling
    VISUAL_ARROW = "VISUAL_ARROW"           # Flèche détectée
    VISUAL_CAPTION = "VISUAL_CAPTION"       # Caption de diagramme

    # Coréférence (Sprint 2)
    TOPIC_BINDING = "TOPIC_BINDING"         # Résolution via topic binding D+
    DOMINANCE_WITH_SCOPE = "DOMINANCE_WITH_SCOPE"  # Topic dominant + scope local
    D_PLUS_STRUCTURAL = "D_PLUS_STRUCTURAL"        # Approche D+ complète


# =============================================================================
# Core Models
# =============================================================================

class EvidenceFragment(BaseModel):
    """
    Fragment d'evidence individuel dans un bundle.

    Chaque fragment représente une pièce de preuve:
    - EA: Evidence du sujet (ENTITY_MENTION)
    - EB: Evidence de l'objet (ENTITY_MENTION)
    - EP: Evidence du prédicat (PREDICATE_LEXICAL ou PREDICATE_VISUAL)
    - EL: Evidence du lien (COREFERENCE_LINK) - Sprint 2 uniquement
    """

    fragment_id: str = Field(
        description="Identifiant unique du fragment (ULID)"
    )
    fragment_type: FragmentType = Field(
        description="Type de fragment"
    )
    text: str = Field(
        description="Texte du fragment (verbatim du document)"
    )
    source_context_id: str = Field(
        description="ID du SectionContext source (sec:doc:hash)"
    )
    source_page: Optional[int] = Field(
        default=None,
        description="Numéro de page source (si disponible)"
    )

    # Positionnement (si disponible)
    char_start: Optional[int] = Field(
        default=None,
        description="Position début dans le texte de la section"
    )
    char_end: Optional[int] = Field(
        default=None,
        description="Position fin dans le texte de la section"
    )

    # Qualité
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confiance du fragment [0.0-1.0]"
    )
    extraction_method: ExtractionMethodBundle = Field(
        description="Méthode d'extraction utilisée"
    )

    class Config:
        use_enum_values = True


class EvidenceBundle(BaseModel):
    """
    Bundle d'evidence assemblant des fragments pour prouver une relation.

    Un EvidenceBundle n'est PAS de la connaissance. C'est un artefact de
    justification structuré qui, si validé, sera promu en SemanticRelation.

    Formule de confiance: confidence = min(EA, EB, EP, [EL])
    Le maillon le plus faible gouverne.
    """

    # Identité
    bundle_id: str = Field(
        description="Identifiant unique du bundle (ULID)"
    )
    tenant_id: str = Field(
        default="default",
        description="Tenant ID"
    )
    document_id: str = Field(
        description="Document source"
    )

    # Fragments d'evidence
    evidence_subject: EvidenceFragment = Field(
        description="EA: Evidence du sujet"
    )
    evidence_object: EvidenceFragment = Field(
        description="EB: Evidence de l'objet"
    )
    evidence_predicate: List[EvidenceFragment] = Field(
        default_factory=list,
        description="EP: Evidence(s) du prédicat (peut être multiple)"
    )
    evidence_link: Optional[EvidenceFragment] = Field(
        default=None,
        description="EL: Evidence du lien coréférentiel (Sprint 2 uniquement)"
    )

    # Concepts liés
    subject_concept_id: str = Field(
        description="ID du CanonicalConcept sujet"
    )
    object_concept_id: str = Field(
        description="ID du CanonicalConcept objet"
    )

    # Typage de la relation (tentatif)
    relation_type_candidate: str = Field(
        description="Type de relation candidat (ex: INTEGRATES_WITH, REQUIRES)"
    )
    typing_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confiance sur le typage de la relation"
    )

    # Confiance globale
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confiance globale = min(tous les fragments)"
    )

    # Validation
    validation_status: BundleValidationStatus = Field(
        default=BundleValidationStatus.CANDIDATE,
        description="Statut de validation"
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Raison du rejet (si REJECTED)"
    )

    # Promotion
    promoted_relation_id: Optional[str] = Field(
        default=None,
        description="ID de la SemanticRelation si promu"
    )

    # Traçabilité
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de création"
    )
    validated_at: Optional[datetime] = Field(
        default=None,
        description="Date de validation/rejet"
    )

    # Métadonnées
    schema_version: str = Field(
        default="1.0.0",
        description="Version du schéma"
    )

    class Config:
        use_enum_values = True


# =============================================================================
# Validation Models
# =============================================================================

class BundleValidationResult(BaseModel):
    """
    Résultat de la validation d'un bundle.

    Contient le détail des checks passés et échoués pour audit.
    """

    is_valid: bool = Field(
        description="True si le bundle passe tous les checks"
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Raison principale du rejet"
    )
    checks_passed: List[str] = Field(
        default_factory=list,
        description="Liste des checks passés"
    )
    checks_failed: List[str] = Field(
        default_factory=list,
        description="Liste des checks échoués"
    )

    # Détails pour audit
    validation_details: Dict[str, str] = Field(
        default_factory=dict,
        description="Détails par check (check_name -> message)"
    )


# =============================================================================
# Candidate Detection Models
# =============================================================================

class CandidatePair(BaseModel):
    """
    Paire de concepts candidate pour création de bundle.

    Résultat de la requête de co-présence intra-section.
    """

    # Concepts
    subject_concept_id: str = Field(description="ID du concept sujet")
    subject_label: str = Field(description="Label du concept sujet")
    object_concept_id: str = Field(description="ID du concept objet")
    object_label: str = Field(description="Label du concept objet")

    # Section partagée
    shared_context_id: str = Field(description="ID de la section commune")

    # Quotes et positions
    subject_quote: Optional[str] = Field(
        default=None,
        description="Citation du sujet dans le document"
    )
    object_quote: Optional[str] = Field(
        default=None,
        description="Citation de l'objet dans le document"
    )

    # Charspans (requis Sprint 1)
    subject_char_start: Optional[int] = Field(
        default=None,
        description="Position début du sujet"
    )
    subject_char_end: Optional[int] = Field(
        default=None,
        description="Position fin du sujet"
    )
    object_char_start: Optional[int] = Field(
        default=None,
        description="Position début de l'objet"
    )
    object_char_end: Optional[int] = Field(
        default=None,
        description="Position fin de l'objet"
    )


class PredicateCandidate(BaseModel):
    """
    Prédicat candidat extrait entre deux entités.
    """

    text: str = Field(description="Texte du prédicat")
    lemma: str = Field(description="Lemme du verbe principal")
    pos: str = Field(description="POS tag du verbe")
    dep: str = Field(description="Dépendance syntaxique")

    # Position
    char_start: int = Field(description="Position début")
    char_end: int = Field(description="Position fin")
    token_index: int = Field(description="Index du token dans le doc")

    # Validation
    is_auxiliary: bool = Field(
        default=False,
        description="True si POS=AUX"
    )
    is_copula: bool = Field(
        default=False,
        description="True si structure copule/attributive"
    )
    is_modal: bool = Field(
        default=False,
        description="True si modal/intentionnel"
    )
    has_prep_complement: bool = Field(
        default=False,
        description="True si complément prépositionnel présent"
    )

    # Confiance
    structure_confidence: float = Field(
        ge=0.0, le=1.0,
        default=0.8,
        description="Confiance sur la structure prédicative"
    )


# =============================================================================
# Processing Result Models
# =============================================================================

class BundleProcessingStats(BaseModel):
    """Statistiques de traitement des bundles."""

    pairs_found: int = Field(default=0, description="Paires candidates trouvées")
    pairs_with_charspan: int = Field(default=0, description="Paires avec charspans valides")
    pairs_skipped_no_charspan: int = Field(default=0, description="Paires ignorées (pas de charspan)")

    bundles_created: int = Field(default=0, description="Bundles créés")
    bundles_promoted: int = Field(default=0, description="Bundles promus")
    bundles_rejected: int = Field(default=0, description="Bundles rejetés")

    # Raisons de rejet
    rejection_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Compteur par raison de rejet"
    )


class BundleProcessingResult(BaseModel):
    """
    Résultat complet du traitement des bundles pour un document.
    """

    document_id: str = Field(description="Document traité")
    tenant_id: str = Field(default="default")

    # Bundles créés
    bundles: List[EvidenceBundle] = Field(
        default_factory=list,
        description="Tous les bundles créés"
    )

    # Statistiques
    stats: BundleProcessingStats = Field(
        default_factory=BundleProcessingStats
    )

    # Timing
    processing_time_seconds: float = Field(
        default=0.0,
        description="Temps de traitement en secondes"
    )

    # Métadonnées
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    processor_version: str = Field(default="1.0.0")
