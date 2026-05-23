"""Module Parse — LLM #1 décomposition question → sub-goals.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.1 + §3.1 + §3.1.1.

Architecture :
    parse(input: ParseInput) -> ParseOutput

Logique :
    1. Charger few-shot examples depuis prompts/parse_examples.json (cached)
    2. Construire system prompt avec injection examples
    3. Appeler LLM via llm_router (TaskType.KNOWLEDGE_EXTRACTION, Qwen3-235B par défaut — A4.8 rollback)
    4. Parser output JSON + valider Pydantic
    5. Si validation échoue → retry 1× avec instruction renforcée
    6. Si retry échoue → fallback déterministe (1 sub_goal fact_lookup naïf, confidence=0.3)

Garde-fous :
    - Max 5 sub_goals (Pydantic validation max_length=5)
    - Question >5000 chars → tronquer avec warning question_truncated
    - parse_confidence < 0.5 → Evaluate routera vers INSUFFICIENT (saut Plan/Execute)
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from knowbase.runtime_a3.schemas import (
    ParseError,
    ParseInput,
    ParseOutput,
    ParseValidationError,
    SubGoal,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

# Path vers les few-shot examples (relative au module)
_EXAMPLES_PATH = Path(__file__).parent / "prompts" / "parse_examples.json"

# Limites (cf ADR §2.9 + §3.1.1 stratégie context window)
MAX_QUESTION_CHARS = 5000  # au-delà, troncature avec warning
MAX_SUB_GOALS = 5


# ============================================================================
# System prompt construction
# ============================================================================


_SYSTEM_PROMPT_BASE = """You are a query decomposer for a knowledge graph runtime.
Given a user question, produce a list of CONCRETE sub-goals that can be answered by querying a structured knowledge base.

OUTPUT JSON ONLY, matching this schema:
{
  "sub_goals": [
    {
      "kind": "fact_lookup | list_enumeration | comparison | lifecycle_trace | contradiction_check | definition_lookup",
      "subject_canonical": "entity name (or null if too broad)",
      "predicate_hint": "verb or relation (e.g. 'uses', 'released_at', or null)",
      "object_hint": "expected value or pattern (or null)",
      "expected_value_kind": "percent | version | number | string | date | boolean | null",
      "time_filter": "as_of | current | evolution",
      "priority": 1
    }
  ],
  "entities": ["entity1", "entity2"],
  "language": "fr | en | de | es | other",
  "raw_question": "<echo of original question>",
  "parse_confidence": 0.0,
  "parse_warnings": ["ambiguous subject", "..."],
  "schema_version": "a3.0"
}

GUIDELINES:
- Decompose, don't classify. The output is a list of small, actionable goals — not a single "type".
- A simple question may have just 1 sub_goal. A complex one (comparison, lifecycle) may have 2-3.
- Use "fact_lookup" for "X has predicate Y" style questions.
- Use "list_enumeration" for "all X such that ..." style.
- Use "comparison" when comparing 2 entities — 2 fact_lookups + diff (one sub_goal per entity).
- Use "lifecycle_trace" when the question implies evolution over time.
- Use "contradiction_check" when the question explicitly asks about conflicts.
- Use "definition_lookup" for "what is X?" style.
- subject_canonical should be the most specific entity reasonably extractable. If unclear, null.
- time_filter:
    "current" = default, what's true now
    "as_of" = point-in-time historical query
    "evolution" = trace changes over time
- parse_confidence: low when subject ambiguous, multiple interpretations, or out-of-scope.

MAXIMUM 5 sub_goals. If the question is unanswerable (out of scope, weather, etc.), return [] sub_goals + warning "out_of_scope_for_corpus" + confidence < 0.3."""


def _format_example_block(examples: List[Dict[str, Any]]) -> str:
    """Formate la section EXAMPLES injectée dans le system prompt.

    Domain-agnostic strict : examples doivent rester avec placeholders abstraits
    (Product X, Tool Alpha, etc.). Validation côté tests.
    """
    lines = ["", "## EXAMPLES", ""]
    for i, ex in enumerate(examples, 1):
        lines.append(f"### Example {i}")
        lines.append(f'User question: "{ex["question"]}"')
        lines.append("Expected output:")
        lines.append("```json")
        lines.append(json.dumps(ex["expected"], indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _load_examples() -> List[Dict[str, Any]]:
    """Charge les few-shot examples depuis JSON. Mis en cache (LRU)."""
    if not _EXAMPLES_PATH.exists():
        raise ParseError(f"Few-shot examples file not found: {_EXAMPLES_PATH}")
    return json.loads(_EXAMPLES_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _build_system_prompt() -> str:
    """Construit le system prompt complet avec injection examples. Mis en cache (LRU)."""
    examples = _load_examples()
    examples_block = _format_example_block(examples)
    return _SYSTEM_PROMPT_BASE + examples_block


# ============================================================================
# Parser
# ============================================================================


class Parser:
    """Module Parse — convertit question → ParseOutput via LLM.

    Cf ADR §2.1 + §3.1.

    Usage:
        from knowbase.runtime_a3.parse import Parser
        parser = Parser()
        output = parser.parse(ParseInput(question="...", tenant_id="default"))
    """

    def __init__(self, llm_client=None) -> None:
        """Args :
            llm_client : injection optionnelle d'un client LLM custom (tests).
                         Si None, utilise llm_router (TaskType.KNOWLEDGE_EXTRACTION).
        """
        self._llm_client = llm_client

    def parse(self, parse_input: ParseInput) -> ParseOutput:
        """Convertit la question en ParseOutput structuré.

        Returns :
            ParseOutput validé Pydantic.

        Raises :
            ParseError : si fallback déterministe lui-même échoue (très rare).
        """
        # 1. Préparer la question (tronquer si trop longue)
        question, truncation_warning = self._prepare_question(parse_input.question)

        # 2. Tenter le LLM call (avec 1 retry)
        try:
            output = self._call_llm_with_retry(question, parse_input)
        except (ParseValidationError, Exception) as e:
            logger.warning(f"[Parse] LLM call failed: {e}. Using deterministic fallback.")
            return self._fallback_deterministic(parse_input.question, parse_input)

        # 3. Ajouter le warning de troncature si applicable
        if truncation_warning and truncation_warning not in output.parse_warnings:
            output.parse_warnings.append(truncation_warning)

        return output

    # ------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------

    @staticmethod
    def _prepare_question(question: str) -> tuple[str, Optional[str]]:
        """Tronque la question si > MAX_QUESTION_CHARS. Retourne (question, warning|None)."""
        if len(question) <= MAX_QUESTION_CHARS:
            return question, None

        # Troncature : 2000 début + 2000 fin (cf ADR §3.1.1)
        half = (MAX_QUESTION_CHARS - 100) // 2
        truncated = question[:half] + "\n\n[... TRUNCATED ...]\n\n" + question[-half:]
        return truncated, "question_truncated"

    def _call_llm_with_retry(self, question: str, parse_input: ParseInput) -> ParseOutput:
        """Appelle le LLM (A4.14 — retry désactivé, fallback déterministe direct).

        Initialement 2 attempts (retry sur ValidationError/JSONDecodeError). Mais bench
        50q montre que Qwen3-235B-Instruct-2507 rate JSON ~30% des cas et le retry
        sauve <5% — coûteux (+15-30s par question) pour gain marginal.
        Fallback déterministe activé direct dès le 1er échec.
        """
        try:
            raw_output = self._invoke_llm(question, parse_input, attempt=0)
            output = self._parse_and_validate(raw_output, parse_input.question)
            return output
        except ValidationError as e:
            raise ParseValidationError(f"LLM output invalide: {e}") from e
        except json.JSONDecodeError as e:
            raise ParseValidationError(f"LLM output JSON invalide: {e}") from e

    def _invoke_llm(self, question: str, parse_input: ParseInput, attempt: int) -> str:
        """Invoke LLM via llm_router (ou client injecté) et retourne le raw text."""
        if self._llm_client is not None:
            # Tests : llm_client injecté avec interface .complete(messages, ...)
            return self._llm_client.complete(
                messages=self._build_messages(question, parse_input, attempt),
                temperature=0.1,
                max_tokens=2000,
            )

        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()
        # A4.8 ROLLBACK (22/05/2026 soir) : switch DeepSeek-V3.1 a régressé C1 0.300→0.050
        # car le fallback déterministe (avec subject=None) ratissait plus large que
        # Parse réussi (avec subject_canonical trop précis qui sabotait le retrieval).
        # Revert KNOWLEDGE_EXTRACTION (Qwen3-235B). Le vrai fix est dans Execute (Piste A).
        return router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=self._build_messages(question, parse_input, attempt),
            temperature=0.1,
            max_tokens=2000,
        ).strip()

    @staticmethod
    def _build_messages(question: str, parse_input: ParseInput, attempt: int) -> List[Dict[str, str]]:
        """Construit les messages [system, user] pour l'LLM."""
        system = _build_system_prompt()
        user_parts = [f"User question: {question}"]
        if parse_input.language_hint:
            user_parts.append(f"Language hint: {parse_input.language_hint}")
        if parse_input.as_of_date:
            user_parts.append(f"As-of date (point-in-time query): {parse_input.as_of_date.isoformat()}")

        if attempt > 0:
            # Renforce l'instruction au retry
            user_parts.append(
                "\nRETRY NOTE: previous output failed JSON schema validation. "
                "Be strict: output ONLY valid JSON matching the schema exactly. "
                "No markdown fences, no commentary."
            )

        user_parts.append(
            "\nOutput the JSON now (no markdown, no surrounding text):"
        )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    @staticmethod
    def _parse_and_validate(raw_output: str, original_question: str) -> ParseOutput:
        """Parse le JSON et valide via Pydantic.

        Tolère les ```json fences au cas où le LLM les ajoute.
        Force `raw_question` à la question originale si absent ou modifié par le LLM.
        """
        text = raw_output.strip()
        # Strip markdown fences si présentes
        if text.startswith("```"):
            lines = text.split("\n")
            # Retire ligne ```json et ```
            text = "\n".join(line for line in lines if not line.strip().startswith("```"))

        data = json.loads(text)

        # Force raw_question à la question originale (le LLM peut paraphraser)
        data["raw_question"] = original_question

        # Validation Pydantic stricte
        return ParseOutput.model_validate(data)

    @staticmethod
    def _fallback_deterministic(question: str, parse_input: ParseInput) -> ParseOutput:
        """Fallback déterministe — 1 sub_goal fact_lookup naïf, parse_confidence=0.3.

        Utilisé quand le LLM échoue 2× retry + validation. Permet au runtime de
        continuer en mode dégradé plutôt que crasher (le sub_goal sera probablement
        marqué INSUFFICIENT par Evaluate vu la confidence basse).
        """
        return ParseOutput(
            sub_goals=[
                SubGoal(
                    kind="fact_lookup",
                    subject_canonical=None,
                    predicate_hint=None,
                    object_hint=None,
                    expected_value_kind=None,
                    time_filter="current",
                    priority=1,
                )
            ],
            entities=[],  # Pas de NER déterministe ici (gardé simple pour le fallback)
            language=parse_input.language_hint or _detect_language_naive(question),
            raw_question=question,
            parse_confidence=0.3,
            parse_warnings=["parse_llm_failed_fallback_deterministic_used"],
            schema_version="a3.0",
        )


def _detect_language_naive(text: str) -> str:
    """Heuristique simple FR vs EN basée sur mots fréquents.

    Pour Phase A3.1, suffit. Plus tard, on pourrait intégrer langdetect / fasttext si
    besoin. Reste domain-agnostic.
    """
    fr_markers = {"le", "la", "les", "de", "du", "des", "un", "une", "est", "sont", "quelle", "quel"}
    en_markers = {"the", "of", "and", "is", "are", "what", "which", "how", "to", "in", "for"}

    tokens = {t.lower() for t in text.split() if t}
    fr_score = len(tokens & fr_markers)
    en_score = len(tokens & en_markers)

    if fr_score > en_score:
        return "fr"
    if en_score > 0:
        return "en"
    return "other"


# ============================================================================
# API publique
# ============================================================================


def parse(parse_input: ParseInput, llm_client=None) -> ParseOutput:
    """API top-level — convertit question → ParseOutput.

    Args :
        parse_input : ParseInput (question + tenant_id + optionnels)
        llm_client : optionnel, injection pour tests

    Returns :
        ParseOutput validé.

    Exemple :
        from knowbase.runtime_a3.parse import parse
        from knowbase.runtime_a3.schemas import ParseInput

        result = parse(ParseInput(
            question="What is the maximum number of users for product X?",
            tenant_id="default",
        ))
        for sg in result.sub_goals:
            print(sg.kind, sg.subject_canonical, sg.predicate_hint)
    """
    parser = Parser(llm_client=llm_client)
    return parser.parse(parse_input)
