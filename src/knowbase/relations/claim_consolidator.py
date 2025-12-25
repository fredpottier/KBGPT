"""
Phase 2.11 - Claim Consolidator

Consolidates RawClaims into CanonicalClaims by grouping and computing maturity.

Grouping key: (subject_concept_id, claim_type, scope_key)

Maturity levels:
- CANDIDATE: Single source
- VALIDATED: 2+ sources with consistent values
- CONFLICTING: Contradictory values detected
- CONTEXT_DEPENDENT: High conditional ratio
- SUPERSEDED: Replaced by newer version

Author: Claude Code
Date: 2025-12-24
"""

import hashlib
import logging
from collections import defaultdict
from datetime import datetime
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.relations.types import (
    CanonicalClaim,
    ClaimMaturity,
    ClaimSource,
    ClaimValueType,
)

logger = logging.getLogger(__name__)


def compute_canonical_claim_id(
    tenant_id: str,
    subject_concept_id: str,
    claim_type: str,
    scope_key: str
) -> str:
    """
    Compute stable canonical claim ID.

    Args:
        tenant_id: Tenant ID
        subject_concept_id: Subject concept ID
        claim_type: Claim type
        scope_key: Scope key

    Returns:
        SHA1 hash prefix (16 chars)
    """
    content = f"{tenant_id}|{subject_concept_id}|{claim_type}|{scope_key}"
    return hashlib.sha1(content.encode()).hexdigest()[:16]


def values_are_consistent(values: List[str], numeric_values: List[float]) -> bool:
    """
    Check if claim values are consistent.

    For numeric values: within 5% tolerance
    For text values: exact match

    Args:
        values: List of raw values
        numeric_values: List of numeric values (if applicable)

    Returns:
        True if values are consistent
    """
    if not values:
        return True

    # For numeric values
    if numeric_values and len(numeric_values) == len(values):
        valid_nums = [n for n in numeric_values if n is not None]
        if valid_nums:
            min_val, max_val = min(valid_nums), max(valid_nums)
            if max_val > 0:
                # Within 5% tolerance
                return (max_val - min_val) / max_val < 0.05
            return min_val == max_val

    # For text values: check if all are the same
    normalized = [v.strip().lower() for v in values]
    return len(set(normalized)) == 1


def detect_temporal_supersession(claims: List[Dict[str, Any]]) -> Optional[str]:
    """
    Detect if newer claims supersede older ones.

    Looks for temporal hints like version numbers, dates, etc.

    Args:
        claims: List of RawClaim dicts

    Returns:
        ID of superseded claim if detected, None otherwise
    """
    # Sort by creation time
    sorted_claims = sorted(claims, key=lambda c: c.get("created_at", ""))

    # Look for version patterns
    import re
    version_pattern = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")

    versions = []
    for claim in sorted_claims:
        hint = claim.get("valid_time_hint", "") or ""
        match = version_pattern.search(hint)
        if match:
            major, minor = int(match.group(1)), int(match.group(2))
            patch = int(match.group(3)) if match.group(3) else 0
            versions.append((major * 10000 + minor * 100 + patch, claim.get("raw_claim_id")))

    if len(versions) > 1:
        # Sort by version number
        versions.sort()
        # Oldest version is superseded
        return versions[0][1]

    return None


class ClaimConsolidator:
    """
    Consolidates RawClaims into CanonicalClaims.

    Process:
    1. Group RawClaims by (subject, claim_type, scope_key)
    2. Compute maturity based on source diversity and value consistency
    3. Detect conflicts and supersession
    4. Generate CanonicalClaim with aggregated metadata
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialize consolidator.

        Args:
            neo4j_client: Neo4j client instance
            tenant_id: Tenant ID
        """
        if neo4j_client is None:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        self.neo4j_client = neo4j_client
        self.tenant_id = tenant_id

        self._stats = {
            "groups_processed": 0,
            "canonical_created": 0,
            "conflicts_detected": 0,
            "supersessions_detected": 0
        }

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def fetch_raw_claims(
        self,
        subject_concept_id: Optional[str] = None,
        claim_type: Optional[str] = None,
        doc_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch RawClaims from Neo4j for consolidation.

        Args:
            subject_concept_id: Filter by subject (optional)
            claim_type: Filter by claim type (optional)
            doc_id: Filter by document (optional)

        Returns:
            List of RawClaim dicts
        """
        where_clauses = ["rc.tenant_id = $tenant_id"]
        params: Dict[str, Any] = {"tenant_id": self.tenant_id}

        if subject_concept_id:
            where_clauses.append("rc.subject_concept_id = $subject_id")
            params["subject_id"] = subject_concept_id

        if claim_type:
            where_clauses.append("rc.claim_type = $claim_type")
            params["claim_type"] = claim_type

        if doc_id:
            where_clauses.append("rc.source_doc_id = $doc_id")
            params["doc_id"] = doc_id

        where_str = " AND ".join(where_clauses)

        query = f"""
        MATCH (rc:RawClaim)
        WHERE {where_str}
        RETURN rc {{
            .raw_claim_id,
            .subject_concept_id,
            .claim_type,
            .value_raw,
            .value_type,
            .value_numeric,
            .unit,
            .scope_key,
            .scope_struct,
            .valid_time_hint,
            .source_doc_id,
            .evidence_text,
            .page_number,
            .confidence,
            .conditional,
            .created_at
        }} AS claim
        ORDER BY rc.created_at DESC
        """

        results = self._execute_query(query, params)
        return [r["claim"] for r in results]

    def group_claims(
        self,
        claims: List[Dict[str, Any]]
    ) -> Dict[Tuple[str, str, str], List[Dict[str, Any]]]:
        """
        Group claims by consolidation key.

        Args:
            claims: List of RawClaim dicts

        Returns:
            Dict mapping (subject_id, claim_type, scope_key) to list of claims
        """
        groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)

        for claim in claims:
            key = (
                claim.get("subject_concept_id", ""),
                claim.get("claim_type", ""),
                claim.get("scope_key", "")
            )
            groups[key].append(claim)

        return dict(groups)

    def compute_maturity(
        self,
        claims: List[Dict[str, Any]]
    ) -> Tuple[ClaimMaturity, List[str]]:
        """
        Compute maturity level for a group of claims.

        Args:
            claims: List of claims in the group

        Returns:
            Tuple of (maturity level, list of conflicting claim IDs)
        """
        if not claims:
            return ClaimMaturity.CANDIDATE, []

        # Count distinct documents
        doc_ids = set(c.get("source_doc_id", "") for c in claims)
        distinct_docs = len(doc_ids)

        # Get values
        values = [c.get("value_raw", "") for c in claims]
        numeric_values = [c.get("value_numeric") for c in claims]

        # Check for conditionals
        conditional_count = sum(1 for c in claims if c.get("conditional", False))
        conditional_ratio = conditional_count / len(claims) if claims else 0

        # High conditional ratio = context dependent
        if conditional_ratio > 0.7:
            return ClaimMaturity.CONTEXT_DEPENDENT, []

        # Check value consistency
        if not values_are_consistent(values, numeric_values):
            # Values conflict
            self._stats["conflicts_detected"] += 1
            conflicting_ids = [c.get("raw_claim_id", "") for c in claims]
            return ClaimMaturity.CONFLICTING, conflicting_ids

        # Check for supersession
        superseded = detect_temporal_supersession(claims)
        if superseded:
            self._stats["supersessions_detected"] += 1
            return ClaimMaturity.SUPERSEDED, []

        # Multi-source with consistent values = validated
        if distinct_docs >= 2:
            return ClaimMaturity.VALIDATED, []

        # Single source = candidate
        return ClaimMaturity.CANDIDATE, []

    def consolidate_group(
        self,
        key: Tuple[str, str, str],
        claims: List[Dict[str, Any]]
    ) -> CanonicalClaim:
        """
        Consolidate a group of claims into a CanonicalClaim.

        Args:
            key: (subject_id, claim_type, scope_key) tuple
            claims: List of claims in the group

        Returns:
            CanonicalClaim instance
        """
        subject_id, claim_type, scope_key = key

        # Compute maturity
        maturity, conflicts = self.compute_maturity(claims)

        # Aggregate values - use most common or most recent
        values = [c.get("value_raw", "") for c in claims]
        value_counts = defaultdict(int)
        for v in values:
            value_counts[v] += 1
        canonical_value = max(value_counts.keys(), key=lambda v: value_counts[v])

        # Get numeric value and unit from the canonical value claim
        canonical_claim_data = next(
            (c for c in claims if c.get("value_raw") == canonical_value),
            claims[0]
        )
        value_numeric = canonical_claim_data.get("value_numeric")
        unit = canonical_claim_data.get("unit")
        value_type = canonical_claim_data.get("value_type", "text")

        # Parse scope_struct from first claim
        scope_struct = {}
        if claims:
            import json
            scope_json = claims[0].get("scope_struct", "{}")
            if isinstance(scope_json, str):
                try:
                    scope_struct = json.loads(scope_json)
                except json.JSONDecodeError:
                    scope_struct = {}
            elif isinstance(scope_json, dict):
                scope_struct = scope_json

        # Compute aggregates
        doc_ids = set(c.get("source_doc_id", "") for c in claims)
        confidences = [c.get("confidence", 0.0) for c in claims if c.get("confidence")]

        # Build sources list
        sources = []
        for claim in claims[:5]:  # Limit to 5 sources
            sources.append(ClaimSource(
                document_id=claim.get("source_doc_id", ""),
                excerpt=claim.get("evidence_text", "")[:200],
                page_number=claim.get("page_number")
            ))

        # Compute canonical ID
        canonical_id = compute_canonical_claim_id(
            self.tenant_id, subject_id, claim_type, scope_key
        )

        # Get timestamps
        created_dates = [c.get("created_at") for c in claims if c.get("created_at")]
        if created_dates:
            first_seen = min(created_dates)
            last_seen = max(created_dates)
        else:
            first_seen = last_seen = datetime.utcnow()

        # Handle value_type enum
        if isinstance(value_type, str):
            try:
                value_type_enum = ClaimValueType(value_type)
            except ValueError:
                value_type_enum = ClaimValueType.TEXT
        else:
            value_type_enum = value_type

        return CanonicalClaim(
            canonical_claim_id=canonical_id,
            tenant_id=self.tenant_id,
            subject_concept_id=subject_id,
            claim_type=claim_type,
            value=canonical_value,
            value_numeric=value_numeric,
            unit=unit,
            value_type=value_type_enum,
            scope_struct=scope_struct,
            scope_key=scope_key,
            distinct_documents=len(doc_ids),
            total_assertions=len(claims),
            confidence_p50=median(confidences) if confidences else 0.0,
            maturity=maturity,
            conflicts_with=conflicts,
            sources=sources,
            created_at=first_seen if isinstance(first_seen, datetime) else datetime.utcnow(),
            last_seen_utc=last_seen if isinstance(last_seen, datetime) else datetime.utcnow()
        )

    def consolidate_all(
        self,
        subject_concept_id: Optional[str] = None,
        claim_type: Optional[str] = None,
        doc_id: Optional[str] = None
    ) -> List[CanonicalClaim]:
        """
        Consolidate all matching RawClaims into CanonicalClaims.

        Args:
            subject_concept_id: Filter by subject (optional)
            claim_type: Filter by claim type (optional)
            doc_id: Filter by document (optional)

        Returns:
            List of CanonicalClaim instances
        """
        # Fetch claims
        claims = self.fetch_raw_claims(subject_concept_id, claim_type, doc_id)
        logger.info(f"[ClaimConsolidator] Fetched {len(claims)} RawClaims")

        if not claims:
            return []

        # Group claims
        groups = self.group_claims(claims)
        logger.info(f"[ClaimConsolidator] Grouped into {len(groups)} groups")

        # Consolidate each group
        canonical_claims = []
        for key, group_claims in groups.items():
            self._stats["groups_processed"] += 1
            canonical = self.consolidate_group(key, group_claims)
            canonical_claims.append(canonical)
            self._stats["canonical_created"] += 1

        logger.info(
            f"[ClaimConsolidator] Created {len(canonical_claims)} CanonicalClaims "
            f"({self._stats['conflicts_detected']} conflicts, "
            f"{self._stats['supersessions_detected']} supersessions)"
        )

        return canonical_claims

    def get_stats(self) -> Dict[str, int]:
        """Get consolidation statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "groups_processed": 0,
            "canonical_created": 0,
            "conflicts_detected": 0,
            "supersessions_detected": 0
        }


# Singleton-like access
_consolidator_instance: Optional[ClaimConsolidator] = None


def get_claim_consolidator(
    tenant_id: str = "default",
    **kwargs
) -> ClaimConsolidator:
    """Get or create ClaimConsolidator instance."""
    global _consolidator_instance
    if _consolidator_instance is None or _consolidator_instance.tenant_id != tenant_id:
        _consolidator_instance = ClaimConsolidator(tenant_id=tenant_id, **kwargs)
    return _consolidator_instance
