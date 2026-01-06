"""
Modèles pour la Marker Normalization Layer.

ADR: doc/ongoing/ADR_MARKER_NORMALIZATION_LAYER.md

Architecture à 2 niveaux:
1. MarkerMention (brut) - Ce qui est écrit dans le document
2. CanonicalMarker (normalisé) - Forme standard après règles/aliases

Relation: MarkerMention -[:CANONICALIZES_TO]-> CanonicalMarker
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
from datetime import datetime
import uuid


class NormalizationStatus(str, Enum):
    """Statut de normalisation d'une mention."""
    RESOLVED = "resolved"           # Normalisé avec succès
    UNRESOLVED = "unresolved"       # Pas assez de contexte pour normaliser
    BLACKLISTED = "blacklisted"     # Faux positif connu (rejeté)
    PENDING_REVIEW = "pending"      # Suggestion en attente d'approbation


class LexicalShape(str, Enum):
    """Forme lexicale du marker (description, pas sémantique)."""
    NUMERIC_4 = "numeric_4"         # 1809, 2020, 2508
    NUMERIC_YEAR = "numeric_year"   # 2024, 2025
    ALPHANUMERIC = "alphanumeric"   # FPS03, SP02
    VERSION = "version"             # v1.0.0, 3.2.1
    SEMANTIC_TOKEN = "semantic"     # Cloud, Private, Edition
    ENTITY_NUMERAL = "entity_numeral"  # "Edition 2508", "Version 3"
    UNKNOWN = "unknown"


@dataclass
class MarkerMention:
    """
    Mention brute d'un marker dans un document.

    C'est ce qui est ÉCRIT dans le document, sans interprétation.
    La mention peut être normalisée en CanonicalMarker via règles/aliases.

    Neo4j node: (:MarkerMention {id, raw_text, lexical_shape, ...})
    """
    # Identité
    id: str = field(default_factory=lambda: f"mm_{uuid.uuid4().hex[:12]}")
    raw_text: str = ""                  # Ce qui est écrit (ex: "Edition 2508")
    lexical_shape: LexicalShape = LexicalShape.UNKNOWN

    # Source
    doc_id: str = ""
    source_location: str = ""           # "cover", "title", "body", "footer"
    evidence_text: str = ""             # Contexte autour de la mention (~100 chars)
    page_index: Optional[int] = None
    zone: str = ""                      # "top", "main", "bottom"

    # Extraction metadata
    confidence_extraction: float = 0.0  # Confiance de l'extraction (0-1)
    extracted_by: str = ""              # "candidate_mining", "regex", etc.

    # Normalization status
    normalization_status: NormalizationStatus = NormalizationStatus.UNRESOLVED
    canonical_id: Optional[str] = None  # ID du CanonicalMarker si normalisé

    # Tenant & timestamps
    tenant_id: str = "default"
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise pour Neo4j."""
        return {
            "id": self.id,
            "raw_text": self.raw_text,
            "lexical_shape": self.lexical_shape.value,
            "doc_id": self.doc_id,
            "source_location": self.source_location,
            "evidence_text": self.evidence_text,
            "page_index": self.page_index,
            "zone": self.zone,
            "confidence_extraction": self.confidence_extraction,
            "extracted_by": self.extracted_by,
            "normalization_status": self.normalization_status.value,
            "canonical_id": self.canonical_id,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarkerMention":
        """Désérialise depuis Neo4j."""
        return cls(
            id=data.get("id", ""),
            raw_text=data.get("raw_text", ""),
            lexical_shape=LexicalShape(data.get("lexical_shape", "unknown")),
            doc_id=data.get("doc_id", ""),
            source_location=data.get("source_location", ""),
            evidence_text=data.get("evidence_text", ""),
            page_index=data.get("page_index"),
            zone=data.get("zone", ""),
            confidence_extraction=data.get("confidence_extraction", 0.0),
            extracted_by=data.get("extracted_by", ""),
            normalization_status=NormalizationStatus(
                data.get("normalization_status", "unresolved")
            ),
            canonical_id=data.get("canonical_id"),
            tenant_id=data.get("tenant_id", "default"),
            created_at=datetime.fromisoformat(data["created_at"])
                       if data.get("created_at") else None,
        )


@dataclass
class CanonicalMarker:
    """
    Forme canonique (normalisée) d'un marker.

    Un CanonicalMarker peut avoir plusieurs MarkerMention qui pointent vers lui.
    Il représente la forme "officielle" utilisée dans le KG.

    Neo4j node: (:CanonicalMarker {id, canonical_form, marker_type, ...})
    """
    # Identité
    id: str = field(default_factory=lambda: f"cm_{uuid.uuid4().hex[:12]}")
    canonical_form: str = ""            # Forme normalisée (ex: "S/4HANA 2508")

    # Dimensions (pour markers complexes)
    # Ex: "Clio 3 Phase 2" → {generation: "3", revision: "Phase 2"}
    dimensions: Dict[str, str] = field(default_factory=dict)

    # Type de marker (ouvert, pas enum fermé)
    marker_type: str = ""               # "product_version", "edition", "model_year", etc.

    # Entity Anchor (entité parente détectée dans le document)
    entity_anchor: str = ""             # Ex: "SAP S/4HANA", "Renault Clio"
    entity_anchor_id: Optional[str] = None  # ID du concept dans le KG

    # Création metadata
    created_by: str = ""                # "rule:regex_edition", "alias:manual", "user:admin"
    confidence: float = 1.0             # Confiance dans la normalisation

    # Statistiques
    mention_count: int = 0              # Nombre de mentions liées
    document_count: int = 0             # Nombre de documents

    # Tenant & timestamps
    tenant_id: str = "default"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise pour Neo4j."""
        return {
            "id": self.id,
            "canonical_form": self.canonical_form,
            "dimensions": self.dimensions,
            "marker_type": self.marker_type,
            "entity_anchor": self.entity_anchor,
            "entity_anchor_id": self.entity_anchor_id,
            "created_by": self.created_by,
            "confidence": self.confidence,
            "mention_count": self.mention_count,
            "document_count": self.document_count,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanonicalMarker":
        """Désérialise depuis Neo4j."""
        return cls(
            id=data.get("id", ""),
            canonical_form=data.get("canonical_form", ""),
            dimensions=data.get("dimensions", {}),
            marker_type=data.get("marker_type", ""),
            entity_anchor=data.get("entity_anchor", ""),
            entity_anchor_id=data.get("entity_anchor_id"),
            created_by=data.get("created_by", ""),
            confidence=data.get("confidence", 1.0),
            mention_count=data.get("mention_count", 0),
            document_count=data.get("document_count", 0),
            tenant_id=data.get("tenant_id", "default"),
            created_at=datetime.fromisoformat(data["created_at"])
                       if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"])
                       if data.get("updated_at") else None,
        )


@dataclass
class NormalizationRule:
    """
    Règle de normalisation (depuis config YAML).

    Types de règles:
    1. Alias exact: "Edition 2508" → "S/4HANA Cloud 2508"
    2. Regex pattern: "Edition\\s+(\\d{4})" + entity → "{entity} {$1}"
    """
    # Identité
    id: str = ""
    description: str = ""

    # Matching
    pattern: str = ""                   # Regex pattern ou valeur exacte
    is_regex: bool = False              # True si pattern est un regex

    # Requirements (garde-fous)
    requires_entity: bool = False       # Doit avoir un Entity Anchor
    requires_strong_entity: bool = False  # Entity doit être "forte" (haute confiance)
    requires_base_version: bool = False # Doit avoir une version parente

    # Output
    output_template: str = ""           # Template de sortie (ex: "{entity} {$1}")

    # Métadonnées
    priority: int = 0                   # Plus haut = testé en premier
    confidence: float = 1.0             # Confiance si cette règle match
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "pattern": self.pattern,
            "is_regex": self.is_regex,
            "requires_entity": self.requires_entity,
            "requires_strong_entity": self.requires_strong_entity,
            "requires_base_version": self.requires_base_version,
            "output_template": self.output_template,
            "priority": self.priority,
            "confidence": self.confidence,
            "enabled": self.enabled,
        }


@dataclass
class NormalizationResult:
    """
    Résultat d'une tentative de normalisation.
    """
    # Input
    mention: MarkerMention

    # Output
    status: NormalizationStatus
    canonical_marker: Optional[CanonicalMarker] = None

    # Métadonnées
    rule_applied: Optional[str] = None  # ID de la règle utilisée
    entity_anchor_found: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""                    # Explication (pour debug/audit)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mention_id": self.mention.id,
            "raw_text": self.mention.raw_text,
            "status": self.status.value,
            "canonical_form": self.canonical_marker.canonical_form
                             if self.canonical_marker else None,
            "canonical_id": self.canonical_marker.id if self.canonical_marker else None,
            "rule_applied": self.rule_applied,
            "entity_anchor": self.entity_anchor_found,
            "confidence": self.confidence,
            "reason": self.reason,
        }


__all__ = [
    "NormalizationStatus",
    "LexicalShape",
    "MarkerMention",
    "CanonicalMarker",
    "NormalizationRule",
    "NormalizationResult",
]
