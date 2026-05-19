"""V6 — Pydantic schemas pour extraction structurée universelle.

Charte domain-agnostic STRICTE : tous les types ici sont universels.
La spécialisation par domaine passe par Domain Pack tenant-scoped (sub-classing
ou enum dynamique sur `domain_type`).

CINQ ARCHÉTYPES UNIVERSELS (présents dans tout document structuré) :

1. `NamedEntity`   — entité nommée (code, person, place, concept, tool, ...)
2. `AtomicFact`    — assertion factuelle vérifiable (subject-predicate-object)
3. `Procedure`     — séquence d'étapes avec objectif
4. `Constraint`    — règle/condition/exception/exclusion
5. `Reference`     — pointeur vers autre information (interne/externe)

PLUS — pour la couche "concept card" (Option B validée) :

6. `ConceptCard`   — agrégation enrichie par entité (auto-générée à
                     l'ingestion, équivalent universel de SAPedia)

TESTS DOMAIN-AGNOSTIQUES : voir tests/runtime_v6/test_schemas.py
qui valide l'instanciation sur SAP / légal / médical / aerospace avec
le MÊME schéma.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# Type literals universels (énumérations volontairement OUVERTES)
# ─────────────────────────────────────────────────────────────────────────────
# Note : on n'utilise PAS de Literal fermé pour entity_kind/predicate.
# Au lieu de cela, on documente les valeurs canoniques attendues et on
# accepte des extensions via Domain Pack. Cela évite de violer la charte
# agnostique avec une énumération qui privilégierait certains domaines.


# Valeurs canoniques recommandées (pour guidance LLM, pas validation stricte)
ENTITY_KIND_CANONICAL = [
    "code",          # identifiants techniques (CGSADM, ICD-10 J45, Article 32, ETOPS-180)
    "person",        # personnes nommées
    "place",         # lieux géographiques
    "organization",  # organisations, entreprises, autorités
    "concept",       # concepts abstraits nommés (Authentication, GDPR Compliance)
    "tool",          # outils, logiciels, équipements
    "standard",      # normes, standards (ISO, IEC, RFC)
    "regulation",    # textes réglementaires (GDPR, CS-25, HIPAA)
    "product",       # produits commerciaux nommés
    "event",         # événements datés (Brexit, COVID-19)
    "other",         # fallback explicite
]


CONSTRAINT_TYPE_CANONICAL = [
    "requirement",   # X DOIT être Y
    "prohibition",   # X NE DOIT PAS être Y
    "exception",     # exception à une règle
    "condition",     # condition pour qu'une règle s'applique
    "exclusion",     # cas exclu du périmètre
]


REFERENCE_KIND_CANONICAL = [
    "internal_section",   # ref vers autre section du même doc
    "external_document",  # ref vers autre doc identifié
    "standard",           # ref vers norme/standard
    "regulation",         # ref vers texte réglementaire
    "url",                # ref URL externe
    "other",              # fallback
]


FACT_MODALITY_CANONICAL = [
    "asserted",        # affirmation directe : "X is Y"
    "conditional",     # conditionnel : "If A, then X is Y"
    "negated",         # négation : "X is NOT Y"
    "example",         # exemple illustratif : "For example, X is Y"
    "hypothetical",    # hypothétique : "X could be Y"
]


# ─────────────────────────────────────────────────────────────────────────────
# Archétype 1 — NamedEntity
# ─────────────────────────────────────────────────────────────────────────────


class NamedEntity(BaseModel):
    """Entité nommée extraite d'un document.

    Représente tout objet ayant une identité propre dans le texte :
    codes techniques, noms propres, références spécifiques, concepts nommés.

    Exemples cross-domaine :
    - SAP        : entity_kind="code", canonical_name="CGSADM"
    - Legal      : entity_kind="regulation", canonical_name="GDPR Article 32"
    - Medical    : entity_kind="code", canonical_name="ICD-10 J45"
    - Aerospace  : entity_kind="standard", canonical_name="CS-25 §25.105"
    """
    model_config = ConfigDict(extra="ignore")

    entity_id: str = Field(
        default_factory=lambda: f"ent_{uuid4().hex[:12]}",
        description="UUID interne (généré automatiquement)",
    )
    canonical_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nom principal de l'entité (verbatim ou normalisé)",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Variantes orthographiques, abréviations, synonymes",
    )
    entity_kind: str = Field(
        ...,
        description=(
            f"Catégorie générique. Valeurs recommandées : {ENTITY_KIND_CANONICAL}. "
            "Extensible via Domain Pack."
        ),
    )
    domain_type: Optional[str] = Field(
        default=None,
        description=(
            "Spécialisation tenant-scoped (chargée du Domain Pack). "
            "Ex: SAP_TRANSACTION, GDPR_ARTICLE, ICD_CODE, AERO_CERT."
        ),
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Description courte si présente dans le texte (1 phrase)",
    )
    evidence_section_id: str = Field(
        ...,
        description="ID de la section d'où l'entité est extraite",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Archétype 2 — AtomicFact
# ─────────────────────────────────────────────────────────────────────────────


class AtomicFact(BaseModel):
    """Assertion factuelle vérifiable, sujet-prédicat-objet.

    Représente une affirmation atomique du texte qui peut être validée.
    Pas d'agrégation, pas d'inférence : extraction littérale guidée.

    Exemples cross-domaine :
    - SAP : subject="CGSADM", predicate="initializes", object="Expert cache"
    - Legal : subject="Article 32", predicate="requires", object="data encryption"
    - Medical : subject="Salbutamol", predicate="relieves", object="bronchospasm"
    - Aerospace : subject="ETOPS-180", predicate="permits", object="180min single-engine flight"
    """
    model_config = ConfigDict(extra="ignore")

    fact_id: str = Field(
        default_factory=lambda: f"fact_{uuid4().hex[:12]}",
    )
    subject: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Sujet de l'assertion (peut référencer un NamedEntity)",
    )
    predicate: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Verbe d'action ou de relation (en minuscules)",
    )
    object: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Objet de l'assertion",
    )
    modality: str = Field(
        default="asserted",
        description=(
            f"Modalité du fait. Valeurs canoniques : {FACT_MODALITY_CANONICAL}. "
            "Permet de distinguer assertions directes de conditions/exemples."
        ),
    )
    evidence_section_id: str = Field(
        ...,
        description="ID de la section d'où le fait est extrait",
    )
    evidence_text: str = Field(
        ...,
        min_length=1,
        max_length=1500,
        description="Verbatim du texte qui supporte le fait (citation exacte)",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confiance du LLM dans cette extraction (1.0 par défaut)",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Archétype 3 — Procedure
# ─────────────────────────────────────────────────────────────────────────────


class ProcedureStep(BaseModel):
    """Une étape dans une procédure."""
    model_config = ConfigDict(extra="ignore")

    step_number: int = Field(..., ge=1)
    action: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Description de l'action à effectuer",
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Précision/contexte si présent",
    )


class Procedure(BaseModel):
    """Séquence d'étapes décrivant comment accomplir un objectif.

    Représente toute marche-à-suivre identifiable dans le texte.

    Exemples cross-domaine :
    - SAP : goal="Initialize Expert cache", steps=["Open CGSADM", "Click Initialize", ...]
    - Medical : goal="Treat acute asthma", steps=["Administer salbutamol", "Monitor SpO2", ...]
    - Legal : goal="Notify data breach", steps=["Identify the breach", "Notify supervisory authority within 72h", ...]
    - Aerospace : goal="Pre-flight check", steps=["Inspect fuselage", "Check fuel level", ...]
    """
    model_config = ConfigDict(extra="ignore")

    procedure_id: str = Field(
        default_factory=lambda: f"proc_{uuid4().hex[:12]}",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nom court de la procédure",
    )
    goal: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Objectif que la procédure permet d'atteindre",
    )
    steps: list[ProcedureStep] = Field(
        default_factory=list,
        description="Étapes ordonnées (peut être vide si goal mentionné sans détails)",
    )
    prerequisites: list[str] = Field(
        default_factory=list,
        description="Prérequis (autres procédures, conditions, autorisations)",
    )
    evidence_section_id: str = Field(...)


# ─────────────────────────────────────────────────────────────────────────────
# Archétype 4 — Constraint
# ─────────────────────────────────────────────────────────────────────────────


class Constraint(BaseModel):
    """Règle, obligation, condition, exception ou exclusion.

    Représente toute contrainte explicite du texte.

    Exemples cross-domaine :
    - SAP : type=requirement, statement="Requires authorization object P_RCF_POOL"
    - Legal : type=requirement, statement="Personal data must be encrypted in transit"
    - Medical : type=prohibition, statement="Contraindicated if patient < 12 years"
    - Aerospace : type=condition, statement="Applicable only above 35,000 ft"
    """
    model_config = ConfigDict(extra="ignore")

    constraint_id: str = Field(
        default_factory=lambda: f"cstr_{uuid4().hex[:12]}",
    )
    constraint_type: str = Field(
        ...,
        description=f"Type de contrainte. Valeurs canoniques : {CONSTRAINT_TYPE_CANONICAL}",
    )
    statement: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Énoncé de la contrainte (verbatim ou quasi-verbatim)",
    )
    applies_to: list[str] = Field(
        default_factory=list,
        description="Entities ou procedures concernés par la contrainte (par nom)",
    )
    evidence_section_id: str = Field(...)


# ─────────────────────────────────────────────────────────────────────────────
# Archétype 5 — Reference
# ─────────────────────────────────────────────────────────────────────────────


class Reference(BaseModel):
    """Pointeur vers une autre information (interne au doc ou externe).

    Représente toute référence croisée mentionnée dans le texte.
    La résolution effective (lookup vers la cible) se fait après extraction.

    Exemples cross-domaine :
    - SAP : reference_text="see SAP Note 1061242", target_kind=external_document
    - Legal : reference_text="see Article 17", target_kind=internal_section
    - Medical : reference_text="ATS Guidelines 2024", target_kind=standard
    - Aerospace : reference_text="EASA AMC 25.1309", target_kind=regulation
    """
    model_config = ConfigDict(extra="ignore")

    reference_id: str = Field(
        default_factory=lambda: f"ref_{uuid4().hex[:12]}",
    )
    reference_text: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Texte de la référence tel qu'apparaît dans le doc (URLs longues acceptées)",
    )
    target_kind: str = Field(
        ...,
        description=f"Type de cible. Valeurs canoniques : {REFERENCE_KIND_CANONICAL}",
    )
    resolved_target: Optional[str] = Field(
        default=None,
        description="Section_id ou doc_id si la référence a été résolue (post-extraction)",
    )
    evidence_section_id: str = Field(...)


# ─────────────────────────────────────────────────────────────────────────────
# Container — résultat d'extraction par section
# ─────────────────────────────────────────────────────────────────────────────


class SectionExtraction(BaseModel):
    """Résultat d'extraction structurée pour une section donnée.

    C'est l'output Pydantic attendu du LLM d'extraction par section.
    """
    model_config = ConfigDict(extra="ignore")

    doc_id: str
    section_id: str
    entities: list[NamedEntity] = Field(default_factory=list)
    facts: list[AtomicFact] = Field(default_factory=list)
    procedures: list[Procedure] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    extractor_model: Optional[str] = Field(
        default=None,
        description="Nom du LLM utilisé pour l'extraction (audit)",
    )

    @model_validator(mode="after")
    def _propagate_section_id(self):
        """S'assure que tous les items contiennent bien evidence_section_id.

        Si le LLM produit des items sans evidence_section_id (ou avec une valeur
        vide), on propage le section_id parent. Permet d'être tolérant aux LLM
        qui oublient parfois ce champ.
        """
        sid = self.section_id
        for ent in self.entities:
            if not ent.evidence_section_id:
                ent.evidence_section_id = sid
        for fact in self.facts:
            if not fact.evidence_section_id:
                fact.evidence_section_id = sid
        for proc in self.procedures:
            if not proc.evidence_section_id:
                proc.evidence_section_id = sid
        for cstr in self.constraints:
            if not cstr.evidence_section_id:
                cstr.evidence_section_id = sid
        for ref in self.references:
            if not ref.evidence_section_id:
                ref.evidence_section_id = sid
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Couche enrichissement — ConceptCard (Option B validée par user 2026-05-14)
# ─────────────────────────────────────────────────────────────────────────────


class ConceptCardFact(BaseModel):
    """Fact agrégé d'une concept card avec référence à sa section evidence."""
    model_config = ConfigDict(extra="ignore")

    statement: str = Field(..., min_length=1, max_length=500)
    evidence_section_id: str


class ConceptCard(BaseModel):
    """Page synthétique enrichie pour une entité importante du corpus.

    Équivalent universel automatique de SAPedia (asset SAP curated humain).
    Générée à l'ingestion par LLM après extraction des facts atomiques :
    le LLM lit toutes les sections où l'entité apparaît et produit un
    résumé structuré agrégé.

    Au runtime, l'agent peut récupérer la card en 1 seul tool call
    (`get_concept_card`) au lieu d'agréger plusieurs find_facts/find_procedures.

    Critère de génération (configurable) : entités mentionnées dans
    ≥3 sections OU ayant ≥3 facts associés.

    Charte respectée : le mécanisme est universel, le contenu est
    grounded sur le corpus (chaque assertion référence sa section evidence).
    """
    model_config = ConfigDict(extra="ignore")

    card_id: str = Field(
        default_factory=lambda: f"card_{uuid4().hex[:12]}",
    )
    entity_id: str = Field(
        ...,
        description="Référence vers le NamedEntity.entity_id source",
    )
    entity_canonical_name: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Description synthétique de l'entité (2-5 phrases)",
    )
    typical_usage: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Contexte d'usage typique mentionné dans le corpus",
    )
    key_facts: list[ConceptCardFact] = Field(
        default_factory=list,
        description="Facts essentiels (avec evidence section_id)",
    )
    procedures_associated: list[str] = Field(
        default_factory=list,
        description="IDs des Procedure liées (procedure_id)",
    )
    constraints_associated: list[str] = Field(
        default_factory=list,
        description="IDs des Constraint liées (constraint_id)",
    )
    references_associated: list[str] = Field(
        default_factory=list,
        description="IDs des Reference liées (reference_id)",
    )
    related_entities: list[str] = Field(
        default_factory=list,
        description="Noms d'autres entités liées (cross-reference)",
    )
    contexts: list[str] = Field(
        default_factory=list,
        description="Liste de contextes d'application (situations où l'entité s'applique)",
    )
    source_section_ids: list[str] = Field(
        default_factory=list,
        description="Sections du corpus utilisées pour générer la card",
    )
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generator_model: Optional[str] = Field(
        default=None,
        description="LLM utilisé pour la génération (audit)",
    )
