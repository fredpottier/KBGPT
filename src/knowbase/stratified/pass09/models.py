"""
OSMOSE Pipeline V2 - Pass 0.9 Models
====================================
Modèles de données pour Global View Construction.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple


@dataclass
class Pass09Config:
    """Configuration pour Pass 0.9 Global View Construction."""

    # Taille des résumés de section
    section_summary_max_chars: int = 800
    section_summary_min_chars: int = 100

    # Seuils pour skip de sections
    section_min_chars_to_summarize: int = 200  # Sections < 200 chars = skip ou verbatim
    section_max_chars_for_verbatim: int = 500  # Sections < 500 chars = copie verbatim

    # Taille meta-document
    meta_document_min_chars: int = 5000
    meta_document_max_chars: int = 30000
    meta_document_target_chars: int = 20000

    # Couverture minimum requise
    min_coverage_ratio: float = 0.95

    # Parallélisation
    max_concurrent_summaries: int = 20

    # Fallback
    enable_fallback: bool = True
    fallback_chars_per_section: int = 1000


@dataclass
class SectionSummary:
    """Résumé d'une section du document."""

    section_id: str
    section_title: str
    level: int  # 1=H1, 2=H2, etc.

    # Résumé généré
    summary: str  # 500-1000 chars max

    # Éléments extraits
    concepts_mentioned: List[str] = field(default_factory=list)
    assertion_types: List[str] = field(default_factory=list)
    key_values: List[str] = field(default_factory=list)

    # Statistiques
    char_count_original: int = 0
    char_count_summary: int = 0

    # Méthode utilisée
    method: str = "llm"  # "llm", "verbatim", "truncated", "skipped"

    @property
    def compression_ratio(self) -> float:
        """Ratio de compression (0-1)."""
        if self.char_count_original == 0:
            return 0.0
        return self.char_count_summary / self.char_count_original


@dataclass
class GlobalViewCoverage:
    """Statistiques de couverture du document."""

    sections_total: int = 0
    sections_summarized: int = 0
    sections_verbatim: int = 0
    sections_skipped: int = 0

    chars_original: int = 0
    chars_meta_document: int = 0

    @property
    def coverage_ratio(self) -> float:
        """Ratio de couverture (sections traitées / total)."""
        if self.sections_total == 0:
            return 0.0
        return (self.sections_summarized + self.sections_verbatim) / self.sections_total

    @property
    def compression_ratio(self) -> float:
        """Ratio de compression (meta / original)."""
        if self.chars_original == 0:
            return 0.0
        return self.chars_meta_document / self.chars_original


@dataclass
class GlobalView:
    """Vue globale construite du document."""

    tenant_id: str
    doc_id: str

    # Meta-document pour LLM (15-25K chars, structuré)
    meta_document: str

    # Détails par section
    section_summaries: Dict[str, SectionSummary] = field(default_factory=dict)

    # Table des matières enrichie
    toc_enhanced: str = ""

    # Statistiques de couverture
    coverage: GlobalViewCoverage = field(default_factory=GlobalViewCoverage)

    # Métadonnées de construction
    created_at: datetime = field(default_factory=datetime.utcnow)
    llm_model_used: str = ""
    total_llm_calls: int = 0
    total_tokens_used: int = 0
    build_time_seconds: float = 0.0

    # Statut
    is_fallback: bool = False  # True si construit sans LLM
    errors: List[str] = field(default_factory=list)

    # V2.2: Zones détectées pour clustering zone-first
    zones: List["Zone"] = field(default_factory=list)

    def is_valid(self, config: Pass09Config) -> bool:
        """Vérifie si la GlobalView est valide selon la config."""
        # Couverture suffisante
        if self.coverage.coverage_ratio < config.min_coverage_ratio:
            return False

        # Taille meta-document dans les limites
        meta_len = len(self.meta_document)
        if meta_len < config.meta_document_min_chars:
            return False
        if meta_len > config.meta_document_max_chars:
            return False

        return True


@dataclass
class Zone:
    """
    Zone documentaire pour clustering zone-first (V2.2).

    Une zone correspond à une section H1 ou à un découpage automatique
    si le document n'a pas de structure H1 exploitable.
    Les zones sont purement informationnelles — elles ne produisent PAS
    de Themes/Concepts, uniquement des labels et keywords.
    """

    zone_id: str                         # "z1", "z2", ...
    label: str                           # Heading H1 (informatif, pas prescriptif)
    section_ids: List[str]               # Sections couvertes
    keywords: List[str] = field(default_factory=list)  # Agrégés depuis concepts_mentioned
    page_range: Tuple[int, int] = (0, 0)  # (page_min, page_max)
