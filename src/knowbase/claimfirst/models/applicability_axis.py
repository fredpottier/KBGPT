# src/knowbase/claimfirst/models/applicability_axis.py
"""
Modèle ApplicabilityAxis - Axe d'applicabilité pour les claims.

INV-25: Axis keys neutres + display_name optionnel
INV-14: compare() → None si ordre inconnu
INV-12: ClaimKey validé si ≥2 docs ET ≥2 valeurs distinctes

Principe: Un axe d'applicabilité permet de qualifier le contexte
dans lequel une claim est valide (version, année, date effective...).

L'axe est découvert du corpus, pas hardcodé. Les clés sont neutres
(release_id, year, effective_date) pour rester agnostique domaine.
Un display_name optionnel capture le terme trouvé dans le corpus.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field


class OrderType(str, Enum):
    """Type d'ordre pour un axe d'applicabilité."""

    TOTAL = "total"
    """Ordre total défini (ex: versions numériques 1.0 < 2.0 < 3.0)."""

    PARTIAL = "partial"
    """Ordre partiel (certains éléments comparables, pas tous)."""

    NONE = "none"
    """Pas d'ordre défini (valeurs catégoriques)."""


class OrderingConfidence(str, Enum):
    """Niveau de confiance dans l'ordonnabilité d'un axe."""

    CERTAIN = "certain"
    """Ordre certain (numériques, semver, années)."""

    INFERRED = "inferred"
    """Ordre inféré depuis patterns (Phase I/II/III, Early/Late)."""

    UNKNOWN = "unknown"
    """L'axe semble orderable mais l'ordre est inconnu."""


class ApplicabilityAxis(BaseModel):
    """
    Axe d'applicabilité pour qualifier le contexte des claims.

    INV-25: Clés neutres core + display_name optionnel
    INV-14: compare() retourne None si ordering_confidence == UNKNOWN

    Attributes:
        axis_id: Identifiant unique de l'axe
        tenant_id: Tenant multi-locataire
        axis_key: Clé neutre (release_id, year, effective_date...)
        axis_display_name: Label textuel trouvé dans le corpus (optionnel)
        is_orderable: Si l'axe supporte la comparaison
        order_type: Type d'ordre (total, partial, none)
        ordering_confidence: Niveau de confiance dans l'ordre
        known_values: Valeurs connues pour cet axe
        value_order: Ordre des valeurs (None si ordering_confidence == UNKNOWN)
        doc_count: Nombre de documents où cet axe a été trouvé
        source_doc_ids: Documents source
    """

    axis_id: str = Field(
        ...,
        description="Identifiant unique de l'axe"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    # INV-25: Clé neutre + display_name optionnel
    axis_key: str = Field(
        ...,
        description="Clé neutre: release_id, year, effective_date..."
    )

    axis_display_name: Optional[str] = Field(
        default=None,
        description="Label textuel trouvé dans le corpus: version, release, etc."
    )

    is_orderable: bool = Field(
        default=False,
        description="Si l'axe supporte la comparaison de valeurs"
    )

    order_type: OrderType = Field(
        default=OrderType.NONE,
        description="Type d'ordre (total, partial, none)"
    )

    ordering_confidence: OrderingConfidence = Field(
        default=OrderingConfidence.UNKNOWN,
        description="Niveau de confiance dans l'ordonnabilité"
    )

    known_values: List[str] = Field(
        default_factory=list,
        description="Valeurs connues pour cet axe"
    )

    # INV-14: None si ordering_confidence == UNKNOWN
    value_order: Optional[List[str]] = Field(
        default=None,
        description="Ordre des valeurs (du plus ancien au plus récent), None si inconnu"
    )

    doc_count: int = Field(
        default=0,
        ge=0,
        description="Nombre de documents où cet axe apparaît"
    )

    source_doc_ids: List[str] = Field(
        default_factory=list,
        description="IDs des documents source"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de création"
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de dernière mise à jour"
    )

    def compare(self, value_a: str, value_b: str) -> Optional[int]:
        """
        Compare deux valeurs de cet axe.

        INV-14: Retourne None si l'ordre est inconnu.

        Args:
            value_a: Première valeur
            value_b: Deuxième valeur

        Returns:
            -1 si value_a < value_b
            0 si value_a == value_b
            1 si value_a > value_b
            None si comparaison impossible ou ordre inconnu
        """
        # INV-14: Jamais inventer un ordre
        if self.ordering_confidence == OrderingConfidence.UNKNOWN:
            return None

        if not self.is_orderable:
            return None

        if self.value_order is None:
            return None

        # Normaliser les valeurs
        value_a_norm = value_a.strip()
        value_b_norm = value_b.strip()

        # Cas identique
        if value_a_norm == value_b_norm:
            return 0

        # Chercher dans l'ordre connu
        try:
            idx_a = self.value_order.index(value_a_norm)
            idx_b = self.value_order.index(value_b_norm)
            if idx_a < idx_b:
                return -1
            elif idx_a > idx_b:
                return 1
            return 0
        except ValueError:
            # Valeur non trouvée dans l'ordre
            return None

    def get_latest_value(self) -> Optional[str]:
        """
        Retourne la valeur la plus récente (dernière dans l'ordre).

        INV-14: Retourne None si l'ordre est inconnu.

        Returns:
            Valeur la plus récente ou None
        """
        if self.ordering_confidence == OrderingConfidence.UNKNOWN:
            return None

        if self.value_order and len(self.value_order) > 0:
            return self.value_order[-1]

        return None

    def add_value(self, value: str, doc_id: Optional[str] = None) -> bool:
        """
        Ajoute une valeur connue pour cet axe.

        Args:
            value: Valeur à ajouter
            doc_id: Document source (optionnel)

        Returns:
            True si la valeur a été ajoutée
        """
        normalized = value.strip()
        if normalized and normalized not in self.known_values:
            self.known_values.append(normalized)
            if doc_id and doc_id not in self.source_doc_ids:
                self.source_doc_ids.append(doc_id)
                self.doc_count = len(self.source_doc_ids)
            self.updated_at = datetime.utcnow()
            return True
        return False

    def is_validated_claimkey(self) -> bool:
        """
        Vérifie si cet axe est un ClaimKey validé.

        INV-12: ClaimKey validé si ≥2 docs ET ≥2 valeurs distinctes.
        Pas de timeline sur 1 seul doc ou 1 seule valeur.

        Returns:
            True si l'axe est un ClaimKey validé
        """
        return self.doc_count >= 2 and len(self.known_values) >= 2

    def compute_axis_hash(self) -> str:
        """
        Calcule un hash stable pour l'axe.

        Returns:
            Hash hexadécimal sur 12 caractères
        """
        content = f"{self.tenant_id}:{self.axis_key}"
        return hashlib.sha256(content.encode()).hexdigest()[:12]

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en propriétés pour Neo4j."""
        return {
            "axis_id": self.axis_id,
            "tenant_id": self.tenant_id,
            "axis_key": self.axis_key,
            "axis_display_name": self.axis_display_name,
            "is_orderable": self.is_orderable,
            "order_type": self.order_type.value,
            "ordering_confidence": self.ordering_confidence.value,
            "known_values": self.known_values if self.known_values else None,
            "value_order": self.value_order if self.value_order else None,
            "doc_count": self.doc_count,
            "source_doc_ids": self.source_doc_ids if self.source_doc_ids else None,
            "axis_hash": self.compute_axis_hash(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_neo4j_record(cls, record: Dict[str, Any]) -> "ApplicabilityAxis":
        """Construit un ApplicabilityAxis depuis un record Neo4j."""
        return cls(
            axis_id=record["axis_id"],
            tenant_id=record["tenant_id"],
            axis_key=record["axis_key"],
            axis_display_name=record.get("axis_display_name"),
            is_orderable=record.get("is_orderable", False),
            order_type=OrderType(record.get("order_type", "none")),
            ordering_confidence=OrderingConfidence(record.get("ordering_confidence", "unknown")),
            known_values=record.get("known_values") or [],
            value_order=record.get("value_order"),
            doc_count=record.get("doc_count", 0),
            source_doc_ids=record.get("source_doc_ids") or [],
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"])
            if record.get("updated_at") else datetime.utcnow(),
        )

    @classmethod
    def create_new(
        cls,
        tenant_id: str,
        axis_key: str,
        axis_display_name: Optional[str] = None,
        doc_id: Optional[str] = None,
    ) -> "ApplicabilityAxis":
        """
        Factory pour créer un nouvel ApplicabilityAxis.

        Args:
            tenant_id: Tenant ID
            axis_key: Clé neutre de l'axe
            axis_display_name: Label textuel trouvé (optionnel)
            doc_id: Document source (optionnel)

        Returns:
            Nouvel ApplicabilityAxis
        """
        axis_id = f"axis_{hashlib.md5(f'{tenant_id}:{axis_key}'.encode()).hexdigest()[:12]}"

        return cls(
            axis_id=axis_id,
            tenant_id=tenant_id,
            axis_key=axis_key,
            axis_display_name=axis_display_name,
            source_doc_ids=[doc_id] if doc_id else [],
            doc_count=1 if doc_id else 0,
        )


# Clés d'axes neutres prédéfinies (bootstrap, pas exhaustif)
NEUTRAL_AXIS_KEYS = frozenset({
    "release_id",      # Identifiant de release/version (neutre IT)
    "year",            # Année calendaire
    "effective_date",  # Date d'entrée en vigueur
    "edition",         # Édition (Enterprise, Standard...)
    "region",          # Région géographique
    "phase",           # Phase de déploiement
    "tier",            # Niveau/tier de service
})


__all__ = [
    "ApplicabilityAxis",
    "OrderType",
    "OrderingConfidence",
    "NEUTRAL_AXIS_KEYS",
]
