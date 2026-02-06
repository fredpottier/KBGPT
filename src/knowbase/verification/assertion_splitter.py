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
SPLIT_ASSERTIONS_PROMPT = """You are a text analyzer. Your task is to identify each verifiable ASSERTION or FACT in the given text.

An assertion is a sentence or part of a sentence that:
- States something factual (characteristics, numbers, features, dates, names, etc.)
- Can be true or false
- Can be verified against a documentary source

DO NOT include:
- Questions
- Purely subjective opinions ("it's good", "I think that...")
- Logical connectors alone ("therefore", "however", etc.)
- Sentences with no factual content

IMPORTANT: Limit yourself to a maximum of 20 assertions to avoid overly long analysis.

Return a JSON array with for each assertion:
- text: the exact text of the assertion (as it appears in the original text)
- start: start position in the original text (character index, starting at 0)
- end: end position in the original text (character index)

Text to analyze:
\"\"\"
{text}
\"\"\"

Return ONLY the JSON array, with no surrounding text. Expected format:
[
  {{"text": "The product was released in 2020.", "start": 0, "end": 33}},
  {{"text": "It supports up to 100 users.", "start": 35, "end": 62}}
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

        # Limit to 20 assertions
        if len(validated) > 20:
            logger.info(f"[ASSERTION_SPLITTER] Limiting from {len(validated)} to 20 assertions")
            validated = validated[:20]

        return validated

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
