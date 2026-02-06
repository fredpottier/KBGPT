"""
OSMOSE Verification - Evidence Matcher V1.1

Searches for evidence in Neo4j claims and falls back to Qdrant chunks.
Uses deterministic comparison engine for structured values (V1.1).

Author: Claude Code
Date: 2026-02-03
Version: 1.1 - Deterministic comparison engine
"""

from __future__ import annotations

import json
import logging
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.common.clients.qdrant_client import get_qdrant_client, search_with_tenant_filter
from knowbase.common.clients.embeddings import EmbeddingModelManager
from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.config.settings import get_settings

# V1.1: Deterministic comparison engine (imported at module level - no circular dep)
from knowbase.verification.comparison import (
    ComparisonEngine,
    ComparisonResult,
    ComparisonExplanation,
    StructuredExtractor,
    TolerancePolicy,
    AggregatorPolicy,
    ClaimComparison,
    ClaimForm,
    ClaimFormType,
    AuthorityLevel,
    ReasonCode,
)


def _get_verification_schemas():
    """Lazy import to avoid circular dependency."""
    from knowbase.api.schemas.verification import Evidence, VerificationStatus
    return Evidence, VerificationStatus

logger = logging.getLogger(__name__)


# Prompt for comparing assertion to claims
COMPARE_CLAIM_PROMPT = """You are comparing a user ASSERTION against documented CLAIMS from a trusted knowledge base.

ASSERTION to verify:
"{assertion}"

CLAIMS found in knowledge base (trusted sources):
{claims_text}

Determine the relationship between the assertion and the claims:

**CONTRADICTS** - Use this status when:
- The assertion states a DIFFERENT VALUE than the claims for the SAME property
- Numbers, dates, percentages, quantities DO NOT match
- Examples of contradictions:
  - "X is 50%" vs claim "X is 75%" → CONTRADICTS (different percentage)
  - "X is 99.5%" vs claim "X is 99.7% to 99.9%" → CONTRADICTS (99.5% is NOT in range 99.7-99.9%)
  - "launched in 2020" vs claim "launched in 2018" → CONTRADICTS

**SUPPORTS** - Use this status when:
- The assertion value MATCHES the claim value (exact or equivalent)
- The assertion covers ALL the values/options mentioned in claims
- Examples of support:
  - "X is 50" vs claim "X is 50" → SUPPORTS
  - "X is 75 to 80%" vs claim "X is 75% to 80%" → SUPPORTS (same range)
  - "X is 0 or 30" vs claim "X can be 0 or 30" → SUPPORTS (all options mentioned)
  - "X supports A, B, C" vs claim "X supports A, B, and C" → SUPPORTS

**PARTIAL** - Use this status when:
- The assertion states ONE value, but claims show MULTIPLE valid values
- The assertion is missing some valid alternatives mentioned in claims
- Examples of partial:
  - "X is 30" vs claim "X is 0 or 30" → PARTIAL (missing the 0 option)
  - "X supports A" vs claim "X supports A, B, and C" → PARTIAL (missing B and C)

CRITICAL RULES:
1. If assertion value MATCHES claim value exactly or equivalently = SUPPORTS
2. If assertion covers ALL values/options from claims = SUPPORTS
3. If assertion has ONE value but claims have MULTIPLE = PARTIAL
4. If assertion value is DIFFERENT from claim value = CONTRADICTS

Return ONLY a JSON object (no surrounding text):
{{
  "relationship": "SUPPORTS" or "CONTRADICTS" or "PARTIAL",
  "confidence": 0.0 to 1.0,
  "explanation": "Brief explanation (1-2 sentences)"
}}"""


class EvidenceMatcher:
    """
    Finds evidence for assertions by searching Neo4j claims and Qdrant chunks.

    Strategy V1.1 (Deterministic Comparison):
    1. Embed the assertion
    2. Search similar claims in Neo4j (keyword-based)
    3. Extract structured form of assertion and claims
    4. If structured comparison possible → deterministic comparison
    5. If TEXT_VALUE or fallback needed → LLM comparison
    6. If no claims found → fallback to Qdrant chunks
    """

    SIMILARITY_THRESHOLD = 0.65  # Minimum similarity to consider a match
    NEO4J_CLAIM_LIMIT = 10  # Increased for better coverage
    QDRANT_CHUNK_LIMIT = 5

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        self.settings = get_settings()
        self.embedding_manager = EmbeddingModelManager()
        self.llm_router = get_llm_router()

        # Neo4j client
        self.neo4j_client = Neo4jClient(
            uri=self.settings.neo4j_uri,
            user=self.settings.neo4j_user,
            password=self.settings.neo4j_password
        )

        # V1.1: Deterministic comparison components
        self.comparison_engine = ComparisonEngine()
        self.structured_extractor = StructuredExtractor()
        self.tolerance_policy = TolerancePolicy()
        self.aggregator = AggregatorPolicy()

    async def find_evidence(
        self,
        assertion_text: str
    ) -> Tuple[List[Any], Any, float]:
        """
        Find evidence for an assertion.

        Args:
            assertion_text: The assertion to verify

        Returns:
            Tuple of (evidence list, verification status, confidence score)
        """
        Evidence, VerificationStatus = _get_verification_schemas()

        if not assertion_text or len(assertion_text.strip()) < 5:
            return [], VerificationStatus.UNKNOWN, 0.0

        try:
            # 1. Get embedding for assertion
            embedding = await self._get_embedding(assertion_text)
            if not embedding:
                logger.warning("[EVIDENCE_MATCHER] Failed to get embedding")
                return [], VerificationStatus.UNKNOWN, 0.0

            # 2. Search claims in Neo4j
            claims = await self._search_claims_neo4j(assertion_text, embedding)

            if claims:
                logger.debug(f"[EVIDENCE_MATCHER] Found {len(claims)} claims in Neo4j")
                return await self._analyze_claims(assertion_text, claims)

            # 3. Fallback: search chunks in Qdrant
            chunks = await self._search_qdrant(embedding)

            if chunks:
                logger.debug(f"[EVIDENCE_MATCHER] Fallback to Qdrant: {len(chunks)} chunks")
                evidence = [
                    Evidence(
                        type="chunk",
                        text=chunk.get("text", "")[:500],  # Truncate
                        source_doc=chunk.get("source_file", "unknown"),
                        source_page=chunk.get("page"),
                        source_section=chunk.get("section"),
                        confidence=chunk.get("score", 0.5),
                        relationship="partial"
                    )
                    for chunk in chunks
                ]
                max_score = max(c.get("score", 0) for c in chunks)
                return evidence, VerificationStatus.FALLBACK, max_score

            # 4. Nothing found
            return [], VerificationStatus.UNKNOWN, 0.0

        except Exception as e:
            logger.error(f"[EVIDENCE_MATCHER] Error finding evidence: {e}")
            return [], VerificationStatus.UNKNOWN, 0.0

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding vector for text."""
        try:
            model = self.embedding_manager.get_model()
            embedding = model.encode(text, normalize_embeddings=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"[EVIDENCE_MATCHER] Embedding error: {e}")
            return None

    async def _search_claims_neo4j(
        self,
        text: str,
        embedding: List[float]
    ) -> List[Dict[str, Any]]:
        """
        Search for similar claims in Neo4j.

        Supports both schemas:
        - Claim nodes (Claim-First pipeline)
        - CanonicalClaim nodes (legacy consolidation pipeline)
        """
        if not self.neo4j_client.driver:
            logger.warning("[EVIDENCE_MATCHER] Neo4j driver not connected")
            return []

        try:
            # Extract keywords for text search
            keywords = self._extract_keywords(text)
            logger.debug(f"[EVIDENCE_MATCHER] Searching with keywords: {keywords}")

            database = getattr(self.neo4j_client, 'database', 'neo4j')

            # First try Claim nodes (Claim-First pipeline)
            # Score claims by:
            # 1. Number of matching keywords
            # 2. Bonus for specific keywords (short ones like 'sla' are often more discriminant)
            # 3. Bonus for numeric patterns (like '99', '99.9%')
            query_claim = """
            MATCH (c:Claim {tenant_id: $tenant_id})
            WHERE any(kw IN $keywords WHERE toLower(c.text) CONTAINS toLower(kw))
            WITH c,
                 size([kw IN $keywords WHERE toLower(c.text) CONTAINS toLower(kw)]) AS keyword_score,
                 // Bonus for short keywords (often acronyms like SLA, ERP)
                 size([kw IN $keywords WHERE size(kw) <= 4 AND toLower(c.text) CONTAINS toLower(kw)]) AS acronym_bonus,
                 // Bonus for numeric patterns (SLA percentages are highly relevant)
                 CASE WHEN c.text =~ '.*[0-9]+[.,]?[0-9]*%.*' THEN 5 ELSE 0 END AS number_bonus
            WITH c, keyword_score + acronym_bonus + number_bonus AS total_score
            RETURN
                c.claim_id AS claim_id,
                c.claim_type AS claim_type,
                c.text AS value,
                c.confidence AS confidence,
                'VALIDATED' AS maturity,
                c.doc_id AS doc_id,
                c.verbatim_quote AS verbatim_quote,
                total_score
            ORDER BY total_score DESC, c.confidence DESC
            LIMIT $limit
            """

            with self.neo4j_client.driver.session(database=database) as session:
                result = session.run(query_claim, {
                    "tenant_id": self.tenant_id,
                    "keywords": keywords,
                    "limit": self.NEO4J_CLAIM_LIMIT
                })
                claims = [dict(record) for record in result]

            if claims:
                logger.info(f"[EVIDENCE_MATCHER] Found {len(claims)} Claim nodes")
                return claims

            # Fallback: try CanonicalClaim nodes (legacy)
            query_canonical = """
            MATCH (cc:CanonicalClaim {tenant_id: $tenant_id})
            WHERE cc.status = 'active'
            AND any(kw IN $keywords WHERE toLower(cc.value) CONTAINS toLower(kw))
            OPTIONAL MATCH (subj:Concept {concept_id: cc.subject_concept_id})
            RETURN
                cc.canonical_claim_id AS claim_id,
                cc.claim_type AS claim_type,
                cc.value AS value,
                cc.confidence_p50 AS confidence,
                cc.maturity AS maturity,
                cc.sources_json AS sources_json,
                subj.name AS subject_name
            ORDER BY cc.confidence_p50 DESC
            LIMIT $limit
            """

            with self.neo4j_client.driver.session(database=database) as session:
                result = session.run(query_canonical, {
                    "tenant_id": self.tenant_id,
                    "keywords": keywords,
                    "limit": self.NEO4J_CLAIM_LIMIT
                })
                claims = [dict(record) for record in result]

            if claims:
                logger.info(f"[EVIDENCE_MATCHER] Found {len(claims)} CanonicalClaim nodes")

            return claims

        except Exception as e:
            logger.error(f"[EVIDENCE_MATCHER] Neo4j search error: {e}")
            return []

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text for search."""
        # Simple keyword extraction: words >= 3 chars (for acronyms like SLA, SAP, ERP), not stopwords
        stopwords = {
            "le", "la", "les", "de", "du", "des", "un", "une", "et", "est",
            "en", "que", "qui", "pour", "par", "sur", "avec", "dans", "son",
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "of", "and", "to", "in", "for", "on", "with", "at", "by", "from"
        }

        words = text.lower().split()
        keywords = [
            w.strip(".,;:!?\"'()[]")
            for w in words
            if len(w) >= 3 and w.lower() not in stopwords
        ]

        # Return unique keywords, max 10
        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen and len(kw) >= 3:  # Double check after strip
                seen.add(kw)
                unique.append(kw)
                if len(unique) >= 10:
                    break

        return unique

    async def _search_qdrant(self, embedding: List[float]) -> List[Dict[str, Any]]:
        """Search for similar chunks in Qdrant."""
        try:
            # Search in main collection
            collection = self.settings.qdrant_collection
            results = search_with_tenant_filter(
                collection_name=collection,
                query_vector=embedding,
                tenant_id=self.tenant_id,
                limit=self.QDRANT_CHUNK_LIMIT,
                score_threshold=self.SIMILARITY_THRESHOLD
            )

            # Format results
            chunks = []
            for hit in results:
                payload = hit.get("payload", {})
                chunks.append({
                    "text": payload.get("text", payload.get("content", "")),
                    "source_file": payload.get("source_file", payload.get("document_name", "unknown")),
                    "page": payload.get("page_number", payload.get("page")),
                    "section": payload.get("section", payload.get("heading")),
                    "score": hit.get("score", 0.5)
                })

            return chunks

        except Exception as e:
            logger.error(f"[EVIDENCE_MATCHER] Qdrant search error: {e}")
            return []

    async def _analyze_claims(
        self,
        assertion: str,
        claims: List[Dict[str, Any]]
    ) -> Tuple[List[Any], Any, float]:
        """
        Analyze how claims relate to the assertion.

        V1.1: Uses deterministic comparison when possible, LLM fallback otherwise.

        Returns evidence list, verification status, and confidence.
        """
        Evidence, VerificationStatus = _get_verification_schemas()

        if not claims:
            return [], VerificationStatus.UNKNOWN, 0.0

        # V1.1: Try deterministic comparison first
        try:
            # 1. Extract structured form of assertion
            assertion_form = await self.structured_extractor.extract(
                assertion,
                default_authority=AuthorityLevel.MEDIUM  # User assertion
            )

            # 2. If structured form (not TEXT_VALUE), try deterministic comparison
            if assertion_form and assertion_form.form_type != ClaimFormType.TEXT_VALUE:
                logger.debug(f"[EVIDENCE_MATCHER] Deterministic comparison for: {assertion_form.form_type.value}")
                return await self._deterministic_compare(assertion_form, claims)
            else:
                logger.debug("[EVIDENCE_MATCHER] TEXT_VALUE form, using LLM fallback")

        except Exception as e:
            logger.warning(f"[EVIDENCE_MATCHER] Deterministic extraction failed: {e}, using LLM")

        # 3. Fallback: LLM comparison
        return await self._llm_compare(assertion, claims)

    async def _deterministic_compare(
        self,
        assertion_form: ClaimForm,
        claims: List[Dict[str, Any]]
    ) -> Tuple[List[Any], Any, float]:
        """
        V1.1: Deterministic comparison using structured forms.

        Steps:
        1. Extract structured forms for each claim
        2. Compare assertion vs each claim
        3. Aggregate results using AggregatorPolicy
        4. Build evidence response
        """
        Evidence, VerificationStatus = _get_verification_schemas()

        comparisons: List[ClaimComparison] = []

        for claim in claims:
            # Extract claim text
            claim_text = claim.get("verbatim_quote") or claim.get("value", "")
            if not claim_text:
                continue

            # Infer authority from claim source
            authority = self._infer_authority(claim)

            # Extract structured form
            claim_form = await self.structured_extractor.extract(
                claim_text,
                default_authority=authority
            )

            if not claim_form:
                continue

            # Calculate tolerance
            tolerance = self.tolerance_policy.get_tolerance(
                value_kind=type(assertion_form.value).__name__,
                unit=assertion_form.value.unit,
                regime=assertion_form.truth_regime,
                authority=claim_form.authority,
                hedge_strength=0.0  # Could be extracted from claim
            )

            # Compare
            explanation = self.comparison_engine.compare(
                assertion_form,
                claim_form,
                tolerance=tolerance
            )

            comparisons.append(ClaimComparison(
                claim=claim,
                claim_form=claim_form,
                explanation=explanation,
                authority=authority,
                scope_match_score=1.0 if assertion_form.scope_matches(claim_form) else 0.5
            ))

        if not comparisons:
            logger.debug("[EVIDENCE_MATCHER] No valid claim comparisons, falling back to unknown")
            return [], VerificationStatus.UNKNOWN, 0.0

        # Aggregate results
        aggregated = self.aggregator.aggregate(assertion_form, comparisons)

        # Build evidence response
        return self._build_deterministic_evidence(aggregated, comparisons, claims)

    def _infer_authority(self, claim: Dict[str, Any]) -> AuthorityLevel:
        """
        Infer authority level from claim metadata.

        Rules:
        - Contract, SLA, official spec → HIGH
        - Technical documentation → MEDIUM
        - Marketing, slides → LOW
        """
        doc_id = claim.get("doc_id", "").lower()
        claim_type = claim.get("claim_type", "").lower()

        # HIGH authority indicators
        high_indicators = ["contract", "sla", "spec", "official", "standard", "norm"]
        if any(ind in doc_id for ind in high_indicators):
            return AuthorityLevel.HIGH
        if claim_type in ["sla", "contract", "specification"]:
            return AuthorityLevel.HIGH

        # LOW authority indicators
        low_indicators = ["marketing", "slide", "presentation", "brochure", "note"]
        if any(ind in doc_id for ind in low_indicators):
            return AuthorityLevel.LOW

        return AuthorityLevel.MEDIUM

    def _build_deterministic_evidence(
        self,
        aggregated: Any,  # AggregatedResult
        comparisons: List[ClaimComparison],
        original_claims: List[Dict[str, Any]]
    ) -> Tuple[List[Any], Any, float]:
        """Build evidence response from deterministic comparison."""
        Evidence, VerificationStatus = _get_verification_schemas()

        # Map ComparisonResult to relationship string
        result_to_rel = {
            ComparisonResult.SUPPORTS: "supports",
            ComparisonResult.CONTRADICTS: "contradicts",
            ComparisonResult.PARTIAL: "partial",
            ComparisonResult.NEEDS_SCOPE: "partial",  # UI shows as partial
            ComparisonResult.UNKNOWN: "partial",
        }

        relationship = result_to_rel.get(aggregated.result, "partial")

        # Build evidence list
        evidence = []
        for comp in comparisons:
            claim = comp.claim
            source_doc = self._extract_source_doc(claim)
            source_page = self._extract_source_page(claim)

            # Build evidence text with comparison details
            claim_text = claim.get("verbatim_quote") or claim.get("value", "")
            claim_type = claim.get("claim_type", "?")

            # Add reason code for transparency
            reason_msg = comp.explanation.get_display_reason("fr")

            evidence.append(Evidence(
                type="claim",
                text=f"[{claim_type}] {claim_text}",
                source_doc=source_doc,
                source_page=source_page,
                confidence=comp.explanation.confidence,
                relationship=result_to_rel.get(comp.explanation.result, "partial"),
                # V1.1: Add structured comparison details
                comparison_details={
                    "reason_code": comp.explanation.reason_code.value,
                    "reason_message": reason_msg,
                    "authority": comp.authority.value,
                    "deterministic": True,
                }
            ))

        # Map to verification status
        status_map = {
            ComparisonResult.SUPPORTS: VerificationStatus.CONFIRMED,
            ComparisonResult.CONTRADICTS: VerificationStatus.CONTRADICTED,
            ComparisonResult.PARTIAL: VerificationStatus.INCOMPLETE,
            ComparisonResult.NEEDS_SCOPE: VerificationStatus.INCOMPLETE,
            ComparisonResult.UNKNOWN: VerificationStatus.UNKNOWN,
        }
        status = status_map.get(aggregated.result, VerificationStatus.UNKNOWN)

        return evidence, status, aggregated.confidence

    def _extract_source_doc(self, claim: Dict[str, Any]) -> str:
        """Extract source document from claim."""
        if claim.get("doc_id"):
            return claim.get("doc_id", "unknown")

        sources_json = claim.get("sources_json")
        if sources_json:
            try:
                sources = json.loads(sources_json) if isinstance(sources_json, str) else sources_json
                if sources and len(sources) > 0:
                    return sources[0].get("document_id", "unknown")
            except (json.JSONDecodeError, TypeError):
                pass

        return "unknown"

    def _extract_source_page(self, claim: Dict[str, Any]) -> Optional[int]:
        """Extract source page from claim."""
        sources_json = claim.get("sources_json")
        if sources_json:
            try:
                sources = json.loads(sources_json) if isinstance(sources_json, str) else sources_json
                if sources and len(sources) > 0:
                    return sources[0].get("page_number")
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    async def _llm_compare(
        self,
        assertion: str,
        claims: List[Dict[str, Any]]
    ) -> Tuple[List[Any], Any, float]:
        """
        LLM-based comparison (legacy method, used as fallback).

        Returns evidence list, verification status, and confidence.
        """
        Evidence, VerificationStatus = _get_verification_schemas()

        # Format claims for LLM
        claims_text = ""
        for i, claim in enumerate(claims, 1):
            claim_type = claim.get("claim_type", "info")
            value = claim.get("value", "")
            # Use verbatim_quote if available (Claim-First format)
            verbatim = claim.get("verbatim_quote")
            display_text = verbatim if verbatim else value
            doc_id = claim.get("doc_id", claim.get("subject_name", ""))
            claims_text += f"{i}. [{claim_type}] {display_text}"
            if doc_id:
                claims_text += f" (source: {doc_id})"
            claims_text += "\n"

        prompt = COMPARE_CLAIM_PROMPT.format(
            assertion=assertion,
            claims_text=claims_text
        )

        try:
            response = await self.llm_router.acomplete(
                task_type=TaskType.FAST_CLASSIFICATION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500
            )

            analysis = self._parse_analysis_response(response)

        except Exception as e:
            logger.error(f"[EVIDENCE_MATCHER] LLM analysis error: {e}")
            # Default to partial if LLM fails
            analysis = {
                "relationship": "PARTIAL",
                "confidence": 0.5,
                "explanation": "Analyse automatique non disponible"
            }

        # Convert claims to Evidence objects
        relationship = analysis.get("relationship", "PARTIAL").lower()
        confidence = analysis.get("confidence", 0.5)

        # Map relationship to Evidence relationship field
        rel_map = {
            "supports": "supports",
            "contradicts": "contradicts",
            "partial": "partial"
        }
        evidence_rel = rel_map.get(relationship, "partial")

        evidence = []
        for claim in claims:
            source_doc = self._extract_source_doc(claim)
            source_page = self._extract_source_page(claim)

            # Build evidence text - use verbatim_quote if available, else value
            claim_value = claim.get("value", "")
            verbatim = claim.get("verbatim_quote")
            display_text = verbatim if verbatim else claim_value

            evidence.append(Evidence(
                type="claim",
                text=f"[{claim.get('claim_type', '?')}] {display_text}",
                source_doc=source_doc,
                source_page=source_page,
                confidence=claim.get("confidence", 0.5),
                relationship=evidence_rel,
                # V1.1: Mark as LLM-based
                comparison_details={
                    "reason_code": ReasonCode.LLM_CLASSIFICATION.value,
                    "reason_message": analysis.get("explanation", ""),
                    "deterministic": False,
                }
            ))

        # Determine verification status
        if relationship == "supports":
            status = VerificationStatus.CONFIRMED
        elif relationship == "contradicts":
            status = VerificationStatus.CONTRADICTED
        else:
            status = VerificationStatus.INCOMPLETE

        return evidence, status, confidence

    def _parse_analysis_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response for claim analysis."""
        import re

        # Try to extract JSON
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Fallback: look for keywords
        response_lower = response.lower()
        if "supports" in response_lower or "confirme" in response_lower:
            return {"relationship": "SUPPORTS", "confidence": 0.7}
        elif "contradicts" in response_lower or "contredit" in response_lower:
            return {"relationship": "CONTRADICTS", "confidence": 0.7}
        else:
            return {"relationship": "PARTIAL", "confidence": 0.5}
