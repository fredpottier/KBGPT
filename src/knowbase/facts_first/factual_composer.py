"""
OSMOSIS V4 — FactualComposer (CH-41 Tranche 2 factual).

Transforme un `facts_first_v1` factual JSON en prose courte avec sentence_support.
Le LLM est cantonné au formatage (D-FF4).

Pour factual single-fact, la réponse est typiquement 1-2 phrases :
  "Le règlement (UE) 2021/821 a été adopté le 20 mai 2021."

Si plusieurs facts (factual avec qualifiers ou multi-attribut), la réponse peut
contenir 2-4 phrases.

Output identique à ListComposer pour cohérence schéma :
{"answer_text", "sentence_support", "language", "format": "factual_prose"}
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from knowbase.runtime_v3.llm_client import RuntimeLLMClient, get_runtime_llm_client

logger = logging.getLogger(__name__)


DEFAULT_COMPOSER_MODEL = os.getenv("FACTUAL_COMPOSER_MODEL", "google/gemma-3-12b-it")


SYSTEM_PROMPT = """You are a presentation-only component for factual answers. You receive a STRUCTURED set of facts already extracted, and produce a clean concise prose answer that:
1. Uses the facts VERBATIM — never modify object.raw, never add information beyond the facts.
2. Cites each fact by its fact_id in the sentence_support array.
3. Matches the requested response language.
4. Stays SHORT : 1-2 sentences for a single-fact answer, max 4 sentences for multi-fact.

Output JSON ONLY:
{
  "answer_text": "<short prose, no bullets unless multiple facts justify it>",
  "sentence_support": [
    {"sentence_index": 0, "text": "<sentence>", "support_ids": ["F1", ...]},
    ...
  ]
}

Rules:
- The answer should DIRECTLY answer the question using the values from object.raw of the direct_answer_fact_ids.
- If facts is empty: answer_text is exactly "La réponse à votre question n'a pas été trouvée dans les documents disponibles." (or English equivalent if language=en).
- DO NOT add caveats, hedging, or "based on the provided information" unless the diagnostic.fallback_mode signals a conflict.
- If diagnostic.fallback_mode == "factual_simple_conflict_suspected", honestly mention both source values without preferring one."""


@dataclass
class ComposerResult:
    answer_text: str
    sentence_support: list[dict]
    language: str = "en"
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    raw_llm_output: str = ""
    parse_error: Optional[str] = None
    format: str = "factual_prose"

    def to_dict(self) -> dict:
        return {
            "answer_text": self.answer_text,
            "sentence_support": self.sentence_support,
            "language": self.language,
            "format": self.format,
        }


class FactualComposer:
    def __init__(
        self,
        llm: Optional[RuntimeLLMClient] = None,
        temperature: float = 0.05,
        max_tokens: int = 800,
        timeout: float = 60.0,
        model_override: Optional[str] = None,
    ) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.model_override = model_override or DEFAULT_COMPOSER_MODEL

    def compose(self, facts_first: dict) -> ComposerResult:
        t0 = time.time()
        language = (facts_first.get("language") or "en").lower()
        factual_specific = facts_first.get("factual_specific") or {}
        facts = factual_specific.get("facts") or []
        direct_ids = factual_specific.get("direct_answer_fact_ids") or []
        diagnostic = facts_first.get("diagnostic") or {}

        if not facts:
            msg = self._abstention_message(language)
            return ComposerResult(
                answer_text=msg,
                sentence_support=[{"sentence_index": 0, "text": msg, "support_ids": []}],
                language=language,
                latency_ms=int((time.time() - t0) * 1000),
                model="deterministic", provider="local",
            )

        # Compact facts for LLM
        facts_compact = [
            {
                "fact_id": f["fact_id"],
                "subject": f["subject"],
                "predicate": f["predicate"],
                "object_raw": f["object"]["raw"],
                "object_kind": f["object"].get("kind"),
                "object_unit": f["object"].get("unit"),
                "qualifiers": {k: v for k, v in (f.get("qualifiers") or {}).items() if v},
            }
            for f in facts
        ]
        user_prompt = (
            f"LANGUAGE: {language}\n"
            f"DIRECT_ANSWER_FACT_IDS: {direct_ids}\n"
            f"FALLBACK_MODE: {diagnostic.get('fallback_mode') or 'none'}\n"
            f"FACTS:\n{json.dumps(facts_compact, ensure_ascii=False, indent=2)}\n\n"
            "Compose a short factual answer. Output JSON only."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            meta = self.llm.chat_completion_with_meta(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                json_mode=True,
                timeout=self.timeout,
                model_override=self.model_override,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("FactualComposer LLM failed: %s — fallback deterministic", exc)
            return self._fallback_deterministic(facts, direct_ids, language, t0, parse_error=str(exc))

        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._fallback_deterministic(facts, direct_ids, language, t0, parse_error=f"json_parse: {exc}")

        answer = str(parsed.get("answer_text") or "").strip()
        ss = parsed.get("sentence_support") or []
        if not answer or not isinstance(ss, list):
            return self._fallback_deterministic(facts, direct_ids, language, t0, parse_error="missing_fields")

        clean_ss = []
        for i, s in enumerate(ss):
            if not isinstance(s, dict):
                continue
            text = str(s.get("text") or "").strip()
            if not text:
                continue
            sids = [str(x) for x in (s.get("support_ids") or []) if isinstance(x, (str, int))]
            clean_ss.append({"sentence_index": int(s.get("sentence_index", i)), "text": text, "support_ids": sids})

        return ComposerResult(
            answer_text=answer,
            sentence_support=clean_ss,
            language=language,
            latency_ms=int((time.time() - t0) * 1000),
            model=meta.get("model", ""),
            provider=meta.get("provider", ""),
            raw_llm_output=raw[:600],
        )

    def _fallback_deterministic(
        self, facts: list[dict], direct_ids: list[str], language: str, t0: float, parse_error: Optional[str]
    ) -> ComposerResult:
        """Fallback : phrase déterministe par fact (subject + predicate + object.raw)."""
        sentences = []
        ss = []
        # Priorité aux direct_answer_fact_ids
        ordered_facts = [f for f in facts if f["fact_id"] in (direct_ids or [])] + [
            f for f in facts if f["fact_id"] not in (direct_ids or [])
        ]
        for f in ordered_facts:
            obj_raw = f["object"]["raw"]
            unit = f["object"].get("unit") or ""
            obj_str = f"{obj_raw} {unit}".strip() if unit else obj_raw
            sentence = f"{f['subject']} {f['predicate']} {obj_str}.".replace("  ", " ")
            sentences.append(sentence)
            ss.append({"sentence_index": len(sentences) - 1, "text": sentence, "support_ids": [f["fact_id"]]})
        answer = " ".join(sentences)
        return ComposerResult(
            answer_text=answer,
            sentence_support=ss,
            language=language,
            latency_ms=int((time.time() - t0) * 1000),
            model="deterministic", provider="local",
            parse_error=parse_error,
        )

    @staticmethod
    def _abstention_message(language: str) -> str:
        if language.startswith("fr"):
            return "La réponse à votre question n'a pas été trouvée dans les documents disponibles."
        return "The answer to your question was not found in the available documents."


_default: Optional[FactualComposer] = None


def get_factual_composer() -> FactualComposer:
    global _default
    if _default is None:
        _default = FactualComposer()
    return _default


def reset_factual_composer() -> None:
    global _default
    _default = None
