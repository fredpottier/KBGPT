"""
Schemas Pydantic pour Assertion-Centric UX (OSMOSE).

Ce module definit les modeles de donnees pour le systeme de reponses instrumentees
qui remplace le score de confiance par un contrat de verite base sur des assertions.

Chaque reponse est decomposee en assertions avec 4 statuts possibles:
- FACT: Explicitement present dans >= 1 source
- INFERRED: Deduit logiquement de FACTs
- FRAGILE: Faiblement soutenu (1 source, ancien, ambigu)
- CONFLICT: Sources incompatibles
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from uuid import uuid4


# Types Litteraux
AssertionStatus = Literal["FACT", "INFERRED", "FRAGILE", "CONFLICT"]
AssertionScope = Literal["paragraph", "list_item"]
Authority = Literal["official", "internal", "partner", "external"]
Freshness = Literal["fresh", "mixed", "stale"]


# --- Schemas de Support ---

class SourcesDateRange(BaseModel):
    """Plage de dates des sources utilisees."""
    from_year: str = Field(..., alias="from", description="Annee de debut (YYYY)")
    to_year: str = Field(..., alias="to", description="Annee de fin (YYYY)")

    class Config:
        populate_by_name = True


class AssertionSupport(BaseModel):
    """Metriques de support pour une assertion."""
    supporting_sources_count: int = Field(
        default=0,
        description="Nombre de sources supportant l'assertion"
    )
    weighted_support: float = Field(
        default=0.0,
        description="Score de support pondere par autorite"
    )
    freshness: Freshness = Field(
        default="mixed",
        description="Fraicheur des sources (fresh/mixed/stale)"
    )
    has_official: bool = Field(
        default=False,
        description="Au moins une source officielle"
    )


class AssertionMeta(BaseModel):
    """Metadonnees techniques d'une assertion."""
    support: Optional[AssertionSupport] = Field(
        default=None,
        description="Metriques de support detaillees"
    )


# --- Document et Localisation ---

class DocumentInfo(BaseModel):
    """Informations sur le document source."""
    id: str = Field(..., description="Identifiant unique du document")
    title: str = Field(..., description="Titre du document")
    doc_type: str = Field(
        ...,
        alias="type",
        description="Type de document (PDF, PPTX, DOCX)"
    )
    date: Optional[str] = Field(
        None,
        description="Date du document (YYYY-MM)"
    )
    authority: Authority = Field(
        default="internal",
        description="Niveau d'autorite"
    )
    uri: Optional[str] = Field(
        None,
        description="URI vers le document original"
    )

    class Config:
        populate_by_name = True


class SourceLocator(BaseModel):
    """Localisation precise dans le document source."""
    page_or_slide: Optional[int] = Field(
        None,
        description="Numero de page ou slide"
    )
    bbox: Optional[List[float]] = Field(
        None,
        description="Bounding box [x1, y1, x2, y2] normalise 0-1"
    )


class SourceRef(BaseModel):
    """Reference complete vers une source."""
    id: str = Field(..., description="Identifiant unique de la source (S1, S2, ...)")
    document: DocumentInfo = Field(..., description="Informations document")
    locator: Optional[SourceLocator] = Field(
        None,
        description="Localisation dans le document"
    )
    excerpt: str = Field(..., description="Extrait textuel cite")
    thumbnail_url: Optional[str] = Field(
        None,
        description="URL du thumbnail (slide/page)"
    )
    evidence_url: Optional[str] = Field(
        None,
        description="URL vers la preuve visuelle avec highlight"
    )


# --- Assertion ---

class Assertion(BaseModel):
    """
    Unite fondamentale du systeme Assertion-Centric.

    Une assertion = un claim logique verifiable (pas une phrase grammaticale).
    """
    id: str = Field(..., description="Identifiant unique (A1, A2, ...)")
    text_md: str = Field(
        ...,
        description="Contenu markdown (gras, italique, liens, listes simples autorisees)"
    )
    status: AssertionStatus = Field(
        ...,
        description="Statut de verite (FACT/INFERRED/FRAGILE/CONFLICT)"
    )
    scope: AssertionScope = Field(
        default="paragraph",
        description="Type de granularite"
    )
    sources: List[str] = Field(
        default_factory=list,
        description="IDs des sources supportant l'assertion"
    )
    contradictions: List[str] = Field(
        default_factory=list,
        description="IDs des sources contradictoires (si CONFLICT)"
    )
    derived_from: List[str] = Field(
        default_factory=list,
        description="IDs assertions parentes (si INFERRED)"
    )
    inference_note: Optional[str] = Field(
        None,
        description="Explication de l'inference (si INFERRED)"
    )
    meta: Optional[AssertionMeta] = Field(
        None,
        description="Metadonnees techniques"
    )


# --- Proof Ticket ---

class ProofTicketCTA(BaseModel):
    """Call-to-action pour un ticket de preuve."""
    label: str = Field(..., description="Texte du bouton (ex: 'Voir citation')")
    target_type: Literal["source", "assertion", "external"] = Field(
        ...,
        alias="type",
        description="Type de cible"
    )
    target_id: str = Field(
        ...,
        alias="id",
        description="ID de la cible"
    )

    class Config:
        populate_by_name = True


class ProofTicket(BaseModel):
    """
    Recu de preuve pour une assertion cle.

    Les proof tickets sont generes pour les 3-5 assertions les plus importantes.
    """
    ticket_id: str = Field(..., description="Identifiant unique du ticket")
    assertion_id: str = Field(..., description="ID de l'assertion concernee")
    title: str = Field(..., description="Resume court de l'assertion")
    status: AssertionStatus = Field(..., description="Statut herite de l'assertion")
    summary: str = Field(
        ...,
        description="Explication en 1 phrase du niveau de confiance"
    )
    primary_sources: List[str] = Field(
        default_factory=list,
        description="IDs des sources principales"
    )
    cta: Optional[ProofTicketCTA] = Field(
        None,
        description="Action suggere a l'utilisateur"
    )


# --- Open Points ---

class OpenPoint(BaseModel):
    """Point non resolu ou question ouverte."""
    id: str = Field(..., description="Identifiant unique (OP1, OP2, ...)")
    description: str = Field(..., description="Description du point non resolu")
    reason: str = Field(..., description="Raison (evidence_insufficient, conflict_unresolved, ...)")
    related_assertions: List[str] = Field(
        default_factory=list,
        description="IDs des assertions liees"
    )


# --- Truth Contract ---

class TruthContract(BaseModel):
    """
    Contrat de verite remplacant le score de confiance.

    Affiche: "5 faits sources - 2 inferences - 1 fragile - 0 conflit - Sources 2023-2025"
    """
    facts_count: int = Field(default=0, description="Nombre d'assertions FACT")
    inferred_count: int = Field(default=0, description="Nombre d'assertions INFERRED")
    fragile_count: int = Field(default=0, description="Nombre d'assertions FRAGILE")
    conflict_count: int = Field(default=0, description="Nombre d'assertions CONFLICT")
    sources_count: int = Field(default=0, description="Nombre total de sources distinctes")
    sources_date_range: Optional[SourcesDateRange] = Field(
        None,
        description="Plage temporelle des sources"
    )


# --- Instrumented Answer ---

class InstrumentedAnswer(BaseModel):
    """
    Reponse instrumentee complete (Assertion-Centric).

    Remplace la synthese textuelle monolithique par une liste ordonnee
    d'assertions avec leurs statuts de verite.
    """
    answer_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Identifiant unique de la reponse"
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Horodatage ISO-8601"
    )
    truth_contract: TruthContract = Field(
        default_factory=TruthContract,
        description="Resume du contrat de verite"
    )
    assertions: List[Assertion] = Field(
        default_factory=list,
        description="Liste ordonnee des assertions (6-14 recommande)"
    )
    proof_tickets: List[ProofTicket] = Field(
        default_factory=list,
        description="Tickets de preuve pour assertions cles (3-5)"
    )
    sources: List[SourceRef] = Field(
        default_factory=list,
        description="References sources completes"
    )
    open_points: List[OpenPoint] = Field(
        default_factory=list,
        description="Points non resolus"
    )


# --- Search Response Extension ---

class RetrievalStats(BaseModel):
    """Statistiques de recuperation pour debug/monitoring."""
    candidates_considered: int = Field(
        default=0,
        description="Nombre de candidats evalues"
    )
    top_k_used: int = Field(
        default=0,
        description="Nombre de candidats retenus"
    )
    kg_nodes_touched: int = Field(
        default=0,
        description="Noeuds KG consultes"
    )
    kg_edges_touched: int = Field(
        default=0,
        description="Relations KG consultees"
    )


class InstrumentedSearchResponse(BaseModel):
    """
    Extension de la reponse de recherche avec instrumentation.

    Utilisee quand use_instrumented=true dans la requete.
    """
    request_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="ID de la requete"
    )
    query: str = Field(..., description="Question originale")
    instrumented_answer: InstrumentedAnswer = Field(
        ...,
        description="Reponse instrumentee"
    )
    retrieval: Optional[RetrievalStats] = Field(
        None,
        description="Statistiques de recuperation"
    )


# --- Candidats LLM (internes) ---

class AssertionCandidate(BaseModel):
    """
    Assertion candidate generee par le LLM (avant classification backend).

    Le LLM propose kind=FACT ou kind=INFERRED, le backend valide et peut
    changer le statut final (FRAGILE, CONFLICT).
    """
    id: str = Field(..., description="ID temporaire (A1, A2, ...)")
    text_md: str = Field(..., description="Contenu markdown")
    kind: Literal["FACT", "INFERRED"] = Field(
        ...,
        description="Type propose par LLM"
    )
    evidence_used: List[str] = Field(
        default_factory=list,
        description="IDs sources citees (pour FACT)"
    )
    derived_from: List[str] = Field(
        default_factory=list,
        description="IDs assertions parentes (pour INFERRED)"
    )
    notes: Optional[str] = Field(
        None,
        description="Explication LLM (pour INFERRED)"
    )


class LLMAssertionResponse(BaseModel):
    """Schema de la reponse JSON attendue du LLM."""
    assertions: List[AssertionCandidate] = Field(
        default_factory=list,
        description="Liste des assertions generees"
    )
    open_points: List[str] = Field(
        default_factory=list,
        description="Points non resolus identifies par le LLM"
    )


__all__ = [
    # Types
    "AssertionStatus",
    "AssertionScope",
    "Authority",
    "Freshness",
    # Support schemas
    "SourcesDateRange",
    "AssertionSupport",
    "AssertionMeta",
    # Document schemas
    "DocumentInfo",
    "SourceLocator",
    "SourceRef",
    # Core schemas
    "Assertion",
    "ProofTicket",
    "ProofTicketCTA",
    "OpenPoint",
    "TruthContract",
    "InstrumentedAnswer",
    # Response schemas
    "RetrievalStats",
    "InstrumentedSearchResponse",
    # Internal schemas
    "AssertionCandidate",
    "LLMAssertionResponse",
]
