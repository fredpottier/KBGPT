"""
OSMOSIS V4 — QuestionAnalyzer (composant [A], CH-41.1).

Détecte le `primary_type` et `secondary_type` (multi-label top-2) d'une question
utilisateur. Émet une `RoutingDecision` selon l'ADR D-FF11 :

  - primary_confidence ≥ 0.7  → routing "single" (Structurer type-specific seul)
  - 0.5 ≤ primary_conf < 0.7  → routing "combined" (top-2 combiné dans Composer)
  - primary_confidence < 0.5  → routing "eav_fallback" (mode abstention EAV)

7 types primaires reconnus (ADR D-FF3) :
  factual, list, temporal, comparison, causal, unanswerable, false_premise

Charte anti-V2 (D-FF1, D-FF8) :
  - Prompt sémantique pur, pas de regex/keywords métier.
  - Multilingue par construction (FR/EN/DE/...).
  - Pas de listing métier hardcodé.
  - Output JSON strict, validation déterministe.

Usage :
    from knowbase.facts_first import get_question_analyzer
    analyzer = get_question_analyzer()
    result = analyzer.analyze("List the four types of authorisations...")
    print(result.primary_type, result.routing.value, result.primary_confidence)
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

from knowbase.runtime_v3.llm_client import RuntimeLLMClient, get_runtime_llm_client

# CH-46 L1 — modèle Analyzer override (env). Default vide → fallback Qwen-72B
# via DEEPINFRA_RUNTIME_MODEL. Set ANALYZER_MODEL=mistralai/Mistral-Small-3.2-24B-Instruct-2506
# pour gagner ~7s sur le stage analyzer (task simple : classification 7 classes).
ANALYZER_MODEL_OVERRIDE = os.getenv("ANALYZER_MODEL", "")

logger = logging.getLogger(__name__)


PRIMARY_TYPES = ("factual", "list", "temporal", "comparison", "causal", "unanswerable", "false_premise")


class RoutingDecision(str, Enum):
    """Décision de routing post-analyse (ADR D-FF11)."""
    SINGLE = "single"              # primary_confidence ≥ 0.7
    COMBINED = "combined"          # 0.5 ≤ primary_confidence < 0.7
    EAV_FALLBACK = "eav_fallback"  # primary_confidence < 0.5


@dataclass
class AnalyzerResult:
    """Résultat structuré d'une analyse de question."""
    primary_type: str
    primary_confidence: float
    secondary_type: Optional[str] = None
    secondary_confidence: Optional[float] = None
    language: str = "en"
    rationale: str = ""
    routing: RoutingDecision = RoutingDecision.EAV_FALLBACK
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    raw_llm_output: str = ""
    parse_error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["routing"] = self.routing.value
        return d


SYSTEM_PROMPT = """You classify the *structural type* of a user question for a multi-domain Q&A system.

Output JSON ONLY, no prose, with this exact schema:
{
  "primary_type": one of [factual, list, temporal, comparison, causal, unanswerable, false_premise],
  "primary_confidence": float 0.0-1.0,
  "secondary_type": one of the same 7 values OR null,
  "secondary_confidence": float 0.0-1.0 OR null,
  "language": ISO 639-1 code (en, fr, de, ...) of the question text,
  "rationale": one short sentence (≤ 25 words) explaining the classification
}

Type definitions (structural intent, language-agnostic):

- list: asks for an ENUMERATION. Decisive signal = the question expects multiple items as answer. Recognize across languages by:
    EN: "list", "what are the", "which X" where X is plural ("which paragraphs", "which conditions")
    FR: "quels", "quelles", "liste", "énumère", "donne-moi les" + plural noun
    DE: "welche X" with plural, "liste"
  Even if the actual count is 1 or 0 in a corpus, if the question expects ≥1 enumerable item the type is list.

- factual: asks for ONE SPECIFIC value, identifier, date, name, number, or definition. Decisive signal = singular noun, "what is the", "quel est le", "wie ist der". The expected answer is a single piece of information.

- temporal: asks about EVOLUTION, CURRENT STATE, SUPERSESSION, or LIFECYCLE across time. Decisive signals:
    - "is X still in force / still applicable / still valid?" (current-status check)
    - "what regulation/version replaced X?" / "which X superseded Y?" (succession)
    - "when was X superseded/deprecated/withdrawn?" (lifecycle change)
    - "what changed between version A and B?" (version delta — but if asks for items list of changes, list takes priority)
    - "is X superseded by Y?" / "Le règlement 428/2009 est-il toujours en vigueur ?" / "Quel règlement a remplacé X ?"
    - meta-questions about KG temporal relationships ("how many SUPERSEDES are in the KG")
  A single date question alone (e.g. "what is the publication date of X?") is factual, NOT temporal.

- comparison: asks to COMPARE ≥2 entities/versions/positions/sources, even when one is implicit. Decisive signals:
    - explicit "X vs Y" / "compare X and Y" / "differences between"
    - "are X and Y identical/equivalent/different?" / "do X and Y contain a divergence?"
    - "X ou Y ?" (FR — choice between two named alternatives)
    - "is there a conflict between X and Y?"
    - the question NAMES at least 2 distinct entities/sources/versions and asks about their relationship.
  Even if the answer ends up being "no, they are equivalent", the question STRUCTURE is comparison.

- causal: asks "WHY", "HOW", or about a MECHANISM / CONDITION / SCENARIO. The expected answer is a reasoning, justification, mechanism, or scenario projection — NOT a single value.
  Includes (universal, multilingual):
    - direct WHY: "Pourquoi X", "why does Y", "warum X", "porqué X"
    - mechanism / how: "Comment X fonctionne", "How does X work", "Quel mécanisme permet Y", "What mechanism allows Y"
    - hypothetical scenario: "Si X était hypothétiquement Y, alors quelle conséquence", "If X were Y, what would happen", "Were X to occur, what...", "Imaginons que X..."
    - conditional projection: "Si A alors B?", "If A then B?", "Sous quelles conditions X?", "Under what conditions Y?", "What if A?", "When does A apply?"
    - rationale request: "Quelle est la raison de X", "Why does X exist", "What is the purpose of Y"
    - escape / contestation: "Si quelqu'un voulait X, quel recours?", "If someone wanted to do X, what option?"
  Decisive signal: the question is NOT seeking ONE single value/identifier; it requires explanation, condition application, or scenario reasoning.

- unanswerable: question structure asks for information that is generically beyond reach (meta-question about the system itself, opinion on private matters). NOT to be used for "info-just-not-in-corpus" — that is detected downstream after evidence retrieval.

- false_premise: question contains an explicit FACTUALLY-VERIFIABLE-WRONG assumption stated in the question (e.g. "given that the speed limit is 200 mph in France"). NOT to be used for "could-be-true-could-be-false" — that is a downstream verdict.

Critical disambiguation rules (apply in order):
1. If the question NAMES ≥2 distinct entities/versions/sources AND asks about their relationship (identical, different, equivalent, divergent, conflict, X or Y) → comparison.
2. If asks about CURRENT STATE / SUPERSESSION / replacement / lifecycle ("still in force?", "replaced by?", "superseded?") → temporal.
3. If the question requests multiple items via plural noun ("quels paragraphes", "which conditions") → list.
4. If asks "WHY", a MECHANISM, a SCENARIO, a CONDITION, or a HYPOTHETICAL projection → causal.
   This INCLUDES "Si X..." / "If X..." / "Quel mécanisme..." / "Sous quelles conditions...". These are NOT factual.
5. If single fact/value/identifier with no scenario/condition/mechanism component (singular noun, "what is the date of X?", "quelle est la valeur de X?") → factual.
6. unanswerable / false_premise: ONLY use if obviously meta or obviously contains wrong-fact-as-given. When in doubt, classify by structural intent and let downstream detect answerability.

Tie-breaker — factual vs causal:
- If the answer is ONE concrete value/name/date with no reasoning required → factual.
- If the answer requires explaining a mechanism, applying a condition, projecting a scenario, or
  giving a rationale → causal. Even when the wording opens with "what" or "quel" — the structural
  intent matters more than the question word ("Quel mécanisme permettrait X?" is causal, not factual).

Confidence calibration:
- ≥0.7 = clear single type (no genuine secondary interpretation).
- 0.5-0.7 = two plausible types — provide secondary.
- <0.5 = genuinely ambiguous (rare).

Multilingual: handle FR / EN / DE / ES / IT / NL uniformly — language field reports the question's language.
Return only the JSON object."""


def _safe_float(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        return max(0.0, min(1.0, v))
    except (TypeError, ValueError):
        return default


def _routing_from_confidence(conf: float) -> RoutingDecision:
    if conf >= 0.7:
        return RoutingDecision.SINGLE
    if conf >= 0.5:
        return RoutingDecision.COMBINED
    return RoutingDecision.EAV_FALLBACK


class QuestionAnalyzer:
    """Analyseur de questions multi-label top-2 (CH-41.1)."""

    def __init__(
        self,
        llm: Optional[RuntimeLLMClient] = None,
        max_tokens: int = 250,
        temperature: float = 0.1,
        timeout: float = 30.0,
        model_override: Optional[str] = None,
    ) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        # CH-46 L1 — model_override priorité : explicit > env > default RuntimeLLMClient
        self.model_override = model_override or (ANALYZER_MODEL_OVERRIDE or None)

    def analyze(self, question: str, language_hint: Optional[str] = None) -> AnalyzerResult:
        """Analyse une question et émet le routing.

        Args:
            question: texte de la question utilisateur.
            language_hint: code ISO de la langue si déjà connu (utilisé pour log seulement,
                la langue est re-détectée par le LLM dans tous les cas).
        """
        if not question or not question.strip():
            return AnalyzerResult(
                primary_type="unanswerable",
                primary_confidence=0.0,
                language=language_hint or "en",
                rationale="empty question",
                routing=RoutingDecision.EAV_FALLBACK,
                parse_error="empty_input",
            )

        user_prompt = f"QUESTION: {question.strip()}\n\nClassify and output JSON only."
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        t0 = time.time()
        try:
            meta = self.llm.chat_completion_with_meta(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                json_mode=True,
                timeout=self.timeout,
                model_override=self.model_override,  # CH-46 L1
            )
        except Exception as exc:
            latency_ms = int((time.time() - t0) * 1000)
            logger.warning("QuestionAnalyzer LLM call failed: %s", exc)
            return AnalyzerResult(
                primary_type="unanswerable",
                primary_confidence=0.0,
                language=language_hint or "en",
                rationale=f"llm_error: {exc.__class__.__name__}",
                routing=RoutingDecision.EAV_FALLBACK,
                latency_ms=latency_ms,
                parse_error=str(exc),
            )

        latency_ms = int((time.time() - t0) * 1000)
        raw = meta.get("content", "") or ""
        return self._parse_response(
            raw=raw,
            latency_ms=latency_ms,
            model=meta.get("model", ""),
            provider=meta.get("provider", ""),
            language_hint=language_hint,
        )

    def _parse_response(
        self,
        raw: str,
        latency_ms: int,
        model: str,
        provider: str,
        language_hint: Optional[str],
    ) -> AnalyzerResult:
        """Parse le JSON LLM avec validation stricte. Retombe sur EAV_FALLBACK si malformé."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return AnalyzerResult(
                primary_type="unanswerable",
                primary_confidence=0.0,
                language=language_hint or "en",
                rationale="json_parse_error",
                routing=RoutingDecision.EAV_FALLBACK,
                latency_ms=latency_ms,
                model=model,
                provider=provider,
                raw_llm_output=raw[:500],
                parse_error=f"json_parse: {exc}",
            )

        if not isinstance(data, dict):
            return AnalyzerResult(
                primary_type="unanswerable",
                primary_confidence=0.0,
                language=language_hint or "en",
                rationale="not_object",
                routing=RoutingDecision.EAV_FALLBACK,
                latency_ms=latency_ms,
                model=model,
                provider=provider,
                raw_llm_output=raw[:500],
                parse_error="not_object",
            )

        primary_type = str(data.get("primary_type", "")).strip().lower()
        if primary_type not in PRIMARY_TYPES:
            return AnalyzerResult(
                primary_type="unanswerable",
                primary_confidence=0.0,
                language=str(data.get("language", language_hint or "en")),
                rationale=str(data.get("rationale", ""))[:200],
                routing=RoutingDecision.EAV_FALLBACK,
                latency_ms=latency_ms,
                model=model,
                provider=provider,
                raw_llm_output=raw[:500],
                parse_error=f"unknown_primary_type:{primary_type}",
            )

        primary_conf = _safe_float(data.get("primary_confidence"), default=0.0)
        secondary_type = data.get("secondary_type")
        secondary_conf = data.get("secondary_confidence")

        # Normalize secondary
        if isinstance(secondary_type, str):
            stype = secondary_type.strip().lower()
            if stype not in PRIMARY_TYPES or stype == primary_type:
                secondary_type = None
                secondary_conf = None
            else:
                secondary_type = stype
                secondary_conf = _safe_float(secondary_conf, default=0.0) if secondary_conf is not None else None
        else:
            secondary_type = None
            secondary_conf = None

        language = str(data.get("language", language_hint or "en")).strip().lower()
        if not language or len(language) > 10:
            language = language_hint or "en"

        rationale = str(data.get("rationale", ""))[:300]

        return AnalyzerResult(
            primary_type=primary_type,
            primary_confidence=primary_conf,
            secondary_type=secondary_type,
            secondary_confidence=secondary_conf,
            language=language,
            rationale=rationale,
            routing=_routing_from_confidence(primary_conf),
            latency_ms=latency_ms,
            model=model,
            provider=provider,
            raw_llm_output=raw[:500],
            parse_error=None,
        )


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------

_default_analyzer: Optional[QuestionAnalyzer] = None


def get_question_analyzer() -> QuestionAnalyzer:
    """Singleton du QuestionAnalyzer."""
    global _default_analyzer
    if _default_analyzer is None:
        _default_analyzer = QuestionAnalyzer()
    return _default_analyzer


def reset_question_analyzer() -> None:
    """Force re-init (test/dev)."""
    global _default_analyzer
    _default_analyzer = None
