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
        )


__all__ = [
    "Claim",
    "ClaimType",
    "ClaimScope",
]
