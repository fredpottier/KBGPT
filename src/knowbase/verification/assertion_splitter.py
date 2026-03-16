"""
OSMOSE Verification - Assertion Splitter

Uses LLM to split input text into verifiable assertions with their positions.

Author: Claude Code
Date: 2026-02-03
"""

import json
import logging
import re
from typing import List, Dict, Any

from knowbase.common.llm_router import get_llm_router, TaskType

logger = logging.getLogger(__name__)


# Prompt for splitting text into assertions
SPLIT_ASSERTIONS_PROMPT = """You are a text analyzer. Extract EVERY verifiable statement from the text.

A verifiable statement is ANY sentence that:
- States a fact, a claim, a definition, a property, a number, a date
- Makes a positive or NEGATIVE assertion ("X has no effect on Y" IS a verifiable statement)
- Describes what something IS or DOES ("X is a biomarker used for..." IS verifiable)
- Can potentially be confirmed or contradicted by a documentary source

INCLUDE:
- Definitions ("X is a biomarker used for Y")
- Negations ("X has no impact on Y")
- Generalizations ("X is used in primary care")
- Numerical claims ("the rate was 15%")
- Causal claims ("X reduces Y")

DO NOT include:
- Questions
- Pure subjective opinions without factual basis

CRITICAL: Extract EVERY sentence that contains factual content. Err on the side of including too many rather than too few. Each sentence in the text is likely a separate assertion.

Maximum 20 assertions.

Return a JSON array with for each assertion:
- text: the EXACT text as it appears in the original (copy-paste, do not rephrase)
- start: start character index (0-based)
- end: end character index

Text to analyze:
\"\"\"
{text}
\"\"\"

Return ONLY the JSON array:
[
  {{"text": "exact sentence from text", "start": 0, "end": 45}},
  {{"text": "another exact sentence", "start": 47, "end": 80}}
]"""


class AssertionSplitter:
    """
    Splits input text into verifiable assertions using LLM.

    Returns a list of assertions with their exact positions in the original text.
    """

    def __init__(self):
        self.llm_router = get_llm_router()

    async def split(self, text: str) -> List[Dict[str, Any]]:
        """
        Split text into assertions.

        Args:
            text: Input text to analyze

        Returns:
            List of dicts with 'text', 'start', 'end' keys
        """
        if not text or len(text.strip()) < 10:
            logger.warning("[ASSERTION_SPLITTER] Text too short to analyze")
            return []

        # Truncate very long texts
        max_chars = 15000
        if len(text) > max_chars:
            logger.warning(f"[ASSERTION_SPLITTER] Text truncated from {len(text)} to {max_chars} chars")
            text = text[:max_chars]

        prompt = SPLIT_ASSERTIONS_PROMPT.format(text=text)

        try:
            response = await self.llm_router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4096
            )

            assertions = self._parse_response(response, text)
            logger.info(f"[ASSERTION_SPLITTER] Extracted {len(assertions)} assertions from text")
            return assertions

        except Exception as e:
            logger.error(f"[ASSERTION_SPLITTER] LLM call failed: {e}")
            # Fallback: split by sentences
            return self._fallback_split(text)

    def _parse_response(self, response: str, original_text: str) -> List[Dict[str, Any]]:
        """Parse LLM response and validate positions."""
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'\[[\s\S]*\]', response)
        if not json_match:
            logger.warning("[ASSERTION_SPLITTER] No JSON array found in response")
            return []

        try:
            assertions = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            logger.error(f"[ASSERTION_SPLITTER] JSON parse error: {e}")
            return []

        # Validate and fix positions
        validated = []
        for i, assertion in enumerate(assertions):
            if not isinstance(assertion, dict):
                continue

            text = assertion.get("text", "")
            if not text:
                continue

            # Try to find the actual position in original text
            actual_start = original_text.find(text)
            if actual_start >= 0:
                # Found exact match
                validated.append({
                    "text": text,
                    "start": actual_start,
                    "end": actual_start + len(text)
                })
            else:
                # Use LLM-provided positions if they seem valid
                start = assertion.get("start", 0)
                end = assertion.get("end", len(text))

                # Sanity check
                if 0 <= start < len(original_text) and start < end:
                    validated.append({
                        "text": text,
                        "start": start,
                        "end": min(end, len(original_text))
                    })
                else:
                    # Can't find position, skip or use fuzzy match
                    logger.debug(f"[ASSERTION_SPLITTER] Could not locate assertion: {text[:50]}...")

        # Compléter avec les phrases manquantes (le LLM peut en rater)
        validated = self._fill_missing_sentences(validated, original_text)

        # Limit to 20 assertions
        if len(validated) > 20:
            logger.info(f"[ASSERTION_SPLITTER] Limiting from {len(validated)} to 20 assertions")
            validated = validated[:20]

        return validated

    def _fill_missing_sentences(
        self,
        assertions: List[Dict[str, Any]],
        original_text: str,
    ) -> List[Dict[str, Any]]:
        """
        Complète les assertions avec les phrases du texte original
        que le LLM a ratées.

        Le LLM peut considérer certaines phrases comme "non vérifiables"
        (définitions, négations, généralités) alors qu'elles le sont.
        """
        # Découper le texte en phrases
        sentences = re.split(r'(?<=[.!?])\s+', original_text)

        # Positions déjà couvertes par les assertions LLM
        covered_ranges = [(a["start"], a["end"]) for a in assertions]

        def is_covered(start: int, end: int) -> bool:
            for cs, ce in covered_ranges:
                # Overlap significatif (>50% de la phrase)
                overlap = min(end, ce) - max(start, cs)
                if overlap > (end - start) * 0.5:
                    return True
            return False

        # Trouver les phrases manquantes
        added = 0
        current_pos = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:
                current_pos = original_text.find(sentence, current_pos)
                if current_pos >= 0:
                    current_pos += len(sentence)
                continue

            start = original_text.find(sentence, current_pos)
            if start < 0:
                continue

            end = start + len(sentence)

            if not is_covered(start, end):
                assertions.append({
                    "text": sentence,
                    "start": start,
                    "end": end,
                })
                covered_ranges.append((start, end))
                added += 1

            current_pos = end

        if added > 0:
            # Re-trier par position
            assertions.sort(key=lambda a: a["start"])
            logger.info(
                f"[ASSERTION_SPLITTER] Added {added} missing sentences "
                f"(total: {len(assertions)})"
            )

        return assertions

    def _fallback_split(self, text: str) -> List[Dict[str, Any]]:
        """
        Fallback: simple sentence splitting when LLM fails.
        """
        # Simple sentence split (naive but works for fallback)
        sentences = re.split(r'(?<=[.!?])\s+', text)

        assertions = []
        current_pos = 0

        for sentence in sentences[:20]:  # Limit to 20
            sentence = sentence.strip()
            if len(sentence) < 10:
                current_pos = text.find(sentence, current_pos) + len(sentence)
                continue

            start = text.find(sentence, current_pos)
            if start >= 0:
                assertions.append({
                    "text": sentence,
                    "start": start,
                    "end": start + len(sentence)
                })
                current_pos = start + len(sentence)

        return assertions
