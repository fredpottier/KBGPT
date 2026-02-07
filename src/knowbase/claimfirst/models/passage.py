# src/knowbase/claimfirst/models/passage.py
"""
Modèle Passage - Contexte englobant pour les Claims.

INV-1: Sémantique Unit vs Passage vs Claim
- Unit (U1, U2...) = preuve textuelle exacte (verbatim garanti par pointer mode)
- Passage (DocItem) = contexte englobant (peut contenir plusieurs units)
- Claim = affirmation synthétique pointant vers un ou plusieurs unit_ids

Règle: La preuve d'une Claim est `unit_ids`, pas `passage_id`.
       Le passage est le contexte de navigation, pas la preuve.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Passage(BaseModel):
    """
    Passage - Contexte documentaire englobant pour les Claims.

    Un Passage représente une unité de contexte dans le document
    (paragraphe, section, etc.) qui peut contenir plusieurs
    AssertionUnits (U1, U2...).

    Le Passage sert de contexte de navigation, pas de preuve.
    La preuve est dans les unit_ids des Claims.

    Attributes:
        passage_id: Identifiant unique du passage
        tenant_id: Tenant multi-locataire
        doc_id: Document source
        text: Texte complet du passage
        page_no: Numéro de page (optionnel)
        char_start: Position de début dans le document
        char_end: Position de fin dans le document
        unit_ids: IDs des AssertionUnits contenus
        section_id: Section parente (optionnel)
        section_title: Titre de la section (optionnel)
    """

    passage_id: str = Field(
        ...,
        description="Identifiant unique du passage"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    doc_id: str = Field(
        ...,
        description="Document source"
    )

    text: str = Field(
        ...,
        description="Texte complet du passage"
    )

    page_no: Optional[int] = Field(
        default=None,
        ge=0,
        description="Numéro de page (optionnel)"
    )

    char_start: int = Field(
        default=0,
        ge=0,
        description="Position de début dans le document"
    )

    char_end: int = Field(
        default=0,
        ge=0,
        description="Position de fin dans le document"
    )

    unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs des AssertionUnits contenus (U1, U2...)"
    )

    section_id: Optional[str] = Field(
        default=None,
        description="Section parente (optionnel)"
    )

    section_title: Optional[str] = Field(
        default=None,
        description="Titre de la section (optionnel)"
    )

    # Métadonnées
    item_type: str = Field(
        default="paragraph",
        description="Type de l'élément source (paragraph, list_item, etc.)"
    )

    reading_order_index: int = Field(
        default=0,
        description="Index dans l'ordre de lecture"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de création"
    )

    @property
    def char_length(self) -> int:
        """Longueur du passage en caractères."""
        return self.char_end - self.char_start

    @property
    def unit_count(self) -> int:
        """Nombre d'AssertionUnits dans ce passage."""
        return len(self.unit_ids)

    def contains_unit_span(self, unit_start: int, unit_end: int) -> bool:
        """
        Vérifie si un span d'unité est contenu dans ce passage.

        Utilisé par PassageLinker pour vérifier INV-1:
        "unit spans ⊆ passage span"

        Args:
            unit_start: Position de début de l'unité
            unit_end: Position de fin de l'unité

        Returns:
            True si l'unité est contenue dans le passage
        """
        return unit_start >= self.char_start and unit_end <= self.char_end

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        return {
            "passage_id": self.passage_id,
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "page_no": self.page_no,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "unit_ids": self.unit_ids if self.unit_ids else None,
            "section_id": self.section_id,
            "section_title": self.section_title,
            "item_type": self.item_type,
            "reading_order_index": self.reading_order_index,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "Passage":
        """Construit un Passage depuis un record Neo4j."""
        return cls(
            passage_id=record["passage_id"],
            tenant_id=record["tenant_id"],
            doc_id=record["doc_id"],
            text=record["text"],
            page_no=record.get("page_no"),
            char_start=record.get("char_start", 0),
            char_end=record.get("char_end", 0),
            unit_ids=record.get("unit_ids") or [],
            section_id=record.get("section_id"),
            section_title=record.get("section_title"),
            item_type=record.get("item_type", "paragraph"),
            reading_order_index=record.get("reading_order_index", 0),
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at")
            else datetime.utcnow(),
        )

    @classmethod
    def from_docitem(
        cls,
        docitem,
        tenant_id: str,
        unit_ids: List[str] = None,
    ) -> "Passage":
        """
        Factory pour créer un Passage depuis un DocItem.

        Args:
            docitem: DocItem source (de knowbase.structural.models)
            tenant_id: Tenant ID
            unit_ids: IDs des AssertionUnits contenus

        Returns:
            Passage configuré
        """
        # Construire passage_id depuis le docitem
        item_id = getattr(docitem, "item_id", "")
        doc_id = getattr(docitem, "doc_id", "")
        passage_id = f"{tenant_id}:{doc_id}:{item_id}"

        # Extraire le texte
        text = getattr(docitem, "text", "") or getattr(docitem, "content", "") or ""

        # Gérer les charspan None
        char_start = getattr(docitem, "charspan_start", None)
        char_end = getattr(docitem, "charspan_end", None)
        if char_start is None:
            char_start = 0
        if char_end is None:
            char_end = len(text)

        return cls(
            passage_id=passage_id,
            tenant_id=tenant_id,
            doc_id=doc_id,
            text=text,
            page_no=getattr(docitem, "page_no", None),
            char_start=char_start,
            char_end=char_end,
            unit_ids=unit_ids or [],
            section_id=getattr(docitem, "section_id", None),
            section_title=None,  # À enrichir depuis SectionInfo si disponible
            item_type=str(getattr(docitem, "item_type", "paragraph")),
            reading_order_index=getattr(docitem, "reading_order_index", 0) or 0,
        )


__all__ = [
    "Passage",
]
