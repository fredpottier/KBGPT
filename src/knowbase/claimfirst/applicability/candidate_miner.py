# src/knowbase/claimfirst/applicability/candidate_miner.py
"""
Layer B: CandidateMiner — Scan déterministe exhaustif (0 appel LLM).

Scanne TOUTES les EvidenceUnits pour détecter:
1. Markers d'applicabilité (cue words par catégorie)
2. Value candidates (years, versions, named_versions, dates)

Chaque candidat porte des statistiques:
- frequency, in_title, in_header_zone, cooccurs_with_subject
- nearby_markers (≤200 chars), context_snippets (max 3)

100% domain-agnostic (INV-25).
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from knowbase.claimfirst.applicability.models import (
    CandidateProfile,
    EvidenceUnit,
    MarkerCategory,
    MarkerHit,
    ValueCandidate,
)

logger = logging.getLogger(__name__)


# ============================================================================
# MARKER PATTERNS (domain-agnostic)
# ============================================================================

MARKER_PATTERNS: Dict[MarkerCategory, List[re.Pattern]] = {
    MarkerCategory.CONDITIONALITY: [
        re.compile(r"\b(if|only\s+if|unless|except|provided\s+that|subject\s+to)\b", re.IGNORECASE),
    ],
    MarkerCategory.SCOPE: [
        re.compile(r"\b(applies?\s+to|in\s+scope|limited\s+to|for\s+the\s+purposes?\s+of)\b", re.IGNORECASE),
    ],
    MarkerCategory.TEMPORAL: [
        re.compile(r"\b(effective\s+(?:as\s+of|from)|from|until|starting|supersedes|valid\s+(?:from|until|through))\b", re.IGNORECASE),
    ],
    MarkerCategory.DEFINITION: [
        re.compile(r"\b(means|shall\s+mean|is\s+defined\s+as|refers?\s+to)\b", re.IGNORECASE),
    ],
    MarkerCategory.ENVIRONMENT: [
        re.compile(r"\b(when\s+configured|prerequisite|requires|only\s+for|available\s+with|compatible\s+with)\b", re.IGNORECASE),
    ],
    MarkerCategory.REFERENCE: [
        re.compile(r"\b(based\s+on|derived\s+from|version|release|edition)\b", re.IGNORECASE),
    ],
}


# ============================================================================
# VALUE PATTERNS (domain-agnostic)
# ============================================================================

# Contextes copyright à filtrer pour les années
COPYRIGHT_CONTEXT_PATTERN = re.compile(
    r"(copyright|©|\(c\)|all\s+rights\s+reserved|proprietary|confidential)",
    re.IGNORECASE,
)

# Contextes SLA/métriques à filtrer pour les versions
SLA_CONTEXT_PATTERN = re.compile(
    r"(sla|uptime|availability|service\s+level|guaranteed|latency|throughput|"
    r"response\s+time|success\s+rate|error\s+rate|cpu|memory|bandwidth)",
    re.IGNORECASE,
)

# Year: 4 digits, 19xx ou 20xx
YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")

# Version: v1.0, 2.1.3, etc. (max 3 segments pour exclure les IP-like X.X.X.X)
VERSION_PATTERN = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?)\b")

# Filtre IP: exclut les valeurs qui ressemblent à des adresses IP (4 octets 0-255)
_IP_LIKE_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

# Named version: Version X, Release X, Edition X, Phase X, FPS X, SP X
# Le token capturé après le mot-clé DOIT contenir au moins un chiffre
# pour éviter les faux positifs comme "version of", "release notes", etc.
NAMED_VERSION_PATTERN = re.compile(
    r"\b((?:Version|Release|Edition|Phase|FPS|SP)\s+(?=\S*\d)\S+)",
    re.IGNORECASE,
)

# Ponctuation à retirer en fin de valeur extraite
_TRAILING_PUNCT = re.compile(r"[.,;:!?]+$")

# Date ISO: 2024-01-15, 2024/01/15
DATE_ISO_PATTERN = re.compile(r"\b(\d{4}[-/]\d{2}[-/]\d{2})\b")

# Date textuelle: January 2024, Jan 2024, 15 January 2024
DATE_TEXT_PATTERN = re.compile(
    r"\b(\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
    r"Sep|Oct|Nov|Dec)\.?\s+\d{4}\b",
    re.IGNORECASE,
)

# Proximité max (en chars) pour co-occurrence marker ↔ value
PROXIMITY_THRESHOLD = 200

# Max context snippets par candidat
MAX_CONTEXT_SNIPPETS = 3

# Taille du snippet de contexte (±N chars autour de la valeur)
CONTEXT_SNIPPET_RADIUS = 50


class CandidateMiner:
    """
    Scan déterministe de toutes les EvidenceUnits.

    Extrait markers et value candidates sans aucun appel LLM.
    """

    def mine(
        self,
        units: List[EvidenceUnit],
        doc_id: str,
        title: Optional[str] = None,
        primary_subject: Optional[str] = None,
    ) -> CandidateProfile:
        """
        Scan toutes les EvidenceUnits pour extraire markers et value candidates.

        Args:
            units: Liste d'EvidenceUnits (sortie Layer A)
            doc_id: ID du document
            title: Titre du document (pour détecter in_title)
            primary_subject: Sujet principal (pour co-occurrence)

        Returns:
            CandidateProfile complet
        """
        profile = CandidateProfile(
            doc_id=doc_id,
            title=title,
            primary_subject=primary_subject,
            total_units=len(units),
            total_chars=sum(len(u.text) for u in units),
        )

        if not units:
            return profile

        # Calculer le seuil header_zone (10% premiers passages)
        max_passage_idx = max(u.passage_idx for u in units)
        header_zone_threshold = max(1, int(max_passage_idx * 0.1))

        # 1. Détecter les markers dans chaque unité
        all_markers: List[MarkerHit] = []
        markers_by_unit: Dict[str, List[MarkerHit]] = {}

        for unit in units:
            unit_markers = self._detect_markers(unit)
            if unit_markers:
                all_markers.extend(unit_markers)
                markers_by_unit[unit.unit_id] = unit_markers

        profile.markers = all_markers
        profile.markers_by_category = {}
        for m in all_markers:
            cat = m.category.value
            profile.markers_by_category[cat] = profile.markers_by_category.get(cat, 0) + 1

        # 2. Extraire les value candidates
        raw_candidates: Dict[str, ValueCandidate] = {}
        # Clé = (value_type, raw_value) → ValueCandidate

        for unit in units:
            is_header = unit.passage_idx <= header_zone_threshold
            values = self._extract_values(unit)

            for value_type, raw_value, char_offset in values:
                key = f"{value_type}:{raw_value}"

                if key not in raw_candidates:
                    candidate_id = self._make_candidate_id(value_type, raw_value)
                    raw_candidates[key] = ValueCandidate(
                        candidate_id=candidate_id,
                        raw_value=raw_value,
                        value_type=value_type,
                        unit_ids=[],
                        frequency=0,
                        in_title=False,
                        in_header_zone=False,
                        cooccurs_with_subject=False,
                        nearby_markers=[],
                        context_snippets=[],
                    )

                vc = raw_candidates[key]
                vc.frequency += 1

                if unit.unit_id not in vc.unit_ids:
                    vc.unit_ids.append(unit.unit_id)

                if is_header:
                    vc.in_header_zone = True

                # Co-occurrence avec le sujet principal
                if primary_subject and not vc.cooccurs_with_subject:
                    if primary_subject.lower() in unit.text.lower():
                        vc.cooccurs_with_subject = True

                # Markers à proximité
                if unit.unit_id in markers_by_unit:
                    for marker in markers_by_unit[unit.unit_id]:
                        if abs(marker.char_offset - char_offset) <= PROXIMITY_THRESHOLD:
                            marker_desc = f"{marker.category.value}:{marker.matched_text}"
                            if marker_desc not in vc.nearby_markers:
                                vc.nearby_markers.append(marker_desc)

                # Context snippets (max 3)
                if len(vc.context_snippets) < MAX_CONTEXT_SNIPPETS:
                    snippet = self._extract_context_snippet(unit.text, char_offset, raw_value)
                    if snippet and snippet not in vc.context_snippets:
                        vc.context_snippets.append(snippet)

        # 3. Détecter in_title
        if title:
            title_lower = title.lower()
            for vc in raw_candidates.values():
                if vc.raw_value.lower() in title_lower:
                    vc.in_title = True

        profile.value_candidates = list(raw_candidates.values())

        logger.debug(
            f"[OSMOSE:CandidateMiner] {doc_id}: "
            f"{len(all_markers)} markers, "
            f"{len(profile.value_candidates)} value candidates "
            f"({profile.markers_by_category})"
        )

        return profile

    # =========================================================================
    # Marker Detection
    # =========================================================================

    def _detect_markers(self, unit: EvidenceUnit) -> List[MarkerHit]:
        """Détecte tous les markers d'applicabilité dans une EvidenceUnit."""
        hits: List[MarkerHit] = []
        text = unit.text

        for category, patterns in MARKER_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    hits.append(MarkerHit(
                        category=category,
                        matched_text=match.group(0),
                        unit_id=unit.unit_id,
                        char_offset=match.start(),
                    ))

        return hits

    # =========================================================================
    # Value Extraction
    # =========================================================================

    def _extract_values(
        self, unit: EvidenceUnit
    ) -> List[Tuple[str, str, int]]:
        """
        Extrait les value candidates d'une EvidenceUnit.

        Returns:
            Liste de (value_type, raw_value, char_offset)
        """
        results: List[Tuple[str, str, int]] = []
        text = unit.text

        # Named versions en premier (plus spécifiques)
        for match in NAMED_VERSION_PATTERN.finditer(text):
            raw = _TRAILING_PUNCT.sub("", match.group(1).strip())
            results.append(("named_version", raw, match.start()))

        # Versions numériques (v1.0, 2.1.3)
        for match in VERSION_PATTERN.finditer(text):
            raw = match.group(1)
            # Exclure les adresses IP (0.0.0.0, 123.456.789.0, etc.)
            if _IP_LIKE_PATTERN.match(raw):
                continue
            # Exclure les pourcentages (99.9%, 99.7 %)
            end_pos = match.end()
            rest = text[end_pos:end_pos + 3].lstrip()
            if rest.startswith("%") or rest.startswith("％"):
                continue
            # Exclure les valeurs en contexte SLA/métriques (±100 chars)
            offset = match.start()
            ctx_start = max(0, offset - 100)
            ctx_end = min(len(text), end_pos + 100)
            nearby_text = text[ctx_start:ctx_end]
            if SLA_CONTEXT_PATTERN.search(nearby_text):
                try:
                    major = int(raw.split(".")[0])
                    if major >= 50:
                        continue  # 99.9 near SLA → skip
                except ValueError:
                    pass
            # Exclure si déjà capturé par named_version
            if not self._overlaps_existing(match.start(), results):
                results.append(("version", raw, match.start()))

        # Dates ISO
        for match in DATE_ISO_PATTERN.finditer(text):
            results.append(("date", match.group(1), match.start()))

        # Dates textuelles
        for match in DATE_TEXT_PATTERN.finditer(text):
            results.append(("date", match.group(0).strip(), match.start()))

        # Années (avec filtre copyright)
        for match in YEAR_PATTERN.finditer(text):
            year_str = match.group(1)
            offset = match.start()

            # Vérifier le contexte copyright (±100 chars)
            context_start = max(0, offset - 100)
            context_end = min(len(text), offset + len(year_str) + 100)
            context = text[context_start:context_end]

            if COPYRIGHT_CONTEXT_PATTERN.search(context):
                continue  # Filtrer copyright

            # Exclure si déjà dans une date ISO ou named_version
            if not self._overlaps_existing(offset, results):
                results.append(("numeric_identifier", year_str, offset))

        return results

    def _overlaps_existing(
        self,
        offset: int,
        existing: List[Tuple[str, str, int]],
    ) -> bool:
        """Vérifie si un offset chevauche un candidat déjà extrait."""
        for _, raw, start in existing:
            end = start + len(raw)
            if start <= offset < end:
                return True
        return False

    def _extract_context_snippet(
        self,
        text: str,
        char_offset: int,
        raw_value: str,
    ) -> str:
        """Extrait un snippet de contexte autour de la valeur (±50 chars)."""
        start = max(0, char_offset - CONTEXT_SNIPPET_RADIUS)
        end = min(len(text), char_offset + len(raw_value) + CONTEXT_SNIPPET_RADIUS)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet

    def _make_candidate_id(self, value_type: str, raw_value: str) -> str:
        """Génère un ID unique pour un candidat."""
        raw_hash = hashlib.md5(raw_value.encode()).hexdigest()[:8]
        return f"VC:{value_type}:{raw_hash}"


__all__ = [
    "CandidateMiner",
]
