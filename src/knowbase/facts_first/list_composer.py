"""
OSMOSIS V4 — ListComposer (composant [D], CH-41.3, Tranche 1 list).

Transforme un `facts_first_v1` JSON list en prose user-facing avec
`sentence_support[support_ids[]]`. Le LLM est ici cantonné au FORMATAGE
(D-FF4) — il ne peut pas inventer un item ni modifier le label.

Output :
{
  "answer_text": "<final prose to display>",
  "sentence_support": [
    {"sentence_index": 0, "text": "...", "support_ids": ["I1", "I2"]},
    ...
  ],
  "language": "<iso>",
  "format": "list_prose"
}

Si items=[] → answer_text est un message d'abstention ("La réponse à votre question
n'a pas été trouvée dans les documents disponibles.") avec sentence_support vide.
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

# CH-41.4 optim — Composer ne fait que du formatage : un modèle 12B suffit et
# tourne 2.8× plus vite que Qwen2.5-72B (bench 2026-05-06 : 8.9s vs 18.9s mean,
# verifier 100% sur les 2). Override via env LIST_COMPOSER_MODEL.
DEFAULT_COMPOSER_MODEL = os.getenv("LIST_COMPOSER_MODEL", "google/gemma-3-12b-it")


SYSTEM_PROMPT = """You are a presentation-only component. You receive a STRUCTURED LIST of items already extracted, and produce a clean prose answer that:
1. Uses the items VERBATIM — no rewording of `label`, no addition, no removal.
2. Cites each item by its `item_id` in the sentence_support array.
3. Matches the requested response language.
4. Never adds factual content beyond the structured input.

Output JSON ONLY:
{
  "answer_text": "<the final prose, possibly with a short intro and a bulleted/numbered list using the labels>",
  "sentence_support": [
    {"sentence_index": 0, "text": "<sentence 1>", "support_ids": ["I1", "I2", ...]},
    ...
  ]
}

Rules:
- sentence_index is 0-based. Each sentence in answer_text gets one entry.
- support_ids list every item_id whose `label` is mentioned in that sentence (even partially).
- If items is empty, answer_text is exactly: "La réponse à votre question n'a pas été trouvée dans les documents disponibles." (or English equivalent if language=en).
- Do NOT modify item labels; you may translate connectors and intro text but the labels stay verbatim.
- Format: a short intro sentence + a numbered/bulleted list."""


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
    format: str = "list_prose"

    def to_dict(self) -> dict:
        return {
            "answer_text": self.answer_text,
            "sentence_support": self.sentence_support,
            "language": self.language,
            "format": self.format,
        }


class ListComposer:
    def __init__(
        self,
        llm: Optional[RuntimeLLMClient] = None,
        temperature: float = 0.05,
        max_tokens: int = 1200,  # CH-46 L6 : 1500→1200
        timeout: float = 60.0,
        model_override: Optional[str] = None,
    ) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        # CH-41.4 optim — modèle plus rapide pour le formatage (Gemma-3-12b-it)
        self.model_override = model_override or DEFAULT_COMPOSER_MODEL

    def compose(self, facts_first: dict) -> ComposerResult:
        """Compose la prose à partir d'un facts_first_v1 list."""
        t0 = time.time()
        language = (facts_first.get("language") or "en").lower()
        list_specific = facts_first.get("list_specific") or {}
        items = list_specific.get("items") or []
        list_subject = list_specific.get("list_subject") or "items"

        # Cas vide : réponse d'abstention déterministe (pas de LLM)
        if not items:
            msg = self._abstention_message(language)
            return ComposerResult(
                answer_text=msg,
                sentence_support=[{"sentence_index": 0, "text": msg, "support_ids": []}],
                language=language,
                latency_ms=int((time.time() - t0) * 1000),
                model="deterministic",
                provider="local",
            )

        # Préparer la structure passée au LLM (réduction)
        items_compact = [
            {"item_id": it["item_id"], "label": it["label"], "item_type": it.get("item_type", "unknown")}
            for it in items
        ]
        user_prompt = (
            f"LANGUAGE: {language}\n"
            f"LIST_SUBJECT: {list_subject}\n"
            f"COVERAGE_STATE: {(list_specific.get('enumeration_quality') or {}).get('coverage_state', 'unknown')}\n"
            f"ITEMS:\n{json.dumps(items_compact, ensure_ascii=False, indent=2)}\n\n"
            "Compose a clean prose answer. Output JSON only."
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
            logger.warning("ListComposer LLM failed: %s — falling back to deterministic", exc)
            return self._fallback_deterministic(items, list_subject, language, t0, parse_error=str(exc))

        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._fallback_deterministic(items, list_subject, language, t0, parse_error=f"json_parse: {exc}")

        answer = str(parsed.get("answer_text") or "").strip()
        ss = parsed.get("sentence_support") or []
        if not answer or not isinstance(ss, list):
            return self._fallback_deterministic(items, list_subject, language, t0, parse_error="missing_fields")

        # Sanitize sentence_support
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
        self, items: list[dict], list_subject: str, language: str, t0: float, parse_error: Optional[str]
    ) -> ComposerResult:
        """Fallback déterministe : intro + bullet list utilisant les labels verbatim."""
        intro = (
            f"Les {list_subject} suivants ont été identifiés :"
            if language.startswith("fr")
            else f"The following {list_subject} were identified:"
        )
        bullet_lines = [f"- {it['label']}" for it in items]
        answer = intro + "\n" + "\n".join(bullet_lines)
        ss = [{"sentence_index": 0, "text": intro, "support_ids": [it["item_id"] for it in items]}]
        for idx, it in enumerate(items, start=1):
            ss.append({
                "sentence_index": idx,
                "text": f"- {it['label']}",
                "support_ids": [it["item_id"]],
            })
        return ComposerResult(
            answer_text=answer,
            sentence_support=ss,
            language=language,
            latency_ms=int((time.time() - t0) * 1000),
            model="deterministic",
            provider="local",
            parse_error=parse_error,
        )

    @staticmethod
    def _abstention_message(language: str) -> str:
        if language.startswith("fr"):
            return "La réponse à votre question n'a pas été trouvée dans les documents disponibles."
        return "The answer to your question was not found in the available documents."


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_default_composer: Optional[ListComposer] = None


def get_list_composer() -> ListComposer:
    global _default_composer
    if _default_composer is None:
        _default_composer = ListComposer()
    return _default_composer


def reset_list_composer() -> None:
    global _default_composer
    _default_composer = None
