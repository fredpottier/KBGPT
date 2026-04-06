"""
OSMOSE Verification Service

Business logic for text verification against Knowledge Graph.
V2: Uses search_documents pipeline instead of evidence_matcher.

Author: Claude Code
Date: 2026-02-03
"""

import json
import logging
import re
from typing import Dict

from knowbase.verification.assertion_splitter import AssertionSplitter
from knowbase.api.services.search import search_documents
from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings
from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.api.schemas.verification import (
    Assertion,
    Evidence,
    VerifyResponse,
    CorrectResponse,
    CorrectionChange,
    VerificationStatus,
)

logger = logging.getLogger(__name__)


# Prompt for comparing assertion against corpus answer
COMPARE_ASSERTION_PROMPT = """You are a fact-checker. Compare an ASSERTION against the CORPUS ANSWER retrieved from a document knowledge base.

ASSERTION:
"{assertion}"

CORPUS ANSWER:
"{corpus_answer}"

Determine:
- "confirmed" if the corpus answer clearly supports/confirms the assertion
- "contradicted" if the corpus answer clearly contradicts the assertion (different values, dates, facts)
- "incomplete" if the corpus answer partially covers the assertion but is missing key details
- "unknown" if the corpus answer does not address the topic of the assertion at all

Return ONLY a JSON object:
{{"status": "confirmed|contradicted|incomplete|unknown", "confidence": 0.0-1.0, "explanation": "brief reason"}}"""


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
        self.llm_router = get_llm_router()
        self.settings = get_settings()
        self.qdrant_client = get_qdrant_client()
        self.embedding_model = get_sentence_transformer()

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

        # 2. Verify each assertion via search pipeline + LLM compare
        assertions = []
        for i, raw in enumerate(assertions_raw):
            assertion_id = f"A{i + 1}"
            assertion_text = raw.get("text", "")

            logger.debug(f"[VERIFICATION] Checking assertion {assertion_id}: {assertion_text[:50]}...")

            try:
                # 2a. Search corpus using the full search pipeline
                search_result = search_documents(
                    question=assertion_text,
                    qdrant_client=self.qdrant_client,
                    embedding_model=self.embedding_model,
                    settings=self.settings,
                    tenant_id=self.tenant_id,
                )

                synthesis = search_result.get("synthesis", {})
                corpus_answer = synthesis.get("synthesized_answer", "")
                chunks = search_result.get("results", [])

                if not corpus_answer or corpus_answer.strip() == "":
                    # No answer from corpus
                    status = VerificationStatus.UNKNOWN
                    confidence = 0.0
                    explanation = "Aucune information trouvée dans le corpus"
                    evidence_list = []
                else:
                    # 2b. Compare assertion vs corpus answer via LLM
                    verdict = await self._compare_assertion_vs_corpus(
                        assertion_text, corpus_answer
                    )
                    status = self._verdict_to_status(verdict.get("status", "unknown"))
                    confidence = verdict.get("confidence", 0.5)
                    explanation = verdict.get("explanation", "")

                    # 2c. Build evidence from top chunks
                    status_to_relationship = {
                        VerificationStatus.CONFIRMED: "supports",
                        VerificationStatus.CONTRADICTED: "contradicts",
                        VerificationStatus.INCOMPLETE: "partial",
                        VerificationStatus.UNKNOWN: "partial",
                        VerificationStatus.FALLBACK: "partial",
                    }
                    relationship = status_to_relationship.get(status, "partial")

                    evidence_list = []
                    for chunk in chunks[:3]:
                        evidence_list.append(Evidence(
                            type="chunk",
                            text=chunk.get("text", "")[:500],
                            source_doc=chunk.get("source_file", "unknown"),
                            source_page=chunk.get("slide_index"),
                            confidence=chunk.get("score", 0.5),
                            relationship=relationship,
                            comparison_details={
                                "reason_code": f"SEARCH_PIPELINE_{status.value.upper()}",
                                "reason_message": explanation,
                                "deterministic": False,
                                "corpus_answer_excerpt": corpus_answer[:300],
                            }
                        ))

            except Exception as e:
                logger.error(f"[VERIFICATION] Error checking assertion {assertion_id}: {e}")
                status = VerificationStatus.UNKNOWN
                confidence = 0.0
                evidence_list = []

            assertions.append(Assertion(
                id=assertion_id,
                text=assertion_text,
                start_index=raw.get("start", 0),
                end_index=raw.get("end", len(assertion_text)),
                status=status,
                confidence=confidence,
                evidence=evidence_list,
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

    async def _compare_assertion_vs_corpus(self, assertion: str, corpus_answer: str) -> dict:
        """Compare une assertion avec la réponse du corpus via LLM."""
        prompt = COMPARE_ASSERTION_PROMPT.format(
            assertion=assertion,
            corpus_answer=corpus_answer[:2000],
        )

        try:
            response = await self.llm_router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=256,
            )

            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.error(f"[VERIFICATION] LLM compare failed: {e}")

        return {"status": "unknown", "confidence": 0.0, "explanation": "LLM comparison failed"}

    @staticmethod
    def _verdict_to_status(verdict_status: str) -> VerificationStatus:
        """Map verdict string to VerificationStatus enum."""
        mapping = {
            "confirmed": VerificationStatus.CONFIRMED,
            "contradicted": VerificationStatus.CONTRADICTED,
            "incomplete": VerificationStatus.INCOMPLETE,
            "unknown": VerificationStatus.UNKNOWN,
        }
        return mapping.get(verdict_status, VerificationStatus.UNKNOWN)

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
