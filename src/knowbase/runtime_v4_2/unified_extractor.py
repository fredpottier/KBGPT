"""Unified prompt extract + intent + Q↔A self-check (Amendment 7).

1 seul appel Llama-3.3-70B-Turbo produit JSON contenant :
  - extracted_answer (avec citations [doc=...])
  - intent_scores (heuristique routing operators Cap2)
  - qa_alignment self-check (decision + confidence)

Rationale (Claude Web Amendment 7) : économise 1 round-trip QA Verifier sur les
cas haute-confiance, ramène la latence Layer 0 ~5-10s → 3-5s en cas optimal.

Garde-fou anti-biais auto-juge : si confidence < threshold, on FORCE un fallback
DeepSeek-V3.1 verifier externe (cohérence ADR §0 anti-biais Verifier ≠ Composer).
Cible production : 60-80% des cas skip le DeepSeek call, 20-40% le forcent.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from knowbase.runtime_v4_2.models import UnifiedExtractionResult

logger = logging.getLogger(__name__)


UNIFIED_PROMPT = """You are a documentary assistant. You will produce a single JSON object containing :
1. The factual answer extracted from evidence (with citations)
2. A semantic alignment self-check (does your answer address the question?)
3. Intent scores for downstream routing decisions

Rules :
- Use ONLY the evidence chunks provided. Never fabricate facts.
- Always include [doc=ID] citations when claiming a fact.
- If chunks don't contain the answer, set "extracted_answer" to "La reponse a votre question n'a pas ete trouvee dans les documents disponibles." and qa_alignment.decision = "ABSTAIN_OK".
- Stay concise: 1-3 sentences max in extracted_answer.
- The qa_alignment self-check evaluates whether your answer addresses the question's facet/topic/angle (NOT factual correctness).
- intent_scores : score 0..1 the likelihood that this question requires each downstream operator. Be generous on candidates (multi-label).

Output STRICT JSON only, no prose around it :
{
  "extracted_answer": "<concise answer with [doc=...] citations OR explicit not-found marker>",
  "qa_alignment": {
    "decision": "ALIGNED" | "MISALIGNED" | "ABSTAIN_OK",
    "reason": "<one short sentence>",
    "confidence": <float 0..1>
  },
  "intent_scores": {
    "temporal_active_version": <0..1>,
    "lifecycle_resolution": <0..1>,
    "kg_query": <0..1>,
    "set_reasoning": <0..1>,
    "comparison_contradiction": <0..1>,
    "needs_layer2_orchestrator": <0..1>
  }
}"""


# Confidence threshold sous lequel on force le DeepSeek verifier externe
# (anti-biais auto-juge — ADR §0).
DEFAULT_CONFIDENCE_THRESHOLD = 0.85


class UnifiedExtractor:
    """Extracteur unifié : 1 call Llama-Turbo produit answer + qa_check + intent.

    Reuse RuntimeLLMClient (vLLM-first → DeepInfra/Together fallback selon config).
    """

    def __init__(
        self,
        llm_client: Any,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.llm_client = llm_client
        self.confidence_threshold = float(
            os.getenv(
                "RUNTIME_V4_2_UNIFIED_CONFIDENCE_THRESHOLD",
                str(confidence_threshold),
            )
        )

    def extract(self, question: str, chunks_text: str) -> UnifiedExtractionResult:
        """1 call Llama-Turbo. Si parse fail OU confidence < threshold → needs_external_verifier=True."""
        messages = [
            {"role": "system", "content": UNIFIED_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\nEvidence chunks:\n{chunks_text}\n\nJSON:"
                ),
            },
        ]

        try:
            raw = self.llm_client.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=700,
                response_format={"type": "json_object"},
            )
        except TypeError:
            # Fallback si le client ne supporte pas response_format
            raw = self.llm_client.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=700,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"UnifiedExtractor LLM call failed: {exc}")
            return self._error_fallback(reason=f"llm_error: {exc}")

        parsed = self._parse_json(raw)
        if parsed is None:
            return self._error_fallback(reason="json_parse_error", raw_response={"raw": raw[:1000]})

        extracted_answer = str(parsed.get("extracted_answer", "")).strip()
        qa = parsed.get("qa_alignment") or {}
        decision = str(qa.get("decision", "ALIGNED"))
        reason = str(qa.get("reason", ""))
        try:
            confidence = float(qa.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        intent = parsed.get("intent_scores") or {}
        intent_scores = {k: self._to_float(v) for k, v in intent.items() if isinstance(k, str)}

        # Anti-biais : si confidence faible OU décision MISALIGNED → forcer external verifier
        needs_external = (
            confidence < self.confidence_threshold
            or decision.upper() == "MISALIGNED"
        )

        return UnifiedExtractionResult(
            extracted_answer=extracted_answer or "(empty extraction)",
            qa_alignment=decision.upper(),
            qa_reason=reason,
            qa_confidence=confidence,
            intent_scores=intent_scores,
            needs_external_verifier=needs_external,
            raw_response=parsed,
        )

    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Tentative de récupération si le LLM a inclus du prose autour du JSON
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
        return None

    @staticmethod
    def _to_float(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _error_fallback(reason: str, raw_response: Optional[dict] = None) -> UnifiedExtractionResult:
        return UnifiedExtractionResult(
            extracted_answer="(unified extraction failed)",
            qa_alignment="MISALIGNED",
            qa_reason=reason,
            qa_confidence=0.0,
            intent_scores={},
            needs_external_verifier=True,  # Force fallback DeepSeek
            raw_response=raw_response or {},
        )
