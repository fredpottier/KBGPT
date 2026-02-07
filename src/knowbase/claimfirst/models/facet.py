# src/knowbase/claimfirst/models/facet.py
"""
Modèle Facet - Axe de navigation pour les Claims.

Facet = navigation, inféré par patterns déterministes (réutilise ClaimKeyPatterns).
PAS de LLM pour le matching - déterministe uniquement.

Une Facet représente un axe de catégorisation des claims:
- Domain: Domaine thématique (security.encryption, compliance.gdpr)
- Risk: Niveau de risque associé
- Obligation: Type d'obligation (must, should, may)
- Limitation: Restriction ou contrainte
- Capability: Capacité ou fonctionnalité
- Procedure: Étape procédurale
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FacetKind(str, Enum):
    """Types de facettes pour catégorisation des claims."""

    DOMAIN = "domain"
    """Domaine thématique (ex: security, compliance, operations)."""

    RISK = "risk"
    """Niveau de risque (ex: high, medium, low)."""

    OBLIGATION = "obligation"
    """Type d'obligation (ex: mandatory, recommended, optional)."""

    LIMITATION = "limitation"
    """Restriction ou contrainte (ex: size_limit, region_restriction)."""

    CAPABILITY = "capability"
    """Capacité ou fonctionnalité (ex: encryption, backup, monitoring)."""

    PROCEDURE = "procedure"
    """Étape procédurale (ex: setup, configuration, migration)."""


class Facet(BaseModel):
    """
    Facet - Axe de navigation pour les Claims.

    Une Facet catégorise les claims selon des axes prédéfinis,
    permettant la navigation et le filtrage.

    Attributes:
        facet_id: Identifiant unique (format: "facet_{domain}_{kind}")
        tenant_id: Tenant multi-locataire
        facet_name: Nom lisible de la facette
        facet_kind: Type de facette
        domain: Domaine hiérarchique (ex: "security.encryption")
        canonical_question: Question associée pour requêtes
    """

    facet_id: str = Field(
        ...,
        description="Identifiant unique (format: 'facet_{domain}_{kind}')"
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
        ...,
        description="Type de facette"
    )

    domain: str = Field(
        ...,
        description="Domaine hiérarchique (ex: 'security.encryption')"
    )

    canonical_question: str = Field(
        default="",
        description="Question associée pour requêtes"
    )

    # Métadonnées pour hiérarchie
    parent_domain: Optional[str] = Field(
        default=None,
        description="Domaine parent (ex: 'security' pour 'security.encryption')"
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

        # Match exact
        if self.domain == query_domain:
            return True

        # Match hiérarchique (query est préfixe)
        if self.domain.startswith(query_domain + "."):
            return True

        return False

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        return {
            "facet_id": self.facet_id,
            "tenant_id": self.tenant_id,
            "facet_name": self.facet_name,
            "facet_kind": self.facet_kind.value,
            "domain": self.domain,
            "canonical_question": self.canonical_question,
            "parent_domain": self.parent_domain,
            "domain_root": self.domain_root,
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "Facet":
        """Construit une Facet depuis un record Neo4j."""
        return cls(
            facet_id=record["facet_id"],
            tenant_id=record["tenant_id"],
            facet_name=record["facet_name"],
            facet_kind=FacetKind(record["facet_kind"]),
            domain=record["domain"],
            canonical_question=record.get("canonical_question", ""),
            parent_domain=record.get("parent_domain"),
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
        Factory pour créer une Facet depuis un domaine.

        Args:
            domain: Domaine hiérarchique (ex: "security.encryption")
            kind: Type de facette
            tenant_id: Tenant ID
            canonical_question: Question canonique optionnelle

        Returns:
            Facet configurée
        """
        # Générer facet_id
        facet_id = f"facet_{domain.replace('.', '_')}_{kind.value}"

        # Générer facet_name depuis domain
        name_parts = domain.split(".")
        facet_name = " / ".join(part.replace("_", " ").title() for part in name_parts)

        # Calculer parent_domain
        parent_domain = None
        if len(name_parts) > 1:
            parent_domain = ".".join(name_parts[:-1])

        return cls(
            facet_id=facet_id,
            tenant_id=tenant_id,
            facet_name=facet_name,
            facet_kind=kind,
            domain=domain,
            canonical_question=canonical_question,
            parent_domain=parent_domain,
        )


# Facettes prédéfinies (bootstrap)
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

    Args:
        tenant_id: Tenant ID

    Returns:
        Liste de Facets prédéfinies
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


__all__ = [
    "Facet",
    "FacetKind",
    "PREDEFINED_FACETS",
    "get_predefined_facets",
]
