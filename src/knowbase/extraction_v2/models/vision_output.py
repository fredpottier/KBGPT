"""
Modèles de sortie Vision pour Extraction V2.

VisionElement: Élément extrait par Vision LLM.
VisionRelation: Relation extraite par Vision LLM.
VisionAmbiguity: Ambiguïté déclarée par Vision LLM.
VisionUncertainty: Incertitude déclarée par Vision LLM.
VisionExtraction: Résultat complet de l'extraction Vision.

Spécification: VISION_GATING_V4_CLASS_SCHEMA.py, VISION_PROMPT_CANONICAL.md
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


class ElementType(str, Enum):
    """Types d'éléments visuels détectables."""
    BOX = "box"
    LABEL = "label"
    ARROW = "arrow"
    GROUP = "group"
    ICON = "icon"
    LINE = "line"
    CONNECTOR = "connector"
    OTHER = "other"


class RelationType(str, Enum):
    """Types de relations visuelles."""
    CONTAINS = "contains"
    FLOWS_TO = "flows_to"
    INTEGRATES_WITH = "integrates_with"
    DEPENDS_ON = "depends_on"
    GROUPED_WITH = "grouped_with"
    CONNECTED = "connected"
    LABELED_BY = "labeled_by"
    OTHER = "other"


class EvidenceType(str, Enum):
    """Types de preuves visuelles pour les relations."""
    ARROW = "arrow"
    LINE = "line"
    GROUPING = "grouping"
    ALIGNMENT = "alignment"
    PROXIMITY = "proximity"
    LABEL_NEAR_LINE = "label_near_line"
    ENCLOSURE = "enclosure"
    COLOR_CODING = "color_coding"


@dataclass
class VisionElement:
    """
    Élément extrait par Vision LLM.

    Attributs:
        id: Identifiant unique (ex: "box_1", "arrow_2")
        type: Type d'élément (box, label, arrow, group, icon, other)
        text: Texte contenu dans l'élément (si applicable)
        bbox: Bounding box normalisée (x, y, width, height) - optionnel
        confidence: Score de confiance (0.0 - 1.0)
        metadata: Métadonnées additionnelles
    """
    id: str
    type: str  # ElementType value
    text: str = ""
    bbox: Optional[Tuple[float, float, float, float]] = None  # normalized (0..1)
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validation."""
        self.confidence = max(0.0, min(1.0, self.confidence))

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        result = {
            "id": self.id,
            "type": self.type,
            "text": self.text,
            "confidence": round(self.confidence, 2),
        }
        if self.bbox:
            result["bbox"] = list(self.bbox)
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisionElement":
        """Désérialise depuis un dictionnaire."""
        bbox = None
        if "bbox" in data and data["bbox"]:
            bbox = tuple(data["bbox"])
        return cls(
            id=data["id"],
            type=data["type"],
            text=data.get("text", ""),
            bbox=bbox,
            confidence=data.get("confidence", 1.0),
            metadata=data.get("metadata", {}),
        )

    def to_text_format(self) -> str:
        """
        Format texte pour inclusion dans vision_text.

        Ex: [E1|box] "SAP S/4HANA"
        """
        return f'[{self.id}|{self.type}] "{self.text}"'

    def __repr__(self) -> str:
        return f"VisionElement({self.id}: {self.type}, '{self.text[:30]}...')"


@dataclass
class VisionRelation:
    """
    Relation extraite par Vision LLM.

    Toute relation DOIT avoir une evidence visuelle explicite.

    Attributs:
        source_id: ID de l'élément source
        target_id: ID de l'élément cible
        type: Type de relation
        evidence: Type de preuve visuelle
        confidence: Score de confiance (0.0 - 1.0)
        direction: Direction si applicable ("forward", "backward", "bidirectional", "unclear")
        metadata: Métadonnées additionnelles
    """
    source_id: str
    target_id: str
    type: str  # RelationType value
    evidence: str  # EvidenceType value
    confidence: float = 1.0
    direction: str = "forward"  # "forward", "backward", "bidirectional", "unclear"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validation."""
        self.confidence = max(0.0, min(1.0, self.confidence))

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.type,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 2),
            "direction": self.direction,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisionRelation":
        """Désérialise depuis un dictionnaire."""
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            type=data.get("relation_type", data.get("type", "other")),
            evidence=data["evidence"],
            confidence=data.get("confidence", 1.0),
            direction=data.get("direction", "forward"),
            metadata=data.get("metadata", {}),
        )

    def to_text_format(self) -> str:
        """
        Format texte pour inclusion dans vision_text.

        Ex: [E1] -> [E2]
              relation: flows_to
              evidence: arrow
              direction: forward
        """
        lines = [
            f"- [{self.source_id}] -> [{self.target_id}]",
            f"  relation: {self.type}",
            f"  evidence: {self.evidence}",
        ]
        if self.direction != "forward":
            lines.append(f"  direction: {self.direction}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"VisionRelation({self.source_id} -> {self.target_id}: {self.type})"


@dataclass
class VisionAmbiguity:
    """
    Ambiguïté déclarée par Vision LLM.

    Une ambiguïté DOIT être déclarée plutôt que résolue implicitement.
    """
    term: str
    possible_interpretations: List[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "term": self.term,
            "possible_interpretations": self.possible_interpretations,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisionAmbiguity":
        """Désérialise depuis un dictionnaire."""
        return cls(
            term=data["term"],
            possible_interpretations=data["possible_interpretations"],
            reason=data["reason"],
        )

    def to_text_format(self) -> str:
        """Format texte pour inclusion dans vision_text."""
        interps = ", ".join(self.possible_interpretations)
        return f"- {self.term}: [{interps}] ({self.reason})"


@dataclass
class VisionUncertainty:
    """
    Incertitude déclarée par Vision LLM.

    Si Vision n'est pas sûr, déclarer l'incertitude explicitement.
    """
    item: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "item": self.item,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisionUncertainty":
        """Désérialise depuis un dictionnaire."""
        return cls(
            item=data["item"],
            reason=data["reason"],
        )

    def to_text_format(self) -> str:
        """Format texte pour inclusion dans vision_text."""
        return f"- {self.item}: {self.reason}"


@dataclass
class VisionExtraction:
    """
    Résultat complet de l'extraction Vision.

    Conforme au schema JSON défini dans VISION_PROMPT_CANONICAL.md.

    Attributs:
        kind: Type de diagramme détecté
        elements: Liste des éléments visuels
        relations: Liste des relations
        ambiguities: Liste des ambiguïtés déclarées
        uncertainties: Liste des incertitudes déclarées
        raw_model_output: Sortie brute du modèle (pour debug)
        page_index: Index de la page source
        confidence: Score de confiance global
    """
    kind: str  # "architecture_diagram", "process_workflow", "system_landscape", etc.
    elements: List[VisionElement] = field(default_factory=list)
    relations: List[VisionRelation] = field(default_factory=list)
    ambiguities: List[VisionAmbiguity] = field(default_factory=list)
    uncertainties: List[VisionUncertainty] = field(default_factory=list)
    raw_model_output: Optional[Dict[str, Any]] = None
    page_index: Optional[int] = None
    confidence: float = 1.0

    def __post_init__(self):
        """Validation."""
        self.confidence = max(0.0, min(1.0, self.confidence))

    @property
    def has_elements(self) -> bool:
        """Indique si des éléments ont été extraits."""
        return len(self.elements) > 0

    @property
    def has_relations(self) -> bool:
        """Indique si des relations ont été extraites."""
        return len(self.relations) > 0

    @property
    def has_ambiguities(self) -> bool:
        """Indique si des ambiguïtés ont été déclarées."""
        return len(self.ambiguities) > 0

    @property
    def has_uncertainties(self) -> bool:
        """Indique si des incertitudes ont été déclarées."""
        return len(self.uncertainties) > 0

    @property
    def element_count(self) -> int:
        """Nombre d'éléments."""
        return len(self.elements)

    @property
    def relation_count(self) -> int:
        """Nombre de relations."""
        return len(self.relations)

    def get_element_by_id(self, element_id: str) -> Optional[VisionElement]:
        """Récupère un élément par son ID."""
        for elem in self.elements:
            if elem.id == element_id:
                return elem
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire (format JSON schema)."""
        return {
            "diagram_type": self.kind,
            "elements": [e.to_dict() for e in self.elements],
            "relations": [r.to_dict() for r in self.relations],
            "ambiguities": [a.to_dict() for a in self.ambiguities],
            "uncertainties": [u.to_dict() for u in self.uncertainties],
            "page_index": self.page_index,
            "confidence": round(self.confidence, 2),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisionExtraction":
        """Désérialise depuis un dictionnaire."""
        return cls(
            kind=data.get("diagram_type", data.get("kind", "unknown")),
            elements=[VisionElement.from_dict(e) for e in data.get("elements", [])],
            relations=[VisionRelation.from_dict(r) for r in data.get("relations", [])],
            ambiguities=[
                VisionAmbiguity.from_dict(a) for a in data.get("ambiguities", [])
            ],
            uncertainties=[
                VisionUncertainty.from_dict(u) for u in data.get("uncertainties", [])
            ],
            raw_model_output=data.get("raw_model_output"),
            page_index=data.get("page_index"),
            confidence=data.get("confidence", 1.0),
        )

    @classmethod
    def from_llm_response(cls, response: Dict[str, Any], page_index: int = None) -> "VisionExtraction":
        """
        Parse la réponse JSON du LLM Vision.

        Args:
            response: Réponse JSON du modèle Vision
            page_index: Index de la page source

        Returns:
            VisionExtraction avec les données parsées
        """
        extraction = cls.from_dict(response)
        extraction.page_index = page_index
        extraction.raw_model_output = response
        return extraction

    def to_vision_text(self, page_index: int = None, confidence: float = None) -> str:
        """
        Génère le vision_text descriptif pour inclusion dans full_text OSMOSE.

        Format conforme à OSMOSIS_EXTRACTION_V2_DECISIONS.md - Décision 3.

        Args:
            page_index: Index de la page (override self.page_index)
            confidence: Confidence (override self.confidence)

        Returns:
            Texte balisé pour OSMOSE
        """
        idx = page_index if page_index is not None else self.page_index
        conf = confidence if confidence is not None else self.confidence

        lines = [
            f"[VISUAL_ENRICHMENT id=vision_{idx}_1 confidence={conf:.2f}]",
            f"diagram_type: {self.kind}",
            "",
        ]

        # Éléments visibles
        if self.elements:
            lines.append("visible_elements:")
            for elem in self.elements:
                lines.append(elem.to_text_format())
            lines.append("")

        # Relations visuelles
        if self.relations:
            lines.append("visible_relations (visual only):")
            for rel in self.relations:
                lines.append(rel.to_text_format())
            lines.append("")

        # Ambiguïtés
        if self.ambiguities:
            lines.append("ambiguities:")
            for amb in self.ambiguities:
                lines.append(amb.to_text_format())
            lines.append("")

        # Incertitudes
        if self.uncertainties:
            lines.append("uncertainties:")
            for unc in self.uncertainties:
                lines.append(unc.to_text_format())
            lines.append("")

        lines.append("[END_VISUAL_ENRICHMENT]")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"VisionExtraction({self.kind}: {len(self.elements)} elements, "
            f"{len(self.relations)} relations)"
        )


__all__ = [
    "ElementType",
    "RelationType",
    "EvidenceType",
    "VisionElement",
    "VisionRelation",
    "VisionAmbiguity",
    "VisionUncertainty",
    "VisionExtraction",
]
