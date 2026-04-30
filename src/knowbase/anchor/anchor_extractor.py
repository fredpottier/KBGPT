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


SYSTEM_PROMPT = """You are a question analyst extracting an "anchor" from a user's question. The anchor describes the temporal/scope frame within which the question expects to be answered, based on documents from a knowledge base.

There are exactly three possible anchor types:

## CURRENT_DEFAULT
The question has NO explicit temporal or scope qualifier. The user expects the answer for the CURRENT/MOST RECENT applicable state.
Examples (across languages and domains):
- "What is the data encryption mode at rest of S/4HANA Cloud Private Edition?"
- "Quel est le mode de chiffrement au repos de S/4HANA Cloud ?"
- "What dosage is recommended for biomarker X?"
- "Was ist die Standardkonfiguration für Modul Y?"

## POINT
The question explicitly targets ONE specific frame (one version, one date, one release, one document edition). Look for explicit identifiers like version numbers, release codes, dates, edition labels.
Examples:
- "Which APIs are available in S/4HANA 1809?"  → POINT, version=1809
- "What did the standard say in 2018?"          → POINT, date=2018
- "Quelles règles dans CS-25 Amendment 27 ?"   → POINT, version=Amendment 27
- "Document edition 3.2 specifies what about X?" → POINT, version=3.2

## RANGE
The question targets a SPAN of frames — explicitly or implicitly. The user wants evolution / history / comparison.
Examples:
- "How did encryption evolve between 2018 and 2024?"  → RANGE, range_start=2018, range_end=2024
- "Comment cette disposition a évolué dans la réglementation ?" → RANGE, no explicit bounds (full history)
- "List all dosage recommendations since the biomarker was first used." → RANGE, no explicit bounds
- "Compare APIs of S/4HANA 1809 and 2023."  → RANGE, range_start=1809, range_end=2023
- "What changed between version A and version B?" → RANGE, range_start=A, range_end=B

## Critical extraction rules

1. **Output JSON ONLY** matching exactly this schema:
```
{
  "anchor_type": "point" | "range" | "current_default",
  "scope": {
    "version": "<verbatim version/release/edition identifier>" | null,
    "date": "<ISO-like date if explicit>" | null,
    "range_start": "<verbatim start identifier>" | null,
    "range_end": "<verbatim end identifier>" | null,
    "extraction_evidence": "<verbatim fragment of the question proving the anchor>" | null
  },
  "confidence": 0.0-1.0,
  "reasoning": "<brief reason>"
}
```

2. **`extraction_evidence` is MANDATORY for POINT and RANGE**. It MUST be a verbatim substring of the user's question — no paraphrasing. The validator will reject the extraction if the evidence is not found verbatim. For CURRENT_DEFAULT it MUST be null.

3. **For RANGE, fill range_start and range_end if explicitly cited**. If the user asks for full history without bounds ("since when", "how has X evolved", "depuis", "throughout"), leave both null but still set anchor_type=range.

4. **Do NOT infer beyond what the question states**. If the question is ambiguous between current_default and a vaguely implied frame, prefer current_default.

5. **Identifiers can be ANY format** (version numbers, release codes, dates, amendment numbers, edition labels, semantic versions, named milestones). Capture them verbatim — no normalization, no domain assumption.

6. **Multilingual**: apply the same logic regardless of question language."""


class AnchorExtractor:
    """LLM Anchor Extractor evidence-locked.

    Usage:
        extractor = AnchorExtractor(vllm_url="http://x.y.z.w:8000")
        anchor = extractor.extract("What is encryption mode of S/4HANA?")
        # → ResolvedAnchor(anchor_type=CURRENT_DEFAULT, scope=AnchorScope(...), confidence=...)
    """

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

    def extract(self, question: str) -> ResolvedAnchor:
        """Extrait l'anchor d'une question.

        Returns un ResolvedAnchor avec extraction_method indiquant le succès du
        validator evidence-locked. Si la quote LLM n'est pas dans la question
        (hallucination), on dégrade en current_default avec confidence basse —
        plutôt que d'inventer un anchor à partir d'une evidence fabriquée.
        """
        raw_json = self._call_llm(question)
        anchor = self._parse_response(raw_json)

        # Validator evidence-locked
        validated = self._validate_evidence(anchor, question)
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
