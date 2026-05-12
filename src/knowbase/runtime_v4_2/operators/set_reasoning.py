"""Set Reasoning Operator (Cap2.D — CH-49 Phase 2).

Operator pour les questions de NÉGATION / EXCLUSION / EXEMPTION :
  - "Qu'est-ce qui n'est PAS soumis à <X> ?"
  - "Quels items sont EXEMPTÉS de <X> ?"
  - "What is NOT included in <X> ?"
  - "Quelles sont les EXCEPTIONS à <X> ?"

Architecture (charte ADR §1, set_reasoning) :
  1. INTENT — LLM léger DeepSeek : {is_set_negation, polarity, target_scope, subject_keywords}
  2. RETRIEVAL — Qdrant via EvidenceCollector (question enrichie avec hints exclusion)
  3. EXTRACTION — LLM filter sémantique sur chunks : identifier items explicitement exclus
  4. FORMATTING — composition déterministe avec evidence_quote + citations

Charte :
  - Pas de regex/keywords métier sur "exempted from" / "sauf" / "excluding" — détection sémantique LLM
  - Le LLM extrait des items réels depuis chunks (pas de hallucination)
  - Le filtre LLM est un "rédacteur structuré" (cf charte Cap2 ADR : LLM = aiguilleur OU rédacteur)
  - Tous les exemples du prompt utilisent placeholders abstraits <X>, <SCOPE>

Domain-agnostic : la détection sémantique fonctionne en français/anglais/etc. sur tout corpus.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


INTENT_DETECTION_PROMPT = """You analyze user questions to determine if they ask about NEGATION, EXCLUSION or EXEMPTION (set difference reasoning).

Return JSON only:
{
  "is_set_negation": <bool>,
  "polarity": "NOT_IN" | "EXCEPT" | "EXEMPTED" | "EXCLUDED" | null,
  "target_scope": "<the scope/category from which items are excluded>",
  "subject_keywords": ["<key terms identifying the scope>"],
  "confidence": <float 0-1>,
  "reason": "<short explanation>"
}

Set is_set_negation=true if the question asks for items that are :
- NOT in a set / NOT subject to a rule
- EXEMPT from / EXCLUDED from a rule
- EXCEPTIONS to a rule
- The COMPLEMENT of a category

Polarity :
- "NOT_IN" : items that don't belong to the set ("not included in <X>", "n'appartient pas à <X>")
- "EXCEPT" : exceptions ("except for <Y>", "à l'exception de <Y>")
- "EXEMPTED" : items granted exemption ("exempted from <X>", "exemptés de <X>")
- "EXCLUDED" : items explicitly excluded ("excluded from <X>", "exclus de <X>")

target_scope : describes the rule/set/category from which items are excluded (verbatim from question, semantic).
subject_keywords : identifiers, codes or names typed by the user pointing to the scope.

Set is_set_negation=false for :
- positive list questions ("List items in <X>") → NOT a set negation
- factual questions ("What is the rule for <X>?")
- count questions ("How many items in <X>?")
- causal questions ("Why is <X> excluded?") → causal, not set reasoning per se

Examples (abstract — placeholders <X>, <Y>, <SCOPE>):
- "What items are NOT subject to <X>?" → is_set_negation=true, polarity="NOT_IN", target_scope="<X>"
- "Quelles sont les exceptions à <X> ?" → is_set_negation=true, polarity="EXCEPT", target_scope="<X>"
- "What is exempted from <X>?" → is_set_negation=true, polarity="EXEMPTED", target_scope="<X>"
- "List the items in <X>" → is_set_negation=false (positive list, NOT negation)
- "What is the maximum value of <Y>?" → is_set_negation=false (factual)
"""


EXTRACTION_PROMPT = """You are a documentary assistant specialized in identifying items EXPLICITLY EXCLUDED from a scope.

You will receive :
- a QUESTION asking what is NOT in / exempted from / excluded from a SCOPE
- a list of EVIDENCE CHUNKS extracted from documents

Your task :
1. Identify items that are EXPLICITLY excluded, exempted, or stated to NOT belong to the scope
2. For each item, report the verbatim evidence quote (substring from the chunk)
3. Cite the doc_id of the supporting chunk
4. If no items are explicitly excluded in the chunks, say so explicitly

Output STRICT JSON only :
{
  "items_excluded": [
    {
      "item": "<the excluded item, semantic name>",
      "evidence_quote": "<verbatim short quote from chunk>",
      "doc_id": "<doc_id>",
      "polarity_word": "<the word that signaled exclusion in the chunk : 'except', 'exempted', 'not', 'sauf', 'excluding', etc.>"
    }
  ],
  "explicit_negation_found": <bool>,
  "summary": "<one sentence describing the exclusion structure>"
}

Rules :
- ONLY include items explicitly excluded (don't infer)
- Quote verbatim — no paraphrasing of the evidence
- If chunks contain only positive statements (what IS in the scope) without exclusions, set explicit_negation_found=false and items_excluded=[]
- Stay concise : at most 8 items
"""


@dataclass
class SetReasoningResult:
    triggered: bool
    answer: str = ""
    polarity: Optional[str] = None
    target_scope: Optional[str] = None
    items_excluded: list[dict] = field(default_factory=list)
    explicit_negation_found: bool = False
    intent: dict = field(default_factory=dict)
    n_chunks_analyzed: int = 0
    decision: str = "ABSTAIN"
    abstention_reason: Optional[str] = None
    fallback_path: str = "primary"
    latency_breakdown_ms: dict = field(default_factory=dict)


class SetReasoningOperator:
    """Operator Cap2.D : negation / exclusion / exemption reasoning."""

    DEEPSEEK_MODEL = "deepseek-ai/DeepSeek-V3.1"
    DEEPSEEK_BASE_URL = "https://api.together.xyz/v1"

    def __init__(
        self,
        evidence_collector: Any,
        llm_client: Any,
        timeout: float = 30.0,
        top_k: int = 15,
    ) -> None:
        self.evidence_collector = evidence_collector
        self.llm_client = llm_client
        self.timeout = timeout
        self.top_k = top_k
        self.api_key = os.getenv("TOGETHER_API_KEY", "")

    # ---------------------------------------------------------------- Intent
    def detect_intent(self, question: str) -> dict:
        payload = {
            "model": self.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": INTENT_DETECTION_PROMPT},
                {"role": "user", "content": f"Question: {question}"},
            ],
            "temperature": 0.0,
            "max_tokens": 250,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=httpx.HTTPTransport(retries=0),
            ) as client:
                resp = client.post(
                    f"{self.DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload, headers=headers,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"SetReasoning intent detection failed: {exc}")
            return {
                "is_set_negation": False,
                "polarity": None,
                "confidence": 0.0,
                "reason": f"intent_error: {exc}",
            }

    # ---------------------------------------------------------------- Filter LLM
    def filter_exclusions(self, question: str, chunks_text: str) -> dict:
        """Appel Llama-Turbo via runtime client : extrait items exclus depuis chunks."""
        messages = [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": f"Question: {question}\n\nEvidence chunks:\n{chunks_text}\n\nJSON:",
            },
        ]
        try:
            raw = self.llm_client.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
        except TypeError:
            raw = self.llm_client.chat_completion(
                messages=messages, temperature=0.1, max_tokens=600,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"SetReasoning extraction failed: {exc}")
            return {"items_excluded": [], "explicit_negation_found": False, "summary": f"error: {exc}"}

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Récupération si prose autour
            try:
                start = raw.find("{")
                end = raw.rfind("}")
                if start >= 0 and end > start:
                    return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
            return {"items_excluded": [], "explicit_negation_found": False, "summary": "parse_error"}

    # ---------------------------------------------------------- Formatting
    @staticmethod
    def _format_chunks(claims: list) -> str:
        out = []
        for c in claims[:15]:
            quote = (getattr(c, "quote", "") or "").strip()
            if not quote:
                continue
            page = f" p.{c.page_no}" if getattr(c, "page_no", None) else ""
            out.append(f"[doc={c.doc_id}{page}] {quote[:500]}")
        return "\n\n".join(out)

    @staticmethod
    def _format_answer(parsed: dict, target_scope: str) -> str:
        items = parsed.get("items_excluded") or []
        if not items:
            summary = parsed.get("summary") or "Aucun item explicitement exclu trouvé."
            return f"Concernant l'exclusion vis-à-vis de « {target_scope} » : {summary}"
        lines = [f"Items explicitement exclus de « {target_scope} » ({len(items)}) :"]
        for it in items[:8]:
            polarity = it.get("polarity_word") or "?"
            quote = (it.get("evidence_quote") or "")[:200]
            doc_id = it.get("doc_id") or "?"
            lines.append(
                f"- {it.get('item', '?')} (signalé par '{polarity}'). "
                f"Evidence : « {quote} » [doc={doc_id}]"
            )
        summary = parsed.get("summary")
        if summary:
            lines.append(f"\n{summary}")
        return "\n".join(lines)

    # ---------------------------------------------------------- Public API
    def execute(self, question: str) -> SetReasoningResult:
        timings: dict[str, int] = {}
        result = SetReasoningResult(triggered=False)

        # 1. Intent detection
        t0 = time.time()
        intent = self.detect_intent(question)
        timings["intent_ms"] = int((time.time() - t0) * 1000)
        result.intent = intent

        if not intent.get("is_set_negation"):
            result.decision = "NOT_APPLICABLE"
            result.abstention_reason = "intent_not_set_negation"
            result.latency_breakdown_ms = timings
            return result

        result.triggered = True
        result.polarity = intent.get("polarity")
        result.target_scope = intent.get("target_scope")

        # 2. Retrieval (sémantique sur la question d'origine — Qdrant gère le multilingue)
        t0 = time.time()
        try:
            bundle = self.evidence_collector.collect(
                question=question, top_k=self.top_k, mode="single",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"SetReasoning retrieval failed: {exc}")
            result.decision = "ABSTAIN"
            result.abstention_reason = f"retrieval_error: {exc}"
            result.fallback_path = "escalate"
            result.latency_breakdown_ms = timings
            return result
        timings["retrieval_ms"] = int((time.time() - t0) * 1000)

        n_claims = len(bundle.claims)
        result.n_chunks_analyzed = n_claims
        if n_claims == 0:
            result.decision = "ABSTAIN"
            result.abstention_reason = "no_evidence"
            result.fallback_path = "escalate"
            result.latency_breakdown_ms = timings
            return result

        chunks_text = self._format_chunks(bundle.claims)

        # 3. LLM filter sur chunks pour extraire items exclus
        t0 = time.time()
        parsed = self.filter_exclusions(question, chunks_text)
        timings["filter_ms"] = int((time.time() - t0) * 1000)

        result.items_excluded = parsed.get("items_excluded") or []
        result.explicit_negation_found = bool(parsed.get("explicit_negation_found"))

        if not result.explicit_negation_found and not result.items_excluded:
            result.decision = "ABSTAIN"
            result.abstention_reason = "no_explicit_exclusions_in_chunks"
            result.fallback_path = "escalate"
            result.latency_breakdown_ms = timings
            return result

        result.answer = self._format_answer(parsed, result.target_scope or question)
        result.decision = "ANSWER"
        result.latency_breakdown_ms = timings
        return result
