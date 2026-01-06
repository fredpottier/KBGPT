"""
OSMOSE Navigation Layer - Types

Modèles de données pour la couche de navigation non-sémantique.
ADR: doc/ongoing/ADR_NAVIGATION_LAYER.md

Author: Claude Code
Date: 2026-01-01
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from knowbase.common.context_id import make_context_id, make_section_hash


class ContextNodeKind(str, Enum):
    """Types de ContextNode."""
    DOCUMENT = "document"   # DocumentContext - 1 par document
    SECTION = "section"     # SectionContext - ~5-20 par document
    WINDOW = "window"       # WindowContext - 1 par chunk (optionnel, désactivé par défaut)


class ContextNode(BaseModel):
    """
    Noeud de contexte pour la navigation layer.

    Label Neo4j: :ContextNode (+ sous-label spécifique)

    IMPORTANT: Ces noeuds sont pour la NAVIGATION uniquement.
    Ils ne doivent JAMAIS être utilisés pour le raisonnement sémantique.
    """
    context_id: str                     # Format: "doc:{doc_id}" ou "sec:{doc_id}:{hash}" ou "win:{chunk_id}"
    kind: ContextNodeKind               # Type de contexte
    tenant_id: str = "default"

    # Métadonnées
    doc_id: str                         # Document source
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_props(self) -> Dict[str, Any]:
        """Convertit en propriétés Neo4j."""
        return {
            "context_id": self.context_id,
            "kind": self.kind.value,
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "created_at": self.created_at.isoformat(),
        }


class DocumentContext(ContextNode):
    """
    Contexte au niveau document.

    Label Neo4j: :DocumentContext:ContextNode
    Cardinalité: 1 par document
    """
    kind: ContextNodeKind = ContextNodeKind.DOCUMENT

    # Métadonnées document
    document_name: Optional[str] = None
    document_type: Optional[str] = None

    @classmethod
    def create(cls, document_id: str, tenant_id: str = "default",
               document_name: Optional[str] = None,
               document_type: Optional[str] = None) -> "DocumentContext":
        """Factory pour créer un DocumentContext."""
        return cls(
            context_id=make_context_id(document_id),  # Utilise helper partagé
            doc_id=document_id,
            tenant_id=tenant_id,
            document_name=document_name,
            document_type=document_type,
        )

    def to_neo4j_props(self) -> Dict[str, Any]:
        props = super().to_neo4j_props()
        if self.document_name:
            props["document_name"] = self.document_name
        if self.document_type:
            props["document_type"] = self.document_type
        return props


class SectionContext(ContextNode):
    """
    Contexte au niveau section.

    Label Neo4j: :SectionContext:ContextNode
    Cardinalité: ~5-20 par document
    """
    kind: ContextNodeKind = ContextNodeKind.SECTION

    # Métadonnées section
    section_path: str                   # Ex: "1.2.3 Security Architecture"
    section_hash: str                   # Hash du section_path pour l'ID
    section_level: int = 0              # Niveau hiérarchique (0 = root)

    @classmethod
    def create(cls, document_id: str, section_path: str,
               tenant_id: str = "default",
               section_level: int = 0) -> "SectionContext":
        """Factory pour créer un SectionContext."""
        # Utilise helpers partagés pour cohérence Neo4j ↔ Qdrant
        section_hash = make_section_hash(document_id, section_path)
        return cls(
            context_id=make_context_id(document_id, section_path),
            doc_id=document_id,
            tenant_id=tenant_id,
            section_path=section_path,
            section_hash=section_hash,
            section_level=section_level,
        )

    def to_neo4j_props(self) -> Dict[str, Any]:
        props = super().to_neo4j_props()
        props["section_path"] = self.section_path
        props["section_hash"] = self.section_hash
        props["section_level"] = self.section_level
        return props


class WindowContext(ContextNode):
    """
    Contexte au niveau fenêtre/chunk.

    Label Neo4j: :WindowContext:ContextNode
    Cardinalité: 1 par chunk (linéaire avec corpus!)

    ATTENTION: Cette classe est désactivée par défaut (feature flag).
    Elle a une cardinalité linéaire avec le corpus et peut créer
    une explosion de noeuds si mal utilisée.

    Règles (ADR):
    - Désactivé par défaut (ENABLE_WINDOW_CONTEXT=false)
    - Max 50 windows par document
    - Traversal depth <= 1 hop
    - Jamais utilisé pour ranking global
    """
    kind: ContextNodeKind = ContextNodeKind.WINDOW

    # Métadonnées window
    chunk_id: str                       # ID du chunk centré
    window_index: int = 0               # Index dans le document

    @classmethod
    def create(cls, chunk_id: str, document_id: str,
               tenant_id: str = "default",
               window_index: int = 0) -> "WindowContext":
        """Factory pour créer un WindowContext."""
        return cls(
            context_id=f"win:{chunk_id}",
            doc_id=document_id,
            tenant_id=tenant_id,
            chunk_id=chunk_id,
            window_index=window_index,
        )

    def to_neo4j_props(self) -> Dict[str, Any]:
        props = super().to_neo4j_props()
        props["chunk_id"] = self.chunk_id
        props["window_index"] = self.window_index
        return props


@dataclass
class MentionedIn:
    """
    Relation MENTIONED_IN entre un CanonicalConcept et un ContextNode.

    Relation Neo4j: (CanonicalConcept)-[:MENTIONED_IN]->(ContextNode)

    IMPORTANT: Cette relation est pour la NAVIGATION uniquement.
    Elle ne doit JAMAIS être utilisée pour le raisonnement sémantique.
    """
    concept_id: str                     # canonical_id du concept
    context_id: str                     # context_id du ContextNode

    # Propriétés relation
    count: int = 1                      # Nombre de mentions
    weight: float = 0.0                 # Poids normalisé (fréquence)
    first_seen: datetime = field(default_factory=datetime.utcnow)

    # Metadata
    tenant_id: str = "default"

    def to_neo4j_props(self) -> Dict[str, Any]:
        """Convertit en propriétés Neo4j pour la relation."""
        return {
            "count": self.count,
            "weight": self.weight,
            "first_seen": self.first_seen.isoformat(),
        }


@dataclass
class NavigationLayerConfig:
    """
    Configuration pour la Navigation Layer.

    ADR: doc/ongoing/ADR_NAVIGATION_LAYER.md
    """
    # Feature flags
    enable_document_context: bool = True
    enable_section_context: bool = True
    enable_window_context: bool = False  # DÉSACTIVÉ par défaut (ADR)

    # Budgets
    max_windows_per_document: int = 50   # Cap pour WindowContext
    max_mentions_per_concept: int = 100  # Top-N mentions par concept

    # Seuils
    min_mention_count: int = 1           # Min mentions pour créer lien

    # Tenant
    tenant_id: str = "default"

    @classmethod
    def from_feature_flags(cls, tenant_id: str = "default") -> "NavigationLayerConfig":
        """Charge configuration depuis feature_flags.yaml."""
        from knowbase.config.feature_flags import get_feature_config

        nav_config = get_feature_config("navigation_layer") or {}

        return cls(
            enable_document_context=nav_config.get("enable_document_context", True),
            enable_section_context=nav_config.get("enable_section_context", True),
            enable_window_context=nav_config.get("enable_window_context", False),
            max_windows_per_document=nav_config.get("max_windows_per_document", 50),
            max_mentions_per_concept=nav_config.get("max_mentions_per_concept", 100),
            min_mention_count=nav_config.get("min_mention_count", 1),
            tenant_id=tenant_id,
        )


# ============================================================================
# CONSTANTES - Relations Navigation (whitelist)
# ============================================================================

NAVIGATION_RELATION_TYPES = frozenset({
    "MENTIONED_IN",     # Concept → ContextNode
    "IN_DOCUMENT",      # ContextNode → Document
    "CENTERED_ON",      # WindowContext → DocumentChunk
    "IN_SECTION",       # WindowContext → SectionContext (optionnel)
})

# Relations sémantiques (pour référence - NE PAS utiliser dans navigation)
SEMANTIC_RELATION_TYPES = frozenset({
    "REQUIRES", "ENABLES", "PREVENTS", "CAUSES",
    "APPLIES_TO", "DEPENDS_ON", "PART_OF", "MITIGATES",
    "CONFLICTS_WITH", "DEFINES", "EXAMPLE_OF", "GOVERNED_BY",
})
