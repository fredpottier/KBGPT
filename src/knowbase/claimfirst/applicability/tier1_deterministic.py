"""
Tier 1 déterministe — extraction sans LLM depuis filename + cache markers.

Cette couche sert de **prior fiable** pour le FrameBuilder V2 (Tier 2 LLM).
Elle exploite :
- Le filename pour extraire year + version (déterministe)
- La table de mapping CS-25 amendments → year (référence externe EASA)
- Les markers du cache `.v5cache.json` extraits par Docling :
  * `extraction.doc_context.strong_markers` (signal fort)
  * `extraction.doc_context.weak_markers` (signal faible)
  * `extraction.doc_context.document_context.entity_hints` (entités explicites)

ANTI-PATTERN évité : pas d'extraction lexicale dans le full_text (multilingue +
domain-agnostic). Le Layer 1 utilise UNIQUEMENT les sources structurées
ci-dessus (filename + outputs Docling pré-calculés).

Pour les patterns filename non-aerospace (medical, legal, IT), ce module
peut être étendu progressivement, ou contourné — Tier 2 LLM compensera.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Mapping CS-25 amendments → year (EASA ED Decision register)
# ============================================================================
# Source : https://www.easa.europa.eu/en/document-library/certification-specifications
# À étendre quand de nouveaux amdt sont publiés ou pour d'autres familles
# (ex: CS-23, CS-27, etc.). Ce mapping est volontairement explicite pour
# éviter l'inférence implicite.

CS25_AMDT_TO_YEAR: dict[int, int] = {
    22: 2018,  # ED Decision 2018/005/R
    23: 2019,
    24: 2020,
    25: 2020,  # ED Decision 2020/024/R
    26: 2021,
    27: 2022,
    28: 2023,  # ED Decision 2023/021/R
}


@dataclass
class Tier1Hints:
    """
    Output Tier 1 déterministe — hints à passer au Tier 2 LLM.

    Les valeurs ici ont une confiance élevée (déterministe + cross-validation
    multi-sources) mais doivent quand même être confirmées par evidence_quote
    dans le full_text par le Tier 2 LLM si on veut respecter le pattern
    evidence-locked V3.3.
    """

    publication_year: Optional[int] = None
    """Année de publication inférée (filename + cache markers consensus)."""

    edition_number: Optional[int] = None
    """Numéro d'amendment/édition extrait du filename."""

    edition_label: Optional[str] = None
    """Label complet (ex: 'Amendment 28', 'Regulation (EU) 2021/821')."""

    region: Optional[str] = None
    """Région inférée (EU/US/Global) depuis filename + entity_hints."""

    product_version: Optional[str] = None
    """Product/standard inféré (ex: 'CS-25', 'EU Regulation')."""

    sources_count: int = 0
    """Nombre de sources convergentes (filename, markers, entity_hints, primary_subject)."""

    confidence: str = "low"
    """high/medium/low selon le nombre de sources convergentes."""

    raw_filename_year: Optional[int] = None
    """Année extraite du filename uniquement."""

    raw_amdt_number: Optional[int] = None
    """Numéro amdt extrait du filename uniquement."""

    cache_markers_years: list[int] = field(default_factory=list)
    """Années trouvées dans cache strong/weak markers."""

    cache_entity_years: list[int] = field(default_factory=list)
    """Années trouvées dans cache entity_hints (regulations explicites)."""

    primary_subject_years: list[int] = field(default_factory=list)
    """Années trouvées dans DocumentContext.primary_subject."""


# ============================================================================
# Filename parsing
# ============================================================================
# NOTE : ces patterns sont structurels (filename naming convention), pas
# sémantiques sur du texte naturel. Domain-agnostic dans la mesure où les
# filenames adoptent une convention `{family}_{type}_{year}_{nb}` ou
# `{family}_{type}_{nb}_{year}`. À étendre selon les corpus rencontrés.

# Pattern dualuse_(reg|del)_YYYY_NNNN  (ex: dualuse_reg_2021_821)
_DUALUSE_PATTERN = re.compile(r"_(reg|del)_(\d{4})_(\d+)")

# Pattern dualuse NNN_YYYY_original  (ex: dualuse_reg_428_2009_original)
_DUALUSE_OLD_PATTERN = re.compile(r"_(\d+)_(\d{4})_original")

# Pattern cs25_amdt_NN ou cs25_change_amdt_NN
_CS25_AMDT_PATTERN = re.compile(r"cs25_(?:change_)?amdt_(\d+)")


def parse_filename(doc_id: str) -> dict[str, Any]:
    """
    Parse un doc_id (basé sur le filename) pour extraire year/edition/region.

    Returns:
        Dict avec clés : raw_filename_year, raw_amdt_number, edition_label,
        region, product_version (selon ce qui est détectable).
    """
    out: dict[str, Any] = {
        "raw_filename_year": None,
        "raw_amdt_number": None,
        "edition_label": None,
        "region": None,
        "product_version": None,
    }

    # cs25_amdt_NN
    m = _CS25_AMDT_PATTERN.search(doc_id)
    if m:
        amdt = int(m.group(1))
        out["raw_amdt_number"] = amdt
        out["raw_filename_year"] = CS25_AMDT_TO_YEAR.get(amdt)
        out["edition_label"] = f"Amendment {amdt}"
        out["product_version"] = "CS-25"
        out["region"] = "EU"  # CS-25 = EASA = EU
        return out

    # dualuse_reg/del_YYYY_NNNN
    m = _DUALUSE_PATTERN.search(doc_id)
    if m:
        rule_type, year, num = m.group(1), int(m.group(2)), m.group(3)
        out["raw_filename_year"] = year
        prefix = "Regulation" if rule_type == "reg" else "Delegated Regulation"
        out["edition_label"] = f"{prefix} (EU) {year}/{num}"
        out["region"] = "EU"
        out["product_version"] = "EU Dual-Use Items Regulation"
        return out

    # dualuse_NNN_YYYY_original
    m = _DUALUSE_OLD_PATTERN.search(doc_id)
    if m:
        num, year = m.group(1), int(m.group(2))
        out["raw_filename_year"] = year
        out["edition_label"] = f"Council Regulation (EC) No {num}/{year}"
        out["region"] = "EU"
        out["product_version"] = "EU Dual-Use Items Regulation"
        return out

    return out


# ============================================================================
# Cache markers extraction
# ============================================================================

_YEAR_REGEX = re.compile(r"\b((?:19|20)\d{2})\b")


def parse_cache_markers(cache_data: dict) -> dict[str, list[int]]:
    """
    Extrait les années depuis cache.extraction.doc_context.

    Sources (toutes pré-calculées par Docling, pas de lecture de full_text) :
    - strong_markers : signaux forts (titres, headers répétés)
    - weak_markers : signaux faibles
    - document_context.entity_hints : entités regulations/standards explicites
    """
    ext = cache_data.get("extraction", {}) or {}
    dc = ext.get("doc_context", {}) or {}
    inner_dc = dc.get("document_context", {}) or {}

    strong_markers = dc.get("strong_markers", []) or []
    weak_markers = dc.get("weak_markers", []) or []
    entity_hints = inner_dc.get("entity_hints", []) or []

    years_in_markers: list[int] = []
    for marker in strong_markers + weak_markers:
        for y_match in _YEAR_REGEX.findall(str(marker)):
            years_in_markers.append(int(y_match))

    years_in_entities: list[int] = []
    for eh in entity_hints:
        if not isinstance(eh, dict):
            continue
        type_hint = eh.get("type_hint", "")
        # On ne prend que les entités regulatory (regulation, standard, law)
        if type_hint not in ("regulation", "standard", "law"):
            continue
        label = eh.get("label", "")
        for y_match in _YEAR_REGEX.findall(str(label)):
            years_in_entities.append(int(y_match))

    return {
        "markers_years": sorted(set(years_in_markers)),
        "entity_years": sorted(set(years_in_entities)),
    }


# ============================================================================
# Primary subject parsing (DocumentContext.primary_subject)
# ============================================================================

def parse_primary_subject(primary_subject: Optional[str]) -> list[int]:
    """Extrait les années depuis le primary_subject (texte court)."""
    if not primary_subject:
        return []
    return sorted(set(int(y) for y in _YEAR_REGEX.findall(primary_subject)))


# ============================================================================
# Main entry point — combine all sources
# ============================================================================

def extract_tier1_hints(
    doc_id: str,
    cache_data: Optional[dict] = None,
    primary_subject: Optional[str] = None,
) -> Tier1Hints:
    """
    Extrait Tier 1 hints depuis filename + cache markers + primary_subject.

    Cross-validation : la `publication_year` retenue est celle qui apparaît
    dans le plus grand nombre de sources convergentes.

    Args:
        doc_id: Identifiant du document (typ: filename + hash suffix)
        cache_data: Contenu du cache .v5cache.json (peut être None)
        primary_subject: DocumentContext.primary_subject (peut être None)

    Returns:
        Tier1Hints — utilisable directement comme prior pour le Tier 2 LLM
    """
    # 1. Filename
    fn_info = parse_filename(doc_id)

    # 2. Cache markers (si dispo)
    cache_years = {"markers_years": [], "entity_years": []}
    if cache_data:
        cache_years = parse_cache_markers(cache_data)

    # 3. Primary subject
    subject_years = parse_primary_subject(primary_subject)

    # 4. Cross-validation : la year la plus fréquente parmi toutes les sources
    all_years_with_source: list[tuple[int, str]] = []
    if fn_info["raw_filename_year"]:
        all_years_with_source.append((fn_info["raw_filename_year"], "filename"))
    for y in cache_years["markers_years"]:
        all_years_with_source.append((y, "cache_marker"))
    for y in cache_years["entity_years"]:
        all_years_with_source.append((y, "cache_entity"))
    for y in subject_years:
        all_years_with_source.append((y, "primary_subject"))

    inferred_year: Optional[int] = None
    sources_count = 0
    if all_years_with_source:
        year_counter = Counter(y for y, _ in all_years_with_source)
        inferred_year, sources_count = year_counter.most_common(1)[0]

    confidence = "low"
    if sources_count >= 3:
        confidence = "high"
    elif sources_count == 2:
        confidence = "medium"

    return Tier1Hints(
        publication_year=inferred_year,
        edition_number=fn_info.get("raw_amdt_number"),
        edition_label=fn_info.get("edition_label"),
        region=fn_info.get("region"),
        product_version=fn_info.get("product_version"),
        sources_count=sources_count,
        confidence=confidence,
        raw_filename_year=fn_info.get("raw_filename_year"),
        raw_amdt_number=fn_info.get("raw_amdt_number"),
        cache_markers_years=cache_years["markers_years"],
        cache_entity_years=cache_years["entity_years"],
        primary_subject_years=subject_years,
    )


def load_cache_for_doc_id(doc_id: str, cache_dir: Path) -> Optional[dict]:
    """
    Charge le cache .v5cache.json correspondant à un doc_id.

    Le cache est nommé par hash, on cherche celui dont
    extraction.document_id == doc_id.
    """
    if not cache_dir.exists():
        return None
    for cf in cache_dir.glob("*.v5cache.json"):
        try:
            data = json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            continue
        cache_doc_id = (
            data.get("extraction", {}).get("document_id")
            or data.get("document_id")
        )
        if cache_doc_id == doc_id:
            return data
    return None


__all__ = [
    "Tier1Hints",
    "CS25_AMDT_TO_YEAR",
    "parse_filename",
    "parse_cache_markers",
    "parse_primary_subject",
    "extract_tier1_hints",
    "load_cache_for_doc_id",
]
