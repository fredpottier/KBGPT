"""
OSMOSE Verification Service

Business logic for text verification against Knowledge Graph.

Author: Claude Code
Date: 2026-02-03
"""

import logging
from typing import Dict, Optional
from uuid import uuid4

from knowbase.verification.assertion_splitter import AssertionSplitter
from knowbase.verification.evidence_matcher import EvidenceMatcher
from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.api.schemas.verification import (
    Assertion,
    VerifyResponse,
    CorrectResponse,
    CorrectionChange,
    VerificationStatus,
)

logger = logging.getLogger(__name__)


# Prompt for correcting text
CORRECT_TEXT_PROMPT = """You are a precise text corrector. Fix problematic assertions based on evidence.

ORIGINAL TEXT:
\"\"\"
{original_text}
\"\"\"

PROBLEMATIC ASSERTIONS:
{problematic_assertions}

HOW TO CORRECT:

For [CONTRADICTED] assertions:
- Replace the WRONG value with the CORRECT value from evidence
- If evidence shows a range (e.g., "99.7 to 99.9%"), use the full range

For [INCOMPLETE] assertions:
- The value is correct but missing alternatives
- Add the other valid values/conditions mentioned in evidence
- Format: "X or Y" or "X to Y" depending on context

STRICT RULES:
1. Keep the SAME LANGUAGE as the original text
2. Keep the same sentence structure as much as possible
3. Do NOT add unrelated information or explanations
4. Every [CONTRADICTED] and [INCOMPLETE] item MUST be corrected

EXAMPLES:
- [CONTRADICTED] "X is 50%" + evidence "X is 75%" → change to "X is 75%"
- [CONTRADICTED] "X is 50%" + evidence "X is 75 to 80%" → change to "X is 75 to 80%"
- [INCOMPLETE] "X is 30" + evidence "X is 0 or 30 depending on config" → change to "X is 0 or 30 depending on config"
- [INCOMPLETE] "X takes 60s" + evidence "X takes 60s or 120s" → change to "X takes 60s or 120s"

Return ONLY a JSON object (no surrounding text):
{{
  "corrected_text": "The corrected text with ALL fixes applied...",
  "changes": [
    {{"original": "original part", "corrected": "corrected part", "reason": "brief reason"}}
  ]
}}"""


class VerificationService:
    """
    Service for verifying text against Knowledge Graph.

    Pipeline:
    1. Split text into assertions (LLM)
    2. Find evidence for each assertion (Neo4j claims + Qdrant fallback)
    3. Determine verification status
    4. Optionally generate corrections
    """

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        self.assertion_splitter = AssertionSplitter()
        self.evidence_matcher = EvidenceMatcher(tenant_id)
        self.llm_router = get_llm_router()

    async def analyze(self, text: str) -> VerifyResponse:
        """
        Analyze text and verify each assertion.

        Args:
            text: Input text to verify

        Returns:
            VerifyResponse with assertions and summary
        """
        logger.info(f"[VERIFICATION] Starting analysis of {len(text)} chars")

        # 1. Split text into assertions
        assertions_raw = await self.assertion_splitter.split(text)
        logger.info(f"[VERIFICATION] Extracted {len(assertions_raw)} assertions")

        # 2. Verify each assertion
        assertions = []
        for i, raw in enumerate(assertions_raw):
            assertion_id = f"A{i + 1}"
            assertion_text = raw.get("text", "")

            logger.debug(f"[VERIFICATION] Checking assertion {assertion_id}: {assertion_text[:50]}...")

            # Find evidence
            evidence, status, confidence = await self.evidence_matcher.find_evidence(
                assertion_text
            )

            assertions.append(Assertion(
                id=assertion_id,
                text=assertion_text,
                start_index=raw.get("start", 0),
                end_index=raw.get("end", len(assertion_text)),
                status=status,
                confidence=confidence,
                evidence=evidence
            ))

        # 3. Compute summary
        summary = self._compute_summary(assertions)

        logger.info(
            f"[VERIFICATION] Analysis complete: "
            f"{summary['confirmed']} confirmed, "
            f"{summary['contradicted']} contradicted, "
            f"{summary['incomplete']} incomplete, "
            f"{summary['fallback']} fallback, "
            f"{summary['unknown']} unknown"
        )

        return VerifyResponse(
            original_text=text,
            assertions=assertions,
            summary=summary
        )

    async def correct(
        self,
        text: str,
        assertions: list[Assertion]
    ) -> CorrectResponse:
        """
        Generate corrected version of text based on verified assertions.

        Args:
            text: Original text
            assertions: Verified assertions with evidence

        Returns:
            CorrectResponse with corrected text and changes
        """
        # Filter problematic assertions (contradicted or incomplete)
        problematic = [
            a for a in assertions
            if a.status in (VerificationStatus.CONTRADICTED, VerificationStatus.INCOMPLETE)
        ]

        if not problematic:
            logger.info("[VERIFICATION] No corrections needed")
            return CorrectResponse(
                corrected_text=text,
                changes=[]
            )

        logger.info(f"[VERIFICATION] Generating corrections for {len(problematic)} issues")

        # Format problematic assertions for prompt
        assertions_text = ""
        for a in problematic:
            status_label = "CONTRADICTED" if a.status == VerificationStatus.CONTRADICTED else "INCOMPLETE"
            assertions_text += f"\n- [{status_label}] \"{a.text}\"\n"

            # Add evidence with clear instructions
            for ev in a.evidence:
                if ev.relationship == "contradicts":
                    assertions_text += f"  → REPLACE WITH: {ev.text}\n"
                elif ev.relationship == "partial":
                    assertions_text += f"  → COMPLETE WITH: {ev.text}\n"
                else:
                    assertions_text += f"  → Evidence: {ev.text}\n"

        prompt = CORRECT_TEXT_PROMPT.format(
            original_text=text,
            problematic_assertions=assertions_text
        )

        try:
            response = await self.llm_router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=4096
            )

            return self._parse_correction_response(response, text)

        except Exception as e:
            logger.error(f"[VERIFICATION] Correction generation failed: {e}")
            return CorrectResponse(
                corrected_text=text,
                changes=[]
            )

    def _compute_summary(self, assertions: list[Assertion]) -> Dict[str, int]:
        """Compute summary statistics."""
        summary = {
            "total": len(assertions),
            "confirmed": 0,
            "contradicted": 0,
            "incomplete": 0,
            "fallback": 0,
            "unknown": 0
        }

        for a in assertions:
            if a.status == VerificationStatus.CONFIRMED:
                summary["confirmed"] += 1
            elif a.status == VerificationStatus.CONTRADICTED:
                summary["contradicted"] += 1
            elif a.status == VerificationStatus.INCOMPLETE:
                summary["incomplete"] += 1
            elif a.status == VerificationStatus.FALLBACK:
                summary["fallback"] += 1
            else:
                summary["unknown"] += 1

        return summary

    def _parse_correction_response(
        self,
        response: str,
        original_text: str
    ) -> CorrectResponse:
        """Parse LLM correction response."""
        import json
        import re

        # Try to extract JSON
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                corrected_text = data.get("corrected_text", original_text)

                changes = []
                for change in data.get("changes", []):
                    if isinstance(change, dict):
                        changes.append(CorrectionChange(
                            original=change.get("original", ""),
                            corrected=change.get("corrected", ""),
                            reason=change.get("reason", "")
                        ))

                return CorrectResponse(
                    corrected_text=corrected_text,
                    changes=changes
                )

            except json.JSONDecodeError:
                pass

        # Fallback: return original
        logger.warning("[VERIFICATION] Could not parse correction response")
        return CorrectResponse(
            corrected_text=original_text,
            changes=[]
        )


# Factory function
_service_cache: Dict[str, VerificationService] = {}


def get_verification_service(tenant_id: str = "default") -> VerificationService:
    """Get or create VerificationService instance."""
    if tenant_id not in _service_cache:
        _service_cache[tenant_id] = VerificationService(tenant_id)
    return _service_cache[tenant_id]
