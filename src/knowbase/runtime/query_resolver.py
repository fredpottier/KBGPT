"""
R1 — Query Resolver V1.1 (LLM-first, V3.3-conforming).

Reçoit la question utilisateur, détermine le **mode de réponse** (1 sur 7) +
extrait les entités/temporal_anchor. Output utilisé par EvidencePlanner pour
choisir le régime + planifier le retrieval.

**Stratégie V3.3** (cf. feedback_no_lexical_patterns_temporal.md) :

> Le LLM est l'extracteur sémantique unique. Pas de regex/keywords lexicaux
> pour classifier des intentions ou extraire des dates — viole multilingue
> (EN/FR/DE/ES/IT/...), domain-agnostic (regulatory/IT/medical/legal/aero),
> robustesse (cas hors-pattern ratés).

Pipeline :
1. Appel LLM (Qwen2.5-14B AWQ sur EC2 vLLM) avec prompt **sémantique pur**
   décrivant les 7 modes en prose, sans listes de keywords.
2. Output JSON structuré : `{mode, confidence, intent, entities,
   temporal_anchor, temporal_range}`.
3. Filet de sécurité : si le LLM crash (timeout/parse error), heuristique
   minimale logging un warning. Pas la voie principale.

Multilingue + domain-agnostic par construction du LLM sémantique.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

import httpx

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
    """Quelles contradictions / conflits dans le corpus."""

    EXPLORATION_RELATIONAL = "EXPLORATION_RELATIONAL"
    """Navigation par relation typée : 'Listez les EQUIVALENT', 'Quelles EXCEPTIONS'."""

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
    """Entités explicitement nommées dans la query."""

    temporal_anchor: Optional[date] = None
    """Pour SNAPSHOT/DIFF : date de référence (extraite par LLM)."""

    temporal_range: Optional[tuple[date, date]] = None
    """Pour DIFF : période [T1, T2] (extraite par LLM)."""

    persona_hints: dict = field(default_factory=dict)
    """Hints sur le persona (compliance officer, explorer, reader)."""

    classifier_source: str = "llm"
    """'llm' (cas normal) | 'fallback_safety' (LLM crashé, mode par défaut)."""


# ============================================================================
# Prompt LLM sémantique (V3.3-conforming, NO keywords)
# ============================================================================

PROMPT_CLASSIFY_MODE = """You are a query classifier for an OSMOSIS knowledge graph runtime. Your task is to classify the user question into ONE of 7 response modes, and extract any temporal anchors.

The 7 response modes describe what KIND of answer the user needs:

1. **LOOKUP_FACTUAL** — The user wants a specific factual value, threshold, definition, or attribute that is recorded somewhere in the corpus. They are asking "what IS X?" expecting a single answer.

2. **APPLICABILITY_QUERY** — The user wants to know which rules, regulations, or constraints apply to a given scope, situation, or entity. They are asking "what rules govern Y?" or "what applies when Z?". Scope is the key — a specific situation, parameter range, or entity class.

3. **SNAPSHOT_TEMPORAL** — The user asks what was true AT A SPECIFIC POINT IN TIME. They want a historical state, not the current one. Look for explicit time anchor (a year, a date, a period reference like "in 2018", "before 2021", "as of January").

4. **DIFF_EVOLUTION** — The user asks WHAT CHANGED between two points in time, or how something evolved. They want delta/diff, not snapshot. Look for two time anchors or evolution words.

5. **CONFLICT_RISK** — The user asks about contradictions, conflicts, incompatibilities, or inconsistencies inside the corpus. They want to surface tensions between sources.

6. **EXPLORATION_RELATIONAL** — The user wants to ENUMERATE or NAVIGATE elements by their structural relation type. They want a list grouped by relation kind (subset/superset/equivalent/conflict/exception/definition/supersedes/etc.). Look for enumeration intent ("list all", "enumerate", "what are the X") combined with a structural concept (relations, exceptions, definitions, types).

7. **SYNTHESIS_SUMMARY** — The user asks for a SUMMARY or OVERVIEW of a topic, document, or domain. They want broad coverage with multiple perspectives, not a single fact.

The question can be in any language (English, French, German, Spanish, Italian, ...) and from any domain (aerospace, legal, medical, IT, regulatory, etc.). Use semantic understanding, not keyword matching.

You also extract:
- **temporal_anchor** : if the question references a single point in time, extract it as ISO date "YYYY-MM-DD" (use YYYY-01-01 if only year given).
- **temporal_range** : if the question covers a period, extract `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`.
- **entities** : up to 5 named entities, concepts, or specific subjects mentioned in the question.
- **intent** : a one-line verbalization of what the user actually wants (in the question's language).

User question:
__QUESTION__

Respond with ONLY valid JSON in this exact format (no preamble, no markdown):

{
  "mode": "LOOKUP_FACTUAL" | "APPLICABILITY_QUERY" | "SNAPSHOT_TEMPORAL" | "DIFF_EVOLUTION" | "CONFLICT_RISK" | "EXPLORATION_RELATIONAL" | "SYNTHESIS_SUMMARY",
  "confidence": 0.0-1.0,
  "intent": "one-line intent verbalization",
  "entities": ["entity1", "entity2"],
  "temporal_anchor": "YYYY-MM-DD" | null,
  "temporal_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} | null
}"""


# ============================================================================
# QueryResolver
# ============================================================================

VLLM_URL = os.getenv("VLLM_URL", "http://3.79.236.241:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")


class QueryResolver:
    """
    Résout une question en ResolvedQuery via LLM sémantique (V3.3-conforming).

    Pas de regex/keywords pour classifier (anti-pattern). Le LLM est l'unique
    classifieur. Filet de sécurité minimal si le LLM crash.
    """

    def __init__(
        self,
        vllm_url: Optional[str] = None,
        vllm_model: Optional[str] = None,
        timeout: float = 8.0,
    ):
        self.vllm_url = (vllm_url or VLLM_URL).rstrip("/")
        self.vllm_model = vllm_model or VLLM_MODEL
        self.timeout = timeout

    def resolve(self, query: str, persona_hints: Optional[dict] = None) -> ResolvedQuery:
        """Résout la query en ResolvedQuery."""
        clean = (query or "").strip()
        if not clean:
            return ResolvedQuery(
                raw_query=query,
                mode=ResponseMode.LOOKUP_FACTUAL,
                confidence=0.0,
                persona_hints=persona_hints or {},
                classifier_source="empty",
            )

        # Voie principale : LLM classifier sémantique
        try:
            llm_output = self._llm_classify(clean)
            return self._build_resolved(query, llm_output, persona_hints, source="llm")
        except Exception as e:
            logger.warning(f"[QueryResolver] LLM classification failed: {e}. Using safety fallback.")
            # Filet de sécurité : default LOOKUP_FACTUAL low confidence
            # Le runtime doit savoir que la classification n'est pas fiable.
            return ResolvedQuery(
                raw_query=query,
                mode=ResponseMode.LOOKUP_FACTUAL,
                confidence=0.3,  # explicite : on ne sait pas vraiment
                intent=None,
                persona_hints=persona_hints or {},
                classifier_source="fallback_safety",
            )

    # ------------------------------------------------------------------------
    # LLM classification
    # ------------------------------------------------------------------------

    def _llm_classify(self, query: str) -> dict:
        """Appel vLLM pour classification sémantique. Return dict parsed JSON."""
        # Replace plutôt que .format() pour ne pas échapper les { } du JSON sample
        prompt = PROMPT_CLASSIFY_MODE.replace("__QUESTION__", query)
        response = httpx.post(
            f"{self.vllm_url}/v1/chat/completions",
            json={
                "model": self.vllm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,  # déterministe pour classification
                "max_tokens": 300,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        # Cleanup éventuels markdown fences (pour modèles qui en ajoutent)
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        return json.loads(content)

    def _build_resolved(
        self,
        raw_query: str,
        llm_output: dict,
        persona_hints: Optional[dict],
        source: str,
    ) -> ResolvedQuery:
        """Construit la ResolvedQuery depuis l'output JSON du LLM."""
        # Mode (avec validation enum, fallback LOOKUP_FACTUAL si invalide)
        mode_str = (llm_output.get("mode") or "").strip().upper()
        try:
            mode = ResponseMode(mode_str)
        except ValueError:
            logger.warning(f"[QueryResolver] LLM returned invalid mode '{mode_str}', defaulting to LOOKUP_FACTUAL")
            mode = ResponseMode.LOOKUP_FACTUAL

        confidence = float(llm_output.get("confidence", 0.7) or 0.7)
        confidence = max(0.0, min(1.0, confidence))

        intent = llm_output.get("intent")
        entities = llm_output.get("entities") or []
        if not isinstance(entities, list):
            entities = []
        entities = [str(e) for e in entities[:5]]

        # Temporal anchor : LLM peut donner null
        temporal_anchor = self._parse_iso_date(llm_output.get("temporal_anchor"))

        # Temporal range : {"start": ..., "end": ...}
        temporal_range = None
        tr = llm_output.get("temporal_range")
        if isinstance(tr, dict):
            start = self._parse_iso_date(tr.get("start"))
            end = self._parse_iso_date(tr.get("end"))
            if start and end:
                temporal_range = (start, end)
            elif start:
                temporal_range = (start, date.today())

        return ResolvedQuery(
            raw_query=raw_query,
            mode=mode,
            confidence=confidence,
            intent=intent,
            entities=entities,
            temporal_anchor=temporal_anchor,
            temporal_range=temporal_range,
            persona_hints=persona_hints or {},
            classifier_source=source,
        )

    @staticmethod
    def _parse_iso_date(value) -> Optional[date]:
        """Parse une date ISO. Retourne None si invalide."""
        if not value or not isinstance(value, str):
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


__all__ = ["QueryResolver", "ResponseMode", "ResolvedQuery"]
