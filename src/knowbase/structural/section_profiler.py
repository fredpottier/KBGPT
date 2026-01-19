"""
OSMOSE Structural Graph - Section Profiler (Option C)

Assignment des DocItems aux sections et calcul du profil structurel.

Ce module implémente:
- D4: Assignment DocItem → SectionContext
- D10: Calcul du structural_profile

Spec: doc/ongoing/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from knowbase.structural.models import (
    DocItem,
    DocItemType,
    SectionInfo,
    StructuralProfile,
    RELATION_BEARING_TYPES,
)

logger = logging.getLogger(__name__)


# ===================================
# SECTION ID GENERATION
# ===================================

def generate_section_id(item: DocItem) -> str:
    """
    Génère un ID de section depuis un heading.

    Args:
        item: DocItem de type HEADING

    Returns:
        ID de section unique
    """
    # Normaliser le texte pour créer un slug
    text = item.text[:50] if item.text else "untitled"
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', text.lower()).strip('_')[:30]
    short_id = uuid4().hex[:6]
    return f"sec_{slug}_{short_id}"


def build_section_path(section_stack: List[Tuple[int, str, str]], current_title: str) -> str:
    """
    Construit le chemin de section hiérarchique.

    Spec: ADR D4.4

    Args:
        section_stack: Stack de (level, section_id, title)
        current_title: Titre de la section courante

    Returns:
        Chemin formaté (ex: "1. Introduction / 1.1 Overview")
    """
    titles = [t[2] for t in section_stack] + [current_title]
    # Limiter chaque titre à 50 chars
    titles = [t[:50] if t else "Untitled" for t in titles]
    return " / ".join(titles)


# ===================================
# SECTION ASSIGNMENT (D4)
# ===================================

class SectionProfiler:
    """
    Profiler de sections pour Option C.

    Responsabilités:
    1. Assigner chaque DocItem à une section (D4)
    2. Calculer le structural_profile de chaque section (D10)

    Usage:
        profiler = SectionProfiler(
            tenant_id="default",
            doc_id="mydoc",
            doc_version_id="v1:abc123..."
        )
        sections = profiler.assign_sections(doc_items)
    """

    def __init__(
        self,
        tenant_id: str,
        doc_id: str,
        doc_version_id: str,
    ):
        """
        Initialise le profiler.

        Args:
            tenant_id: ID du tenant
            doc_id: ID du document
            doc_version_id: Hash de la version
        """
        self.tenant_id = tenant_id
        self.doc_id = doc_id
        self.doc_version_id = doc_version_id

    def assign_sections(self, items: List[DocItem]) -> List[SectionInfo]:
        """
        Assigne chaque item à une section et calcule les profils.

        Spec: ADR D4.1-D4.5

        Règles:
        - Les sections sont créées à partir des HEADING (D4.1)
        - Un HEADING de niveau N ouvre une section qui se termine au prochain HEADING de niveau ≤ N (D4.2)
        - Tous les DocItems entre deux HEADING sont assignés à la section ouverte (D4.3)
        - Fallback: section root + sous-sections par page si aucun HEADING (D4.5)

        Args:
            items: Liste de DocItems triés par reading_order_index

        Returns:
            Liste de SectionInfo avec items assignés et profils calculés
        """
        if not items:
            return []

        # Trier par reading_order
        sorted_items = sorted(items, key=lambda x: x.reading_order_index)

        # Détecter si le document a des headings
        has_headings = any(i.item_type == DocItemType.HEADING for i in sorted_items)

        if has_headings:
            sections = self._assign_by_headings(sorted_items)
        else:
            sections = self._assign_by_pages(sorted_items)

        # Calculer les profils structurels
        for section in sections:
            section_items = [i for i in sorted_items if i.section_id == section.section_id]
            section.structural_profile = StructuralProfile.from_items(section_items)
            section.item_ids = [i.item_id for i in section_items]

        logger.info(
            f"[SectionProfiler] Assigned {len(sorted_items)} items to "
            f"{len(sections)} sections for doc={self.doc_id}"
        )

        return sections

    def _assign_by_headings(self, items: List[DocItem]) -> List[SectionInfo]:
        """
        Assigne les items aux sections basées sur les headings.

        Spec: ADR D4.1-D4.3
        """
        sections: Dict[str, SectionInfo] = {}
        section_stack: List[Tuple[int, str, str]] = []  # (level, section_id, title)

        # Section root pour les items avant le premier heading
        root_id = f"sec_root_{uuid4().hex[:6]}"
        root_section = SectionInfo(
            section_id=root_id,
            doc_id=self.doc_id,
            doc_version_id=self.doc_version_id,
            tenant_id=self.tenant_id,
            section_path="root",
            section_level=0,
            title="Document Root",
        )
        sections[root_id] = root_section
        current_section_id = root_id

        for item in items:
            if item.item_type == DocItemType.HEADING:
                # Niveau du heading (1 par défaut)
                level = item.heading_level or 1

                # Fermer les sections de niveau >= level (D4.2)
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()

                # Créer nouvelle section
                section_id = generate_section_id(item)
                title = item.text[:100] if item.text else "Untitled"
                section_path = build_section_path(section_stack, title)

                parent_section_id = section_stack[-1][1] if section_stack else root_id

                new_section = SectionInfo(
                    section_id=section_id,
                    doc_id=self.doc_id,
                    doc_version_id=self.doc_version_id,
                    tenant_id=self.tenant_id,
                    section_path=section_path,
                    section_level=level,
                    title=title,
                    parent_section_id=parent_section_id,
                )
                sections[section_id] = new_section

                # Ajouter au stack
                section_stack.append((level, section_id, title))
                current_section_id = section_id

            # Assigner l'item à la section courante
            item.section_id = current_section_id

        # Supprimer root si vide
        root_items = [i for i in items if i.section_id == root_id]
        if not root_items:
            del sections[root_id]

        return list(sections.values())

    def _assign_by_pages(self, items: List[DocItem]) -> List[SectionInfo]:
        """
        Assigne les items aux sections par page (fallback).

        Spec: ADR D4.5
        """
        sections: Dict[str, SectionInfo] = {}

        # Section root
        root_id = f"sec_root_{uuid4().hex[:6]}"
        root_section = SectionInfo(
            section_id=root_id,
            doc_id=self.doc_id,
            doc_version_id=self.doc_version_id,
            tenant_id=self.tenant_id,
            section_path="root",
            section_level=0,
            title="Document Root",
        )
        sections[root_id] = root_section

        # Créer une section par page
        pages = sorted(set(i.page_no for i in items))
        page_sections: Dict[int, str] = {}

        for page_no in pages:
            section_id = f"sec_page_{page_no:03d}_{uuid4().hex[:6]}"
            section = SectionInfo(
                section_id=section_id,
                doc_id=self.doc_id,
                doc_version_id=self.doc_version_id,
                tenant_id=self.tenant_id,
                section_path=f"root / Page {page_no}",
                section_level=1,
                title=f"Page {page_no}",
                parent_section_id=root_id,
            )
            sections[section_id] = section
            page_sections[page_no] = section_id

        # Assigner les items
        for item in items:
            item.section_id = page_sections.get(item.page_no, root_id)

        return list(sections.values())


# ===================================
# RELATION-BEARING CHECK (D3.3)
# ===================================

def is_item_relation_bearing(item: DocItem, section_profile: StructuralProfile) -> bool:
    """
    Détermine si un item est relation-bearing.

    Spec: ADR D3.3

    Args:
        item: DocItem à vérifier
        section_profile: Profil de la section contenant l'item

    Returns:
        True si l'item peut porter des relations
    """
    # Types toujours relation-bearing (D3.1)
    if item.item_type in RELATION_BEARING_TYPES:
        return True

    # LIST_ITEM dépend du contexte (D3.3)
    if item.item_type == DocItemType.LIST_ITEM:
        return (
            section_profile.is_relation_bearing and
            section_profile.list_ratio < 0.5
        )

    return False


def filter_relation_bearing_items(
    items: List[DocItem],
    sections: List[SectionInfo],
) -> List[DocItem]:
    """
    Filtre les items relation-bearing.

    Args:
        items: Liste de DocItems
        sections: Liste de SectionInfo avec profils

    Returns:
        Liste des items relation-bearing uniquement
    """
    # Créer un mapping section_id → profile
    section_profiles = {
        s.section_id: s.structural_profile or StructuralProfile.empty()
        for s in sections
    }

    result = []
    for item in items:
        profile = section_profiles.get(item.section_id, StructuralProfile.empty())
        if is_item_relation_bearing(item, profile):
            result.append(item)

    return result


# ===================================
# SECTION ANALYSIS UTILITIES
# ===================================

def analyze_document_structure(
    items: List[DocItem],
    sections: List[SectionInfo],
) -> Dict[str, Any]:
    """
    Analyse la structure globale du document.

    Args:
        items: Liste de DocItems
        sections: Liste de SectionInfo

    Returns:
        Dictionnaire d'analyse
    """
    from collections import Counter

    type_counts = Counter(i.item_type.value for i in items)
    relation_bearing = filter_relation_bearing_items(items, sections)

    # Stats par section
    section_stats = []
    for section in sections:
        section_items = [i for i in items if i.section_id == section.section_id]
        profile = section.structural_profile or StructuralProfile.empty()
        section_stats.append({
            "section_id": section.section_id,
            "title": section.title,
            "level": section.section_level,
            "item_count": len(section_items),
            "is_relation_bearing": profile.is_relation_bearing,
            "is_structure_bearing": profile.is_structure_bearing,
            "dominant_types": profile.dominant_types,
        })

    return {
        "total_items": len(items),
        "total_sections": len(sections),
        "type_distribution": dict(type_counts),
        "relation_bearing_items": len(relation_bearing),
        "relation_bearing_ratio": len(relation_bearing) / len(items) if items else 0,
        "sections": section_stats,
    }
