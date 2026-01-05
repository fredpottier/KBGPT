"""
Models for Document Structural Awareness Layer.

Dataclasses et enums pour la detection de structure documentaire.

Spec: doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import re


class StructuralConfidence(Enum):
    """
    Niveau de confiance structurelle du document.

    Determine la fiabilite des signaux structurels :
    - HIGH : Assez de pages et signaux pour decisions fortes
    - MEDIUM : Signaux partiels, decisions moderees
    - LOW : Peu de signal, eviter decisions fortes
    """
    HIGH = "high"      # >= 5 pages, signaux clairs
    MEDIUM = "medium"  # 3-4 pages, signaux partiels
    LOW = "low"        # 1-2 pages, peu de signal statistique

    @classmethod
    def from_page_count(cls, page_count: int) -> "StructuralConfidence":
        """Determine la confiance structurelle depuis le nombre de pages."""
        if page_count >= 5:
            return cls.HIGH
        elif page_count >= 3:
            return cls.MEDIUM
        else:
            return cls.LOW


class Zone(Enum):
    """Zone logique d'une page."""
    TOP = "top"
    MAIN = "main"
    BOTTOM = "bottom"


@dataclass
class ZoneConfig:
    """
    Configuration pour la segmentation en zones.

    Parametres agnostiques pour determiner les zones TOP/MAIN/BOTTOM.
    """
    top_lines_count: int = 3          # Lignes considerees comme TOP
    bottom_lines_count: int = 3       # Lignes considerees comme BOTTOM
    min_line_length: int = 5          # Ignorer lignes < N chars
    ignore_pure_numbers: bool = True  # Ignorer numeros de page
    normalize_whitespace: bool = True # Normaliser espaces multiples

    def to_dict(self) -> Dict[str, Any]:
        return {
            "top_lines_count": self.top_lines_count,
            "bottom_lines_count": self.bottom_lines_count,
            "min_line_length": self.min_line_length,
            "ignore_pure_numbers": self.ignore_pure_numbers,
            "normalize_whitespace": self.normalize_whitespace,
        }


@dataclass
class ZonedLine:
    """
    Une ligne avec sa zone assignee.

    Represente une ligne de texte avec metadata de position.
    """
    text: str
    zone: Zone
    line_index: int  # Index dans la page originale
    normalized_text: str = ""  # Version normalisee pour matching

    def __post_init__(self):
        if not self.normalized_text:
            self.normalized_text = normalize_for_template_matching(self.text)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "zone": self.zone.value,
            "line_index": self.line_index,
            "normalized_text": self.normalized_text,
        }


@dataclass
class PageZones:
    """
    Resultat de la segmentation d'une page en zones.

    Contient les lignes classees par zone logique.
    """
    page_index: int
    top_lines: List[ZonedLine] = field(default_factory=list)
    main_lines: List[ZonedLine] = field(default_factory=list)
    bottom_lines: List[ZonedLine] = field(default_factory=list)
    total_lines: int = 0

    def get_lines_by_zone(self, zone: Zone) -> List[ZonedLine]:
        """Retourne les lignes d'une zone specifique."""
        if zone == Zone.TOP:
            return self.top_lines
        elif zone == Zone.MAIN:
            return self.main_lines
        else:
            return self.bottom_lines

    def get_all_lines(self) -> List[ZonedLine]:
        """Retourne toutes les lignes dans l'ordre."""
        return self.top_lines + self.main_lines + self.bottom_lines

    def get_zone_for_line(self, line_text: str) -> Optional[Zone]:
        """Trouve la zone d'une ligne par son texte."""
        for line in self.get_all_lines():
            if line.text == line_text:
                return line.zone
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_index": self.page_index,
            "top_lines": [l.to_dict() for l in self.top_lines],
            "main_lines": [l.to_dict() for l in self.main_lines],
            "bottom_lines": [l.to_dict() for l in self.bottom_lines],
            "total_lines": self.total_lines,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PageZones":
        return cls(
            page_index=data["page_index"],
            top_lines=[
                ZonedLine(
                    text=l["text"],
                    zone=Zone(l["zone"]),
                    line_index=l["line_index"],
                    normalized_text=l.get("normalized_text", ""),
                )
                for l in data.get("top_lines", [])
            ],
            main_lines=[
                ZonedLine(
                    text=l["text"],
                    zone=Zone(l["zone"]),
                    line_index=l["line_index"],
                    normalized_text=l.get("normalized_text", ""),
                )
                for l in data.get("main_lines", [])
            ],
            bottom_lines=[
                ZonedLine(
                    text=l["text"],
                    zone=Zone(l["zone"]),
                    line_index=l["line_index"],
                    normalized_text=l.get("normalized_text", ""),
                )
                for l in data.get("bottom_lines", [])
            ],
            total_lines=data.get("total_lines", 0),
        )


@dataclass
class TemplateFragment:
    """
    Un fragment identifie comme template/boilerplate.

    Represente un texte repete sur plusieurs pages.
    """
    normalized_text: str
    original_samples: List[str] = field(default_factory=list)
    pages_covered: List[int] = field(default_factory=list)
    pages_covered_ratio: float = 0.0
    dominant_zone: Zone = Zone.BOTTOM
    zone_distribution: Dict[str, int] = field(default_factory=dict)
    zone_consistency: float = 0.0
    template_likelihood: float = 0.0

    def contains_value(self, value: str) -> bool:
        """Verifie si ce template contient une valeur donnee."""
        value_lower = value.lower()
        return value_lower in self.normalized_text.lower()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "normalized_text": self.normalized_text,
            "original_samples": self.original_samples[:3],  # Max 3
            "pages_covered": self.pages_covered,
            "pages_covered_ratio": self.pages_covered_ratio,
            "dominant_zone": self.dominant_zone.value,
            "zone_distribution": self.zone_distribution,
            "zone_consistency": self.zone_consistency,
            "template_likelihood": self.template_likelihood,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateFragment":
        return cls(
            normalized_text=data["normalized_text"],
            original_samples=data.get("original_samples", []),
            pages_covered=data.get("pages_covered", []),
            pages_covered_ratio=data.get("pages_covered_ratio", 0.0),
            dominant_zone=Zone(data.get("dominant_zone", "bottom")),
            zone_distribution=data.get("zone_distribution", {}),
            zone_consistency=data.get("zone_consistency", 0.0),
            template_likelihood=data.get("template_likelihood", 0.0),
        )


@dataclass
class TemplateCluster:
    """
    Cluster de lignes similaires pour detection de template.

    Usage interne pour le clustering.
    """
    normalized_key: str
    occurrences: List[Dict[str, Any]] = field(default_factory=list)
    # Chaque occurrence: {page_index, zone, original_text, line_index}

    def add_occurrence(
        self,
        page_index: int,
        zone: Zone,
        original_text: str,
        line_index: int,
    ):
        self.occurrences.append({
            "page_index": page_index,
            "zone": zone.value,
            "original_text": original_text,
            "line_index": line_index,
        })

    @property
    def pages_covered(self) -> Set[int]:
        return {occ["page_index"] for occ in self.occurrences}

    @property
    def zone_distribution(self) -> Dict[str, int]:
        dist = {"top": 0, "main": 0, "bottom": 0}
        for occ in self.occurrences:
            dist[occ["zone"]] += 1
        return dist

    @property
    def dominant_zone(self) -> Zone:
        dist = self.zone_distribution
        max_zone = max(dist, key=dist.get)
        return Zone(max_zone)

    @property
    def zone_consistency(self) -> float:
        """Ratio d'occurrences dans la zone dominante."""
        if not self.occurrences:
            return 0.0
        dist = self.zone_distribution
        max_count = max(dist.values())
        return max_count / len(self.occurrences)

    def to_template_fragment(self, total_pages: int) -> TemplateFragment:
        """Convertit le cluster en TemplateFragment."""
        pages = sorted(self.pages_covered)
        pages_ratio = len(pages) / total_pages if total_pages > 0 else 0.0

        # Template likelihood basee sur:
        # - pages_covered_ratio (poids: 0.4)
        # - zone_consistency (poids: 0.3)
        # - NOT main zone (poids: 0.3)
        zone_factor = 0.0 if self.dominant_zone == Zone.MAIN else 1.0

        template_likelihood = (
            0.4 * pages_ratio +
            0.3 * self.zone_consistency +
            0.3 * zone_factor
        )

        return TemplateFragment(
            normalized_text=self.normalized_key,
            original_samples=[occ["original_text"] for occ in self.occurrences[:5]],
            pages_covered=pages,
            pages_covered_ratio=pages_ratio,
            dominant_zone=self.dominant_zone,
            zone_distribution=self.zone_distribution,
            zone_consistency=self.zone_consistency,
            template_likelihood=min(1.0, template_likelihood),
        )


@dataclass
class StructuralAnalysis:
    """
    Resultat complet de l'analyse structurelle d'un document.

    Aggrege zones et templates pour usage par le DocContextExtractor.
    """
    pages_zones: List[PageZones] = field(default_factory=list)
    template_fragments: List[TemplateFragment] = field(default_factory=list)
    structural_confidence: StructuralConfidence = StructuralConfidence.LOW
    total_pages: int = 0

    # Statistiques agregees
    zone_statistics: Dict[str, int] = field(default_factory=dict)
    template_coverage: float = 0.0  # % de lignes en template

    def get_template_for_value(self, value: str) -> Optional[TemplateFragment]:
        """Trouve le template contenant une valeur."""
        for template in self.template_fragments:
            if template.contains_value(value):
                return template
        return None

    def is_value_in_template(self, value: str) -> bool:
        """Verifie si une valeur apparait dans un template."""
        return self.get_template_for_value(value) is not None

    def get_zone_distribution_for_value(
        self,
        value: str,
    ) -> Dict[str, int]:
        """Calcule la distribution par zone d'une valeur."""
        dist = {"top": 0, "main": 0, "bottom": 0}
        value_lower = value.lower()

        for page_zones in self.pages_zones:
            for line in page_zones.get_all_lines():
                if value_lower in line.text.lower():
                    dist[line.zone.value] += 1

        return dist

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pages_zones": [pz.to_dict() for pz in self.pages_zones],
            "template_fragments": [tf.to_dict() for tf in self.template_fragments],
            "structural_confidence": self.structural_confidence.value,
            "total_pages": self.total_pages,
            "zone_statistics": self.zone_statistics,
            "template_coverage": self.template_coverage,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StructuralAnalysis":
        return cls(
            pages_zones=[PageZones.from_dict(pz) for pz in data.get("pages_zones", [])],
            template_fragments=[
                TemplateFragment.from_dict(tf)
                for tf in data.get("template_fragments", [])
            ],
            structural_confidence=StructuralConfidence(
                data.get("structural_confidence", "low")
            ),
            total_pages=data.get("total_pages", 0),
            zone_statistics=data.get("zone_statistics", {}),
            template_coverage=data.get("template_coverage", 0.0),
        )


# === Fonctions utilitaires ===

def normalize_for_template_matching(text: str) -> str:
    """
    Normalisation agnostique pour detection de repetition.

    - lowercase
    - chiffres → '#'
    - espaces multiples → single space
    - ponctuation preservee (importante pour legal)
    """
    if not text:
        return ""

    text = text.lower()
    text = re.sub(r'\d+', '#', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()

    return text


def is_significant_line(line: str, config: ZoneConfig) -> bool:
    """
    Verifie si une ligne est significative (pas juste un numero de page, etc.).
    """
    if not line or len(line.strip()) < config.min_line_length:
        return False

    stripped = line.strip()

    # Ignorer numeros de page purs
    if config.ignore_pure_numbers and stripped.isdigit():
        return False

    # Ignorer lignes avec seulement ponctuation/symboles
    if not any(c.isalnum() for c in stripped):
        return False

    return True
