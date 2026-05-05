"""
LLM Anchor Extractor — V2-S2.

Extrait l'anchor (point | range | current_default) depuis une question utilisateur.

Conformément à VISION_RECENTREE §1bis et §4.1 :
- Sémantique pur : aucun regex, aucun keyword (anti-pattern V3.3 §0)
- Evidence-locked : extraction_evidence doit être substring de la question
- Multilingue par construction (Qwen2.5-14B AWQ)
- Domain-agnostic : pas de listes de versions/produits/identifiants
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

import httpx

from knowbase.anchor.models import (
    AnchorScope,
    AnchorType,
    ResolvedAnchor,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Extract a temporal/scope anchor from a user question. Domain-agnostic, multilingual.

Anchor types :
- current_default : no explicit temporal/scope qualifier (user wants the current state)
- point : ONE explicit frame (version, date, release, edition) — capture the identifier verbatim
- range : SPAN of frames or evolution/history/comparison request

Output STRICT JSON ONLY :
{
  "anchor_type": "current_default" | "point" | "range",
  "scope": {
    "version": "<verbatim id>" | null,
    "date": "<ISO date>" | null,
    "range_start": "<verbatim start>" | null,
    "range_end": "<verbatim end>" | null,
    "extraction_evidence": "<verbatim substring of the question>" | null
  },
  "confidence": 0.0-1.0,
  "reasoning": "<brief>"
}

Rules :
- extraction_evidence MUST be a verbatim substring of the question for point/range. null for current_default.
- For range with no explicit bounds (e.g. "since", "how did X evolve", "throughout"), keep range_start/end null.
- When ambiguous, prefer current_default.
- Capture identifiers verbatim (version numbers, dates, amendment names, edition labels, semantic versions).
- Multilingual : same logic in any language."""


class AnchorExtractor:
    """LLM Anchor Extractor evidence-locked.

    Usage:
        extractor = AnchorExtractor(vllm_url="http://x.y.z.w:8000")
        anchor = extractor.extract("What is encryption mode of S/4HANA?")
        # → ResolvedAnchor(anchor_type=CURRENT_DEFAULT, scope=AnchorScope(...), confidence=...)
    """

    # CH-33 — cache LRU partagé (instance-agnostic, basé sur la question seule)
    _CACHE: "OrderedDict[str, ResolvedAnchor]" = None  # init lazy
    _CACHE_MAX = 256

    def __init__(
        self,
        vllm_url: str,
        model_id: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
        timeout: float = 120.0,
        temperature: float = 0.1,
        max_tokens: int = 400,
    ) -> None:
        self.vllm_url = vllm_url.rstrip("/")
        self.model_id = model_id
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        if AnchorExtractor._CACHE is None:
            from collections import OrderedDict
            AnchorExtractor._CACHE = OrderedDict()

    @staticmethod
    def _cache_key(question: str) -> str:
        import hashlib
        return hashlib.sha1(question.strip().lower().encode("utf-8")).hexdigest()

    def extract(self, question: str) -> ResolvedAnchor:
        """Extrait l'anchor d'une question.

        Returns un ResolvedAnchor avec extraction_method indiquant le succès du
        validator evidence-locked. Si la quote LLM n'est pas dans la question
        (hallucination), on dégrade en current_default avec confidence basse —
        plutôt que d'inventer un anchor à partir d'une evidence fabriquée.

        CH-33 : cache LRU sur la question.
        """
        ck = self._cache_key(question)
        cache = AnchorExtractor._CACHE
        if cache is not None:
            cached = cache.get(ck)
            if cached is not None:
                cache.move_to_end(ck)
                logger.info("[ANCHOR_EXTRACT] cache HIT (%s...)", ck[:12])
                return cached

        raw_json = self._call_llm(question)
        anchor = self._parse_response(raw_json)

        # Validator evidence-locked
        validated = self._validate_evidence(anchor, question)

        if cache is not None:
            cache[ck] = validated
            if len(cache) > AnchorExtractor._CACHE_MAX:
                cache.popitem(last=False)
        return validated

    def _call_llm(self, question: str) -> str:
        """Appel via RuntimeLLMClient (vLLM si actif, sinon DeepInfra)."""
        user_prompt = (
            "Extract the anchor from this question. Output JSON only, no commentary.\n\n"
            f"Question: {question}"
        )
        try:
            from knowbase.runtime_v2.llm_client import get_runtime_llm_client
            client = get_runtime_llm_client()
            return client.chat_completion(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                json_mode=True,
                timeout=self.timeout,
                model_override="mistralai/Mistral-Small-3.1-24B-Instruct-2503",
            )
        except Exception as exc:
            logger.error("AnchorExtractor LLM call failed: %s", exc)
            return '{"anchor_type": "current_default", "scope": {}, "confidence": 0.0, "reasoning": "LLM call failed, fallback safety"}'

    def _parse_response(self, raw_json: str) -> ResolvedAnchor:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.warning("AnchorExtractor returned invalid JSON: %s", exc)
            return ResolvedAnchor(
                anchor_type=AnchorType.CURRENT_DEFAULT,
                scope=AnchorScope(),
                confidence=0.0,
                reasoning="LLM returned invalid JSON",
                extraction_method="llm_evidence_locked_v2_s2_fallback_invalid_json",
                model_id=self.model_id,
            )

        try:
            scope_data = data.get("scope", {}) or {}
            scope = AnchorScope(
                version=scope_data.get("version"),
                date=scope_data.get("date"),
                range_start=scope_data.get("range_start"),
                range_end=scope_data.get("range_end"),
                extraction_evidence=scope_data.get("extraction_evidence"),
            )
            anchor = ResolvedAnchor(
                anchor_type=AnchorType(data.get("anchor_type", "current_default")),
                scope=scope,
                confidence=float(data.get("confidence", 0.0)),
                reasoning=data.get("reasoning"),
                extraction_method="llm_evidence_locked_v2_s2",
                model_id=self.model_id,
            )
            return anchor
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("AnchorExtractor parse error: %s (data=%s)", exc, data)
            return ResolvedAnchor(
                anchor_type=AnchorType.CURRENT_DEFAULT,
                scope=AnchorScope(),
                confidence=0.0,
                reasoning=f"Parse error: {exc}",
                extraction_method="llm_evidence_locked_v2_s2_fallback_parse_error",
                model_id=self.model_id,
            )

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalise pour comparaison robuste (whitespace collapse + lowercase)."""
        return re.sub(r"\s+", " ", text).strip().lower()

    def _validate_evidence(
        self, anchor: ResolvedAnchor, question: str
    ) -> ResolvedAnchor:
        """Valide que extraction_evidence est substring de la question.

        Si extraction_evidence est requise (POINT ou RANGE) et pas trouvée,
        on dégrade vers CURRENT_DEFAULT avec confidence 0 (refuse de mentir).
        """
        if anchor.anchor_type == AnchorType.CURRENT_DEFAULT:
            # Pour CURRENT_DEFAULT, extraction_evidence DOIT être null
            if anchor.scope.extraction_evidence:
                logger.debug(
                    "CURRENT_DEFAULT but extraction_evidence non-null — clearing"
                )
                anchor.scope.extraction_evidence = None
            return anchor

        # POINT / RANGE → extraction_evidence obligatoire et substring de la question
        evidence = anchor.scope.extraction_evidence
        if not evidence:
            logger.warning(
                "%s requires extraction_evidence but none provided — degrading to CURRENT_DEFAULT",
                anchor.anchor_type.value,
            )
            return ResolvedAnchor(
                anchor_type=AnchorType.CURRENT_DEFAULT,
                scope=AnchorScope(),
                confidence=0.0,
                reasoning=f"Original anchor was {anchor.anchor_type.value} but had no evidence — rejected",
                extraction_method="llm_evidence_locked_v2_s2_rejected_no_evidence",
                model_id=self.model_id,
            )

        if self._normalize(evidence) not in self._normalize(question):
            logger.warning(
                "Evidence quote not in question: '%s' not in '%s' — degrading",
                evidence,
                question,
            )
            return ResolvedAnchor(
                anchor_type=AnchorType.CURRENT_DEFAULT,
                scope=AnchorScope(),
                confidence=0.0,
                reasoning=f"extraction_evidence '{evidence}' is not a substring of the question",
                extraction_method="llm_evidence_locked_v2_s2_rejected_evidence_not_in_question",
                model_id=self.model_id,
            )

        return anchor
