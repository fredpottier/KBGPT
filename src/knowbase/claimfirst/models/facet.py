# src/knowbase/claimfirst/models/facet.py
"""
Modèle Facet - Axe de navigation pour les Claims.

Facet Registry émergent 3-tier :
- Tier 1 : Extraction LLM (FacetCandidateExtractor, 1 appel/doc)
- Tier 2 : Registre gouverné (FacetRegistry, lifecycle candidate→validated→deprecated)
- Tier 3 : Affectation déterministe (FacetMatcher, 4 signaux pondérés)

FacetFamily remplace FacetKind : thematic | normative | operational.
FacetKind est conservé comme alias pour rétrocompatibilité.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class FacetFamily(str, Enum):
    """Famille de facette — séparation thème vs rôle discursif."""

    THEMATIC = "thematic"
    """De quoi parle le document (domaine métier)."""

    NORMATIVE = "normative"
    """Obligations, conformité, régulation."""

    OPERATIONAL = "operational"
    """Opérations, SLA, backup, monitoring."""


class FacetLifecycle(str, Enum):
    """Lifecycle d'une facette dans le registre."""

    CANDIDATE = "candidate"
    """Facette découverte, pas encore validée."""

    VALIDATED = "validated"
    """Facette promue (≥3 docs, ≥2 familles distinctes)."""

    DEPRECATED = "deprecated"
    """Facette dépréciée (action admin manuelle)."""


# Alias rétrocompatible : FacetKind = FacetFamily
# Les anciens codes qui importent FacetKind continuent de fonctionner.
# Les valeurs changent (domain→thematic, etc.) mais FacetKind reste importable.
class FacetKind(str, Enum):
    """Types de facettes pour catégorisation des claims (LEGACY — utiliser FacetFamily)."""

    DOMAIN = "domain"
    RISK = "risk"
    OBLIGATION = "obligation"
    LIMITATION = "limitation"
    CAPABILITY = "capability"
    PROCEDURE = "procedure"


# Mapping FacetKind legacy → FacetFamily
_KIND_TO_FAMILY = {
    FacetKind.DOMAIN: FacetFamily.THEMATIC,
    FacetKind.RISK: FacetFamily.NORMATIVE,
    FacetKind.OBLIGATION: FacetFamily.NORMATIVE,
    FacetKind.LIMITATION: FacetFamily.OPERATIONAL,
    FacetKind.CAPABILITY: FacetFamily.OPERATIONAL,
    FacetKind.PROCEDURE: FacetFamily.OPERATIONAL,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Facet(BaseModel):
    """
    Facet - Axe de navigation pour les Claims.

    Supporte le lifecycle émergent (candidate → validated → deprecated)
    et le tracking multi-document pour promotion automatique.
    """

    facet_id: str = Field(
        ...,
        description="Identifiant unique (format: 'facet_{dimension_key}')"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    facet_name: str = Field(
        ...,
        min_length=1,
        description="Nom lisible de la facette"
    )

    facet_kind: FacetKind = Field(
        default=FacetKind.DOMAIN,
        description="Type de facette (LEGACY — préférer facet_family)"
    )

    facet_family: FacetFamily = Field(
        default=FacetFamily.THEMATIC,
        description="Famille de facette (thematic | normative | operational)"
    )

    domain: str = Field(
        ...,
        description="Domaine hiérarchique / dimension_key (ex: 'security.encryption')"
    )

    canonical_question: str = Field(
        default="",
        description="Question associée pour requêtes"
    )

    # Métadonnées hiérarchie
    parent_domain: Optional[str] = Field(
        default=None,
        description="Domaine parent (ex: 'security' pour 'security.encryption')"
    )

    # Lifecycle
    lifecycle: FacetLifecycle = Field(
        default=FacetLifecycle.CANDIDATE,
        description="Statut dans le registre"
    )

    source_doc_ids: List[str] = Field(
        default_factory=list,
        description="IDs des documents source"
    )

    source_doc_count: int = Field(
        default=0,
        description="Nombre de documents source distincts"
    )

    promoted_at: Optional[str] = Field(
        default=None,
        description="Date ISO de promotion vers VALIDATED"
    )

    created_at: str = Field(
        default_factory=_now_iso,
        description="Date ISO de création"
    )

    # Enrichissement
    keywords: List[str] = Field(
        default_factory=list,
        description="Mots-clés associés (3-5 par extraction)"
    )

    aliases: List[str] = Field(
        default_factory=list,
        description="Quasi-synonymes détectés"
    )

    example_claim_ids: List[str] = Field(
        default_factory=list,
        description="3-5 claims représentatives"
    )

    last_seen_at: Optional[str] = Field(
        default=None,
        description="Dernière apparition (ISO date)"
    )

    promotion_reason: Optional[str] = Field(
        default=None,
        description="Raison de promotion (ex: '3 docs, 2 familles distinctes')"
    )

    # Near-duplicate tracking
    near_duplicate_of: Optional[str] = Field(
        default=None,
        description="facet_id si flaggé comme quasi-doublon"
    )

    @property
    def domain_parts(self) -> list[str]:
        """Retourne les parties du domaine hiérarchique."""
        return self.domain.split(".")

    @property
    def domain_root(self) -> str:
        """Retourne le domaine racine."""
        parts = self.domain_parts
        return parts[0] if parts else ""

    def matches_domain(self, query_domain: str) -> bool:
        """
        Vérifie si la facette correspond à un domaine.

        Supporte la correspondance hiérarchique:
        - "security" matche "security", "security.encryption", etc.
        - "security.encryption" matche seulement "security.encryption"
        """
        if not query_domain:
            return False
        if self.domain == query_domain:
            return True
        if self.domain.startswith(query_domain + "."):
            return True
        return False

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        props = {
            "facet_id": self.facet_id,
            "tenant_id": self.tenant_id,
            "facet_name": self.facet_name,
            "facet_kind": self.facet_kind.value,
            "facet_family": self.facet_family.value,
            "domain": self.domain,
            "canonical_question": self.canonical_question,
            "parent_domain": self.parent_domain,
            "domain_root": self.domain_root,
            "lifecycle": self.lifecycle.value,
            "source_doc_count": self.source_doc_count,
            "created_at": self.created_at,
            "keywords": self.keywords,
            "aliases": self.aliases,
        }
        if self.promoted_at:
            props["promoted_at"] = self.promoted_at
        if self.last_seen_at:
            props["last_seen_at"] = self.last_seen_at
        if self.promotion_reason:
            props["promotion_reason"] = self.promotion_reason
        if self.near_duplicate_of:
            props["near_duplicate_of"] = self.near_duplicate_of
        if self.source_doc_ids:
            props["source_doc_ids"] = self.source_doc_ids
        if self.example_claim_ids:
            props["example_claim_ids"] = self.example_claim_ids
        return props

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "Facet":
        """Construit une Facet depuis un record Neo4j."""
        # Rétrocompatibilité : facet_family peut ne pas exister
        family_str = record.get("facet_family")
        if family_str:
            family = FacetFamily(family_str)
        else:
            kind = FacetKind(record.get("facet_kind", "domain"))
            family = _KIND_TO_FAMILY.get(kind, FacetFamily.THEMATIC)

        lifecycle_str = record.get("lifecycle")
        lifecycle = FacetLifecycle(lifecycle_str) if lifecycle_str else FacetLifecycle.VALIDATED

        return cls(
            facet_id=record["facet_id"],
            tenant_id=record["tenant_id"],
            facet_name=record["facet_name"],
            facet_kind=FacetKind(record.get("facet_kind", "domain")),
            facet_family=family,
            domain=record["domain"],
            canonical_question=record.get("canonical_question", ""),
            parent_domain=record.get("parent_domain"),
            lifecycle=lifecycle,
            source_doc_ids=record.get("source_doc_ids", []) or [],
            source_doc_count=record.get("source_doc_count", 0) or 0,
            promoted_at=record.get("promoted_at"),
            created_at=record.get("created_at", _now_iso()),
            keywords=record.get("keywords", []) or [],
            aliases=record.get("aliases", []) or [],
            example_claim_ids=record.get("example_claim_ids", []) or [],
            last_seen_at=record.get("last_seen_at"),
            promotion_reason=record.get("promotion_reason"),
            near_duplicate_of=record.get("near_duplicate_of"),
        )

    @classmethod
    def create_from_domain(
        cls,
        domain: str,
        kind: FacetKind,
        tenant_id: str,
        canonical_question: str = "",
    ) -> "Facet":
        """
        Factory pour créer une Facet depuis un domaine (rétrocompatible).

        Args:
            domain: Domaine hiérarchique (ex: "security.encryption")
            kind: Type de facette (legacy FacetKind)
            tenant_id: Tenant ID
            canonical_question: Question canonique optionnelle
        """
        facet_id = f"facet_{domain.replace('.', '_')}_{kind.value}"
        name_parts = domain.split(".")
        facet_name = " / ".join(part.replace("_", " ").title() for part in name_parts)
        parent_domain = ".".join(name_parts[:-1]) if len(name_parts) > 1 else None

        return cls(
            facet_id=facet_id,
            tenant_id=tenant_id,
            facet_name=facet_name,
            facet_kind=kind,
            facet_family=_KIND_TO_FAMILY.get(kind, FacetFamily.THEMATIC),
            domain=domain,
            canonical_question=canonical_question,
            parent_domain=parent_domain,
        )

    @classmethod
    def create_from_candidate(
        cls,
        dimension_key: str,
        canonical_name: str,
        facet_family: FacetFamily,
        tenant_id: str,
        keywords: Optional[List[str]] = None,
        source_doc_id: Optional[str] = None,
    ) -> "Facet":
        """
        Factory pour créer une Facet depuis un FacetCandidate (Tier 1).

        Args:
            dimension_key: Clé normalisée (ex: "compliance.data_protection")
            canonical_name: Nom lisible
            facet_family: Famille de facette
            tenant_id: Tenant ID
            keywords: Mots-clés associés
            source_doc_id: Document source
        """
        facet_id = f"facet_{dimension_key.replace('.', '_')}"
        parent_domain = None
        parts = dimension_key.split(".")
        if len(parts) > 1:
            parent_domain = ".".join(parts[:-1])

        return cls(
            facet_id=facet_id,
            tenant_id=tenant_id,
            facet_name=canonical_name,
            facet_kind=FacetKind.DOMAIN,
            facet_family=facet_family,
            domain=dimension_key,
            parent_domain=parent_domain,
            lifecycle=FacetLifecycle.CANDIDATE,
            keywords=keywords or [],
            source_doc_ids=[source_doc_id] if source_doc_id else [],
            source_doc_count=1 if source_doc_id else 0,
            created_at=_now_iso(),
            last_seen_at=_now_iso(),
        )


# Facettes prédéfinies (bootstrap / seed)
PREDEFINED_FACETS = [
    # Security
    ("security", FacetKind.DOMAIN, "What security measures are in place?"),
    ("security.encryption", FacetKind.CAPABILITY, "What encryption is used?"),
    ("security.authentication", FacetKind.CAPABILITY, "How is authentication handled?"),
    ("security.access_control", FacetKind.CAPABILITY, "How is access controlled?"),

    # Compliance
    ("compliance", FacetKind.DOMAIN, "What compliance certifications are available?"),
    ("compliance.gdpr", FacetKind.DOMAIN, "Is the service GDPR compliant?"),
    ("compliance.retention", FacetKind.DOMAIN, "What are the data retention policies?"),
    ("compliance.residency", FacetKind.DOMAIN, "What are the data residency requirements?"),

    # Operations
    ("operations", FacetKind.DOMAIN, "What operational capabilities are available?"),
    ("operations.backup", FacetKind.CAPABILITY, "How are backups performed?"),
    ("operations.patching", FacetKind.PROCEDURE, "How are patches applied?"),
    ("operations.monitoring", FacetKind.CAPABILITY, "What monitoring is available?"),

    # SLA
    ("sla", FacetKind.DOMAIN, "What are the SLA terms?"),
    ("sla.availability", FacetKind.OBLIGATION, "What is the availability SLA?"),
    ("sla.recovery", FacetKind.OBLIGATION, "What are the recovery objectives?"),

    # Infrastructure
    ("infrastructure", FacetKind.DOMAIN, "What infrastructure is used?"),
    ("infrastructure.sizing", FacetKind.LIMITATION, "What are the size limits?"),
    ("infrastructure.scalability", FacetKind.CAPABILITY, "How does it scale?"),

    # Compatibility
    ("compatibility", FacetKind.DOMAIN, "What compatibility requirements exist?"),
    ("compatibility.version", FacetKind.LIMITATION, "What versions are supported?"),
    ("compatibility.integration", FacetKind.CAPABILITY, "What integrations are available?"),
]


def get_predefined_facets(tenant_id: str) -> list[Facet]:
    """
    Retourne les facettes prédéfinies pour un tenant.
    """
    return [
        Facet.create_from_domain(
            domain=domain,
            kind=kind,
            tenant_id=tenant_id,
            canonical_question=question,
        )
        for domain, kind, question in PREDEFINED_FACETS
    ]


def get_seed_facets(tenant_id: str) -> list[Facet]:
    """
    Retourne les facettes prédéfinies comme seed bootstrap pour le FacetRegistry.

    Seed facets sont VALIDATED avec source_doc_count=0 (marquées comme seed).
    Le FacetRegistry les charge si le registre est vide.
    """
    seeds = []
    for domain, kind, question in PREDEFINED_FACETS:
        facet = Facet.create_from_domain(
            domain=domain,
            kind=kind,
            tenant_id=tenant_id,
            canonical_question=question,
        )
        facet.lifecycle = FacetLifecycle.VALIDATED
        facet.source_doc_count = 0
        facet.promotion_reason = "seed_bootstrap"
        seeds.append(facet)
    return seeds


__all__ = [
    "Facet",
    "FacetFamily",
    "FacetKind",
    "FacetLifecycle",
    "PREDEFINED_FACETS",
    "get_predefined_facets",
    "get_seed_facets",
]
