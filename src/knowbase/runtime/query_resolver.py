"""
R1 — Query Resolver V1.1.

Reçoit la question utilisateur, détermine le **mode de réponse** (1 sur 7) +
extrait les entités/temporal_anchor. Output utilisé par EvidencePlanner pour
choisir le régime + planifier le retrieval.

Stratégie hybride :
1. Heuristiques rapides (regex légères + mots-clés sémantiques universels) pour
   les cas évidents (CONFLICT_RISK, SNAPSHOT_TEMPORAL, DIFF_EVOLUTION détectables
   structurellement).
2. LLM fallback pour les cas ambigus (LOOKUP_FACTUAL vs APPLICABILITY_QUERY,
   SYNTHESIS_SUMMARY).

Pattern V1.1 :
- Multilingue + domain-agnostic
- Pas de regex sur du contenu domain-specific (anti-pattern lexical)
- Les heuristiques sont sémantiques (ex: "?" + "what" → factual lookup)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ResponseMode(str, Enum):
    """Les 7 modes de réponse V1.1."""

    LOOKUP_FACTUAL = "LOOKUP_FACTUAL"
    """Question factuelle directe : 'Quel est le seuil X ?', 'Quelle est la date de Y ?'"""

    APPLICABILITY_QUERY = "APPLICABILITY_QUERY"
    """Quelles règles s'appliquent à un scope donné : 'Règles pour un laser de 100ps ?'"""

    SNAPSHOT_TEMPORAL = "SNAPSHOT_TEMPORAL"
    """Quelle était la règle à un point dans le temps : 'Quel était le seuil en 2018 ?'"""

    DIFF_EVOLUTION = "DIFF_EVOLUTION"
    """Quels changements entre deux points temporels : 'Qu'a changé entre 2009 et 2021 ?'"""

    CONFLICT_RISK = "CONFLICT_RISK"
    """Quelles contradictions / conflits dans le corpus : 'Risques de conflits sur X ?'"""

    EXPLORATION_RELATIONAL = "EXPLORATION_RELATIONAL"
    """Navigation par relation : 'Quels termes définis dans le corpus ?', 'Quelles exceptions ?'"""

    SYNTHESIS_SUMMARY = "SYNTHESIS_SUMMARY"
    """Résumé / synthèse étendue : 'Résume le doc X', 'Vue d'ensemble du domaine'"""


@dataclass
class ResolvedQuery:
    """Output du QueryResolver."""

    raw_query: str
    """Question originale utilisateur."""

    mode: ResponseMode
    """Mode de réponse détecté."""

    confidence: float = 0.5
    """Confidence de la détection mode (0-1)."""

    intent: Optional[str] = None
    """Intent verbalisé (ex: 'recherche d'une valeur seuil')."""

    entities: list[str] = field(default_factory=list)
    """Entités explicitement nommées dans la query (ex: 'CS-25', 'laser')."""

    temporal_anchor: Optional[date] = None
    """Pour SNAPSHOT/DIFF : date de référence."""

    temporal_range: Optional[tuple[date, date]] = None
    """Pour DIFF : période [T1, T2]."""

    persona_hints: dict = field(default_factory=dict)
    """Hints sur le persona (compliance officer, explorer, reader). À remplir
    par le runtime avec les overrides utilisateur."""


# ============================================================================
# Heuristiques universelles (sémantiques, multilingues)
# ============================================================================
# Patterns conservatifs sur les marqueurs structurels (chiffres, ponctuation,
# verbes courants). Le LLM tranche si plusieurs heuristiques matchent.

# Détection de date dans la query (universel : YYYY ou YYYY-MM-DD ou DD/MM/YYYY)
_DATE_REGEX = re.compile(r"\b((?:19|20)\d{2})(?:[-/](\d{1,2}))?(?:[-/](\d{1,2}))?\b")

# Détection de mots-clés sémantiques très généraux (multilingues)
# "since/depuis/seit/desde" + "until/jusqu'à/bis/hasta" + "between/entre/zwischen"
_TEMPORAL_DIFF_HINTS = re.compile(
    r"\b(between|entre|zwischen|change[sd]?|evolu(?:tion|ed)|évolu|changement|"
    r"diff(?:erence|érence)|since|depuis|seit|desde|"
    r"compare[ds]?|compar(?:e|er|ed))\b",
    re.IGNORECASE,
)

# Marqueurs CONFLICT_RISK
_CONFLICT_HINTS = re.compile(
    r"\b(contradict(?:ion|s|ory)?|conflict(?:s|ing)?|incompatibl[e]|"
    r"contradiction[s]?|conflit[s]?|incohérence|"
    r"opposing|mutually|exclusiv)\b",
    re.IGNORECASE,
)

# Marqueurs APPLICABILITY (qui s'applique à...)
_APPLICABILITY_HINTS = re.compile(
    r"\b(apply|applies|applicable|applicabilit|applique[snrz]?|gilt|aplica[bn]?|"
    r"valid for|in scope|covers?|relevant for|concerne[snrz]?|"
    r"requirement[s]? for|exigence[s]? pour)\b",
    re.IGNORECASE,
)

# Marqueurs SYNTHESIS
_SYNTHESIS_HINTS = re.compile(
    r"\b(summari[sz]e|summary|résum|synthèse|overview|vue d'ensemble|"
    r"explain|explique[snrz]?|what is the gist|tell me about|parle[snrz]?\s+moi)\b",
    re.IGNORECASE,
)

# Marqueurs EXPLORATION_RELATIONAL (lister, énumérer)
# Note : énumér[a-zéèà]+ pour matcher toutes les conjugaisons (énumérez, énumérer,
# énumère, énumérons, énuméré, énumères, etc.) — la regex précédente ratait
# énumérez/énumérer car elle attendait "énumère" + 1 char optionnel.
_EXPLORATION_HINTS = re.compile(
    r"\b(list (all|the)?|liste[snrz]? (de|des|tous?|toutes?)|"
    r"all the (rules|exceptions|definitions|terms|claims|relations)|"
    r"toutes les (règles|exceptions|définitions|relations)|"
    r"which (rules|exceptions|definitions|relations)|"
    r"quelles? (règles|exceptions|définitions|relations)|"
    r"enumerate|énumér[a-zéèà]+|énumère[snrz]?)\b",
    re.IGNORECASE,
)

# Noms canoniques des 12 LogicalRelation types V3.3 — universels (font partie
# du schéma KG, pas domain-specific). Si la question nomme explicitement un
# de ces types, c'est un fort signal pour un mode KG_LED structurel.
_LOGICAL_RELATION_TYPES = re.compile(
    r"\b("
    r"SUBSETS?|SUPERSETS?|"
    r"EQUIVALENTE?S?|ÉQUIVALENTE?S?|"
    r"OVERLAPS?|DISJOINTS?|"
    r"CONFLICTS?|CONFLITS?|"
    r"EXCEPTIONS?|"
    r"DEFINITIONS?|DÉFINITIONS?|"
    r"SUPERSEDES?|SUPERSEDED|"
    r"EVOLVES?_FROM|EVOLVES?\s+FROM|"
    r"REAFFIRMS?"
    r")\b",
    re.IGNORECASE,
)


class QueryResolver:
    """
    Résout une question en ResolvedQuery (mode + intent + entities + dates).

    Stratégie : heuristiques rapides en premier, LLM fallback uniquement si ambigu.
    """

    def __init__(self, llm_classifier=None):
        """
        Args:
            llm_classifier: optionnel, fonction callable pour fallback LLM
                            (signature : (query: str) -> ResponseMode)
        """
        self.llm_classifier = llm_classifier

    def resolve(self, query: str, persona_hints: Optional[dict] = None) -> ResolvedQuery:
        """Résout la query en ResolvedQuery."""
        clean = (query or "").strip()
        if not clean:
            return ResolvedQuery(
                raw_query=query,
                mode=ResponseMode.LOOKUP_FACTUAL,
                confidence=0.0,
                persona_hints=persona_hints or {},
            )

        # 1. Détection date(s) dans la query
        dates = self._extract_dates(clean)

        # 2. Heuristiques sémantiques (couches de plus en plus spécifiques)
        mode, confidence = self._heuristic_classify(clean, dates)

        # 3. LLM fallback si ambigu et qu'on a un classifier
        if confidence < 0.6 and self.llm_classifier:
            try:
                llm_mode = self.llm_classifier(clean)
                mode = llm_mode
                confidence = 0.75  # LLM gives medium confidence
            except Exception as e:
                logger.warning(f"[QueryResolver] LLM fallback failed: {e}")

        # 4. Build resolved
        resolved = ResolvedQuery(
            raw_query=query,
            mode=mode,
            confidence=confidence,
            persona_hints=persona_hints or {},
        )

        # Temporal anchors
        if mode == ResponseMode.SNAPSHOT_TEMPORAL and dates:
            resolved.temporal_anchor = dates[0]
        elif mode == ResponseMode.DIFF_EVOLUTION and len(dates) >= 2:
            resolved.temporal_range = (dates[0], dates[1])
        elif mode == ResponseMode.DIFF_EVOLUTION and dates:
            resolved.temporal_range = (dates[0], date.today())

        # Entities (extraction très simple : noms propres / mots capitalisés)
        # On laisse le LLM/spaCy faire mieux en runtime, ici juste un draft.
        resolved.entities = self._extract_entities_naive(clean)

        return resolved

    # ------------------------------------------------------------------------
    # Heuristics
    # ------------------------------------------------------------------------

    def _heuristic_classify(self, query: str, dates: list[date]) -> tuple[ResponseMode, float]:
        """Classification heuristique. Returns (mode, confidence)."""
        # CONFLICT_RISK : marqueur explicite de contradiction
        # On check AVANT _LOGICAL_RELATION_TYPES car CONFLICT est aussi un type V3.3,
        # mais "contradictions" en langage naturel = mode CONFLICT_RISK direct.
        if _CONFLICT_HINTS.search(query):
            return ResponseMode.CONFLICT_RISK, 0.85

        # EXPLORATION_RELATIONAL boosté : si la question nomme un type
        # LogicalRelation (EQUIVALENT/SUBSET/EXCEPTION/...) ET un verbe d'énumération,
        # c'est très probablement de l'exploration KG.
        has_relation_type = bool(_LOGICAL_RELATION_TYPES.search(query))
        has_enumeration = bool(_EXPLORATION_HINTS.search(query))
        if has_relation_type and has_enumeration:
            return ResponseMode.EXPLORATION_RELATIONAL, 0.9

        # DIFF_EVOLUTION : 2+ dates ou marqueur de changement
        if len(dates) >= 2 or _TEMPORAL_DIFF_HINTS.search(query):
            return ResponseMode.DIFF_EVOLUTION, 0.8

        # SNAPSHOT_TEMPORAL : 1 date + question factuelle
        if len(dates) == 1:
            return ResponseMode.SNAPSHOT_TEMPORAL, 0.75

        # APPLICABILITY_QUERY : marqueur "applies to / applique à"
        if _APPLICABILITY_HINTS.search(query):
            return ResponseMode.APPLICABILITY_QUERY, 0.7

        # SYNTHESIS_SUMMARY
        if _SYNTHESIS_HINTS.search(query):
            return ResponseMode.SYNTHESIS_SUMMARY, 0.75

        # EXPLORATION_RELATIONAL : "list all", "which X"
        if has_enumeration:
            return ResponseMode.EXPLORATION_RELATIONAL, 0.7

        # EXPLORATION sans verbe d'énumération mais avec type explicite (ex: "Quelles
        # SUBSET dans le corpus ?") — confidence moyenne, peut être overridée par LLM.
        if has_relation_type:
            return ResponseMode.EXPLORATION_RELATIONAL, 0.65

        # Default LOOKUP_FACTUAL (low confidence, le LLM peut overrider)
        return ResponseMode.LOOKUP_FACTUAL, 0.5

    def _extract_dates(self, query: str) -> list[date]:
        """Extrait les dates de la query."""
        out = []
        for m in _DATE_REGEX.finditer(query):
            year = int(m.group(1))
            month = int(m.group(2)) if m.group(2) else 1
            day = int(m.group(3)) if m.group(3) else 1
            try:
                out.append(date(year, month, day))
            except ValueError:
                continue
        return out

    def _extract_entities_naive(self, query: str) -> list[str]:
        """Extraction très naïve d'entités (mots capitalisés). Le runtime fait mieux."""
        # On capture les mots en CAPS ou Mixed-case >= 2 caractères, en évitant les
        # premiers mots (souvent capitalisés au début de phrase).
        words = re.findall(r"\b([A-Z][a-zA-Z\-]{1,}|[A-Z]{2,}(?:[-/][A-Z\d]{1,})*)\b", query)
        # Filtre quelques mots fréquents
        stoplist = {"What", "How", "When", "Where", "Why", "Quel", "Quelle", "Quels", "Quelles",
                    "The", "A", "An", "Le", "La", "Les", "Un", "Une", "Des"}
        return [w for w in words if w not in stoplist][:10]


__all__ = ["QueryResolver", "ResponseMode", "ResolvedQuery"]
