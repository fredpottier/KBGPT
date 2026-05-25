# src/knowbase/claimfirst/models/claim.py
"""
Modèle Claim - Objet central du pipeline Claim-First.

V1.1: Added structured_form for deterministic verification.

Charte de la "bonne Claim" (non négociable):
1. Dit UNE chose précise
2. Supportée par passage(s) verbatim exact(s)
3. Jamais exhaustive par défaut
4. Contextuelle (scope, conditions, version)
5. N'infère rien (pas de déduction)
6. Comparable (compatible/contradictoire/disjointe)
7. Peut NE PAS exister si le document est vague
8. Révisable par addition, jamais par réécriture

INV-1: La preuve d'une Claim est `unit_ids`, pas `passage_id`.
       Le passage est le contexte de navigation, pas la preuve.
INV-3: Une Claim appartient à UN document (`doc_id` obligatoire).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, field_validator


class ClaimType(str, Enum):
    """Types de claims selon leur nature épistémique."""

    FACTUAL = "FACTUAL"
    """Assertion factuelle vérifiable (ex: "TLS 1.2 is supported")."""

    PRESCRIPTIVE = "PRESCRIPTIVE"
    """Obligation ou interdiction (ex: "Customers must enable MFA")."""

    DEFINITIONAL = "DEFINITIONAL"
    """Définition ou description (ex: "SAP BTP is a platform...")."""

    CONDITIONAL = "CONDITIONAL"
    """Assertion conditionnelle (ex: "If data exceeds 1TB, then...")."""

    PERMISSIVE = "PERMISSIVE"
    """Permission ou autorisation (ex: "Customers may configure...")."""

    PROCEDURAL = "PROCEDURAL"
    """Étape ou processus (ex: "To enable SSO, first configure...")."""


class ClaimScope(BaseModel):
    """
    Contexte de validité d'une Claim.

    Définit les conditions sous lesquelles la claim est vraie.
    """

    version: Optional[str] = Field(
        default=None,
        description="Version du produit/service concerné (ex: '2023.10')"
    )

    region: Optional[str] = Field(
        default=None,
        description="Région géographique applicable (ex: 'EU', 'China')"
    )

    edition: Optional[str] = Field(
        default=None,
        description="Édition du produit (ex: 'Enterprise', 'Standard')"
    )

    conditions: List[str] = Field(
        default_factory=list,
        description="Conditions supplémentaires de validité"
    )

    def to_scope_key(self) -> str:
        """Génère une clé de scope pour déduplication."""
        parts = [
            self.version or "any",
            self.region or "any",
            self.edition or "any",
        ]
        if self.conditions:
            parts.append(":".join(sorted(self.conditions)))
        return "|".join(parts)

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j (préfixe scope_)."""
        return {
            "scope_version": self.version,
            "scope_region": self.region,
            "scope_edition": self.edition,
            "scope_conditions": self.conditions if self.conditions else None,
        }


class QualifierType(str, Enum):
    """Types de qualifiers structurés (Phase B, domain-agnostic).

    Cf ADR_PHASE_B_HYPER_RELATIONAL_CLAIMS §3.1. Universels : applicables à
    médical (posologie conditionnelle), légal (amendement temporel),
    aerospace (condition d'altitude), pas seulement SAP.
    """

    TEMPORAL = "temporal"
    """Borne temporelle : "depuis 2024", "jusqu'à v2.5", "à partir de SPS03"."""

    SPATIAL = "spatial"
    """Région/zone : "EU only", "China region", "on-premise"."""

    VERSION = "version"
    """Version/édition produit : "S/4HANA 2023", "edition Private Cloud"."""

    CONDITION = "condition"
    """Condition d'activation : "si MFA activé", "pour clients RISE"."""

    SCOPE_LIMIT = "scope_limit"
    """Limite de portée : "hors production", "développement uniquement"."""


class ClaimQualifier(BaseModel):
    """Qualifier structuré enrichissant un Claim (Phase B, 25/05/2026).

    Capture une condition d'applicabilité dérivée du verbatim source. Permet au
    retrieval + Synthesize de répondre aux questions conditionnelles/temporelles
    (lifecycle) sans avoir à croiser plusieurs claims atomiques.

    Cf ADR_PHASE_B_HYPER_RELATIONAL_CLAIMS §3.1.
    """

    qualifier_type: QualifierType = Field(
        ..., description="Type universel de qualifier (cf QualifierType)"
    )
    value: str = Field(
        ..., description="Valeur du qualifier dérivée du verbatim (ex: 'depuis 2024')"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Confiance LLM sur l'extraction de ce qualifier"
    )


class Claim(BaseModel):
    """
    Claim documentée - objet central du pipeline.

    Une Claim est une affirmation synthétique, précise, explicitement
    fondée sur un ou plusieurs passages verbatim du document.

    Attributes:
        claim_id: Identifiant unique de la claim
        tenant_id: Tenant multi-locataire
        doc_id: Document source (INV-3: mono-document)
        text: Formulation synthétique (UNE chose précise)
        claim_type: Type épistémique
        scope: Contexte de validité
        verbatim_quote: Citation exacte du texte source (OBLIGATOIRE)
        passage_id: Lien vers le Passage englobant
        unit_ids: Références aux AssertionUnits (preuve, INV-1)
        confidence: Score de confiance [0-1]
        cluster_id: Cluster d'agrégation inter-docs (optionnel)
        created_at: Date de création
    """

    claim_id: str = Field(
        ...,
        description="Identifiant unique de la claim"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    doc_id: str = Field(
        ...,
        description="Document source (INV-3: claim mono-document)"
    )

    text: str = Field(
        ...,
        min_length=10,
        description="Formulation synthétique (UNE chose précise)"
    )

    claim_type: ClaimType = Field(
        ...,
        description="Type épistémique de la claim"
    )

    scope: ClaimScope = Field(
        default_factory=ClaimScope,
        description="Contexte de validité"
    )

    verbatim_quote: str = Field(
        ...,
        min_length=10,
        description="Citation exacte du texte source (OBLIGATOIRE)"
    )

    passage_id: str = Field(
        ...,
        description="Lien vers le Passage englobant (contexte)"
    )

    unit_ids: List[str] = Field(
        default_factory=list,
        description="Références aux AssertionUnits (preuve, INV-1)"
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Score de confiance [0-1]"
    )

    cluster_id: Optional[str] = Field(
        default=None,
        description="Cluster d'agrégation inter-docs (optionnel)"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de création"
    )

    # Métadonnées optionnelles
    language: str = Field(
        default="en",
        description="Langue de la claim"
    )

    # V1.1: Structured form for deterministic verification
    structured_form: Optional[Dict[str, Any]] = Field(
        default=None,
        description="V1.1: Pre-computed structured form for deterministic comparison"
    )

    # V1.2: Content fingerprint for cross-doc dedup (hash sans doc_id)
    content_fingerprint: Optional[str] = Field(
        default=None,
        description="V1.2: Content-only fingerprint (no doc_id) for cross-doc matching"
    )

    # V1.3: Quality gate fields
    quality_status: Optional[str] = Field(
        default=None,
        description="V1.3: Quality gate action applied (QualityAction enum value)"
    )

    quality_scores: Optional[Dict[str, float]] = Field(
        default=None,
        description="V1.3: Embedding-based quality scores {verif_score, sf_alignment, triviality}"
    )

    quality_reasons: Optional[List[str]] = Field(
        default=None,
        description="V1.3: Human-readable reasons for quality decision"
    )

    # V1.4: Champion/Redundant fields
    is_champion: Optional[bool] = Field(
        default=None,
        description="V1.4: Best representative in cluster"
    )

    redundant: Optional[bool] = Field(
        default=None,
        description="V1.4: Redundant claim in cluster"
    )

    champion_claim_id: Optional[str] = Field(
        default=None,
        description="V1.4: ID of champion if redundant"
    )

    # A4.2 (22/05/2026) — SubjectIndexer indépendant de structured_form
    # cf doc/ongoing/A41_AUDIT_PIPELINE_CLAIMFIRST.md
    # structured_form est réservé aux relations HIGH VALUE (S-P-O canonique).
    # subject_canonical doit être peuplé pour TOUS les claims pour permettre
    # l'indexation runtime_v6 par sujet, indépendamment de structured_form.
    # Si SF rempli, subject_canonical = SF.subject (priorité SF).
    # Sinon, subject_canonical extrait via SubjectIndexer (LLM zero-shot).
    subject_canonical: Optional[str] = Field(
        default=None,
        description="A4.2: Subject d'indexation runtime. Priorité: SF.subject si présent, sinon extraction SubjectIndexer. NULL acceptable seulement si marginal=True."
    )

    marginal: Optional[bool] = Field(
        default=None,
        description="A4.2: True si le claim n'a pas de subject naturel (descriptif/fragmentaire). Exclu du retrieval principal."
    )

    subject_extraction_confidence: Optional[float] = Field(
        default=None,
        description="A4.2: Confidence du LLM SubjectIndexer (0-1). None si subject vient de SF.subject ou pas encore traité."
    )

    # --- Phase B (25/05/2026) : enrichissement hyper-relationnel ---
    qualifiers: List["ClaimQualifier"] = Field(
        default_factory=list,
        description="Phase B: qualifiers structurés (temporal/spatial/version/condition/scope_limit) dérivés du verbatim. Enrichit le retrieval pour questions conditionnelles/lifecycle."
    )

    procedure_role: Optional[str] = Field(
        default=None,
        description="Phase B: rôle procédural si le claim est une étape ('PREREQUISITE'|'STEP'|'OUTCOME'). None si non-procédural."
    )

    procedure_id: Optional[str] = Field(
        default=None,
        description="Phase B: ID de la :Procedure à laquelle ce claim appartient (foreign key). None si non-procédural."
    )

    step_index: Optional[int] = Field(
        default=None,
        description="Phase B: ordre du claim dans la procédure (1-based). None si non-procédural."
    )

    open_predicate: Optional[bool] = Field(
        default=None,
        description="P1.3.5 (open-then-canonicalize): True si structured_form.predicate est un prédicat libre (hors whitelist) conservé pour le rappel au lieu d'être droppé. None/False si prédicat canonique."
    )

    @field_validator("text")
    @classmethod
    def validate_text_not_too_long(cls, v: str) -> str:
        """Une claim doit dire UNE chose précise (max 500 chars)."""
        if len(v) > 500:
            raise ValueError(
                f"Claim text too long ({len(v)} chars). "
                "A claim must say ONE precise thing."
            )
        return v

    @field_validator("verbatim_quote")
    @classmethod
    def validate_verbatim_not_empty(cls, v: str) -> str:
        """Le verbatim est OBLIGATOIRE et ne peut pas être vide."""
        if not v or not v.strip():
            raise ValueError("verbatim_quote is required and cannot be empty")
        return v.strip()

    def compute_fingerprint(self) -> str:
        """
        Calcule un fingerprint pour déduplication.

        Même fingerprint = même claim sémantique (pour clustering).
        """
        components = [
            self.doc_id,
            self.text.lower().strip(),
            self.scope.to_scope_key(),
        ]
        content = ":".join(components)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def compute_content_fingerprint(self) -> str:
        """
        Calcule un fingerprint basé sur le contenu seul (sans doc_id).

        Permet le matching cross-document futur.
        """
        components = [
            self.text.lower().strip(),
            self.scope.to_scope_key(),
        ]
        content = ":".join(components)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        props = {
            "claim_id": self.claim_id,
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "claim_type": self.claim_type.value,
            "verbatim_quote": self.verbatim_quote,
            "passage_id": self.passage_id,
            "unit_ids": self.unit_ids,
            "confidence": self.confidence,
            "cluster_id": self.cluster_id,
            "language": self.language,
            "created_at": self.created_at.isoformat(),
            "fingerprint": self.compute_fingerprint(),
            "content_fingerprint": self.content_fingerprint,
        }
        # Ajouter les propriétés de scope
        props.update(self.scope.to_neo4j_properties())
        # V1.1: Add structured_form as JSON string
        if self.structured_form:
            props["structured_form_json"] = json.dumps(self.structured_form)
            # Phase A3.8-prep (2026-05-21) : dénormaliser le triplet subject /
            # predicate / object pour permettre les Cypher A3 par indexes
            # (cf doc/ongoing/POST_A38_ROOT_CAUSE_AUDIT_2026-05-21.md §6).
            # structured_form_json reste l'autoritatif (rétro-compat 100%).
            sf_subject = self.structured_form.get("subject")
            sf_predicate = self.structured_form.get("predicate")
            sf_object = self.structured_form.get("object")
            if sf_subject:
                props["subject_canonical"] = sf_subject
            if sf_predicate:
                props["predicate"] = sf_predicate
            if sf_object:
                # `object_canonical` (pas `value` ni `object`) — clarifie que
                # c'est le `object` du structured_form (ADR_PARSE_EVALUATE_RUNTIME §4
                # mapping documenté).
                props["object_canonical"] = sf_object
        # A4.2 (22/05/2026) — SubjectIndexer indépendant
        # Si subject_canonical n'a PAS été défini par SF.subject ci-dessus,
        # et qu'on a un subject_canonical posé par le SubjectIndexer, on l'écrit.
        # Cohérence : SF.subject prend toujours priorité s'il existe.
        if "subject_canonical" not in props and self.subject_canonical:
            props["subject_canonical"] = self.subject_canonical
        # marginal flag : True si pas de subject naturel (claim descriptif).
        # Exclus du retrieval principal côté runtime_v6.
        if self.marginal is not None:
            props["marginal"] = self.marginal
        if self.subject_extraction_confidence is not None:
            props["subject_extraction_confidence"] = self.subject_extraction_confidence
        # V1.3: Quality gate fields
        if self.quality_status:
            props["quality_status"] = self.quality_status
        if self.quality_scores:
            props["quality_scores_json"] = json.dumps(self.quality_scores)
        if self.quality_reasons:
            props["quality_reasons"] = self.quality_reasons
        # V1.4: Champion/Redundant fields
        if self.is_champion is not None:
            props["is_champion"] = self.is_champion
        if self.redundant is not None:
            props["redundant"] = self.redundant
        if self.champion_claim_id:
            props["champion_claim_id"] = self.champion_claim_id
        # Phase B (25/05/2026) : qualifiers + rôle procédural
        if self.qualifiers:
            props["qualifiers_json"] = json.dumps(
                [q.model_dump() for q in self.qualifiers], ensure_ascii=False
            )
        if self.procedure_role:
            props["procedure_role"] = self.procedure_role
        if self.procedure_id:
            props["procedure_id"] = self.procedure_id
        if self.step_index is not None:
            props["step_index"] = self.step_index
        # P1.3.5 : prédicat ouvert (hors whitelist) conservé
        if self.open_predicate is not None:
            props["open_predicate"] = self.open_predicate
        return props

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "Claim":
        """Construit une Claim depuis un record Neo4j."""
        scope = ClaimScope(
            version=record.get("scope_version"),
            region=record.get("scope_region"),
            edition=record.get("scope_edition"),
            conditions=record.get("scope_conditions") or [],
        )

        # V1.1: Parse structured_form from JSON
        structured_form = None
        if record.get("structured_form_json"):
            try:
                structured_form = json.loads(record["structured_form_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        # V1.3: Parse quality_scores from JSON
        quality_scores = None
        if record.get("quality_scores_json"):
            try:
                quality_scores = json.loads(record["quality_scores_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Phase B (25/05/2026) : parse qualifiers from JSON
        qualifiers: List[ClaimQualifier] = []
        if record.get("qualifiers_json"):
            try:
                raw_quals = json.loads(record["qualifiers_json"])
                qualifiers = [ClaimQualifier(**q) for q in raw_quals]
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        return cls(
            claim_id=record["claim_id"],
            tenant_id=record["tenant_id"],
            doc_id=record["doc_id"],
            text=record["text"],
            claim_type=ClaimType(record["claim_type"]),
            scope=scope,
            verbatim_quote=record["verbatim_quote"],
            passage_id=record["passage_id"],
            unit_ids=record.get("unit_ids") or [],
            confidence=record.get("confidence", 0.0),
            cluster_id=record.get("cluster_id"),
            language=record.get("language", "en"),
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at")
            else datetime.utcnow(),
            structured_form=structured_form,
            content_fingerprint=record.get("content_fingerprint"),
            quality_status=record.get("quality_status"),
            quality_scores=quality_scores,
            quality_reasons=record.get("quality_reasons"),
            is_champion=record.get("is_champion"),
            redundant=record.get("redundant"),
            champion_claim_id=record.get("champion_claim_id"),
            qualifiers=qualifiers,
            procedure_role=record.get("procedure_role"),
            procedure_id=record.get("procedure_id"),
            step_index=record.get("step_index"),
            open_predicate=record.get("open_predicate"),
        )


__all__ = [
    "Claim",
    "ClaimType",
    "ClaimScope",
    "ClaimQualifier",
    "QualifierType",
]
