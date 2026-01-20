"""
Phase 2.8/2.10 - Relation Consolidator

Consolidates RawAssertions into CanonicalRelations by grouping and computing maturity.

Grouping key: (subject_concept_id, object_concept_id, predicate_norm)
Note: Uses predicate_norm (normalized predicate) instead of relation_type for finer granularity
      and backwards compatibility with RawAssertions that don't have relation_type.

Maturity levels:
- CANDIDATE: Single source
- VALIDATED: 2+ sources with consistent typing
- AMBIGUOUS_TYPE: type_confidence ≈ alt_type_confidence (delta < 0.15)
- CONFLICTING: Contradictory assertions detected
- CONTEXT_DEPENDENT: High conditional ratio (> 0.70)

Author: Claude Code
Date: 2025-12-24
Updated: 2025-12-26 - Use predicate_norm for grouping instead of relation_type
"""

import hashlib
import logging
from collections import defaultdict, Counter
from datetime import datetime
from statistics import mean, median
from typing import Any, Dict, List, Optional, Tuple

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.relations.types import (
    CanonicalRelation,
    RelationMaturity,
    RelationStatus,
    RelationType,
    PredicateProfile,
    # ADR Relations Discursivement Déterminées
    AssertionKind,
    SemanticGrade,
    compute_semantic_grade,
)

logger = logging.getLogger(__name__)


def compute_canonical_relation_id(
    tenant_id: str,
    subject_id: str,
    predicate_norm: str,
    object_id: str
) -> str:
    """
    Compute stable canonical relation ID.

    Args:
        tenant_id: Tenant ID
        subject_id: Subject concept ID
        predicate_norm: Normalized predicate (e.g., "requires", "uses")
        object_id: Object concept ID

    Returns:
        SHA1 hash prefix (16 chars)
    """
    content = f"{tenant_id}|{subject_id}|{predicate_norm}|{object_id}"
    return hashlib.sha1(content.encode()).hexdigest()[:16]


class RelationConsolidator:
    """
    Consolidates RawAssertions into CanonicalRelations.

    Process:
    1. Group RawAssertions by (subject, object, relation_type)
    2. Compute maturity based on source diversity and type confidence
    3. Build predicate profile (top raw predicates)
    4. Generate CanonicalRelation with aggregated metadata
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
            "validated": 0,
            "ambiguous": 0,
            "conflicting": 0
        }

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def fetch_raw_assertions(
        self,
        subject_concept_id: Optional[str] = None,
        object_concept_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        doc_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch RawAssertions from Neo4j for consolidation.

        Args:
            subject_concept_id: Filter by subject (optional)
            object_concept_id: Filter by object (optional)
            relation_type: Filter by type (optional)
            doc_id: Filter by document (optional)

        Returns:
            List of RawAssertion dicts
        """
        where_clauses = ["ra.tenant_id = $tenant_id"]
        params: Dict[str, Any] = {"tenant_id": self.tenant_id}

        if subject_concept_id:
            where_clauses.append("ra.subject_concept_id = $subject_id")
            params["subject_id"] = subject_concept_id

        if object_concept_id:
            where_clauses.append("ra.object_concept_id = $object_id")
            params["object_id"] = object_concept_id

        if relation_type:
            where_clauses.append("ra.relation_type = $relation_type")
            params["relation_type"] = relation_type

        if doc_id:
            where_clauses.append("ra.source_doc_id = $doc_id")
            params["doc_id"] = doc_id

        where_str = " AND ".join(where_clauses)

        query = f"""
        MATCH (ra:RawAssertion)
        WHERE {where_str}
        RETURN ra {{
            .raw_assertion_id,
            .subject_concept_id,
            .object_concept_id,
            .predicate_raw,
            .predicate_norm,
            .relation_type,
            .type_confidence,
            .alt_type,
            .alt_type_confidence,
            .source_doc_id,
            .source_chunk_id,
            .source_segment_id,
            .confidence_final,
            .is_conditional,
            .extractor_version,
            .created_at,
            .assertion_kind
        }} AS assertion
        ORDER BY ra.created_at DESC
        """

        results = self._execute_query(query, params)
        return [r["assertion"] for r in results]

    def group_assertions(
        self,
        assertions: List[Dict[str, Any]]
    ) -> Dict[Tuple[str, str, str], List[Dict[str, Any]]]:
        """
        Group assertions by consolidation key.

        Args:
            assertions: List of RawAssertion dicts

        Returns:
            Dict mapping (subject_id, object_id, predicate_norm) to list of assertions
        """
        groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)

        for assertion in assertions:
            # Use predicate_norm for grouping (more granular, always available)
            predicate_norm = assertion.get("predicate_norm")
            if not predicate_norm:
                # Skip assertions without predicate_norm
                continue

            subject_id = assertion.get("subject_concept_id", "")
            object_id = assertion.get("object_concept_id", "")

            if not subject_id or not object_id:
                # Skip incomplete assertions
                continue

            key = (subject_id, object_id, predicate_norm)
            groups[key].append(assertion)

        return dict(groups)

    def compute_maturity(
        self,
        assertions: List[Dict[str, Any]]
    ) -> RelationMaturity:
        """
        Compute maturity level for a group of assertions.

        Args:
            assertions: List of assertions in the group

        Returns:
            RelationMaturity level
        """
        if not assertions:
            return RelationMaturity.CANDIDATE

        # Count distinct documents
        doc_ids = set(a.get("source_doc_id", "") for a in assertions)
        distinct_docs = len(doc_ids)

        # Check for type ambiguity (Phase 2.10)
        type_confidences = [a.get("type_confidence", 0.0) for a in assertions if a.get("type_confidence")]
        alt_type_confidences = [a.get("alt_type_confidence", 0.0) for a in assertions if a.get("alt_type_confidence")]

        if type_confidences and alt_type_confidences:
            avg_type_conf = mean(type_confidences)
            avg_alt_conf = mean(alt_type_confidences)
            # Ambiguous if delta < 0.15
            if abs(avg_type_conf - avg_alt_conf) < 0.15:
                self._stats["ambiguous"] += 1
                return RelationMaturity.AMBIGUOUS_TYPE

        # Check for high conditional ratio
        conditional_count = sum(1 for a in assertions if a.get("is_conditional", False))
        conditional_ratio = conditional_count / len(assertions) if assertions else 0
        if conditional_ratio > 0.70:
            return RelationMaturity.CONTEXT_DEPENDENT

        # Multi-source = validated
        if distinct_docs >= 2:
            self._stats["validated"] += 1
            return RelationMaturity.VALIDATED

        # Single source = candidate
        return RelationMaturity.CANDIDATE

    def build_predicate_profile(
        self,
        assertions: List[Dict[str, Any]]
    ) -> PredicateProfile:
        """
        Build predicate profile from assertions.

        Args:
            assertions: List of assertions

        Returns:
            PredicateProfile with top predicates
        """
        predicates = [a.get("predicate_raw", "") for a in assertions if a.get("predicate_raw")]
        if not predicates:
            return PredicateProfile()

        # Count predicates
        predicate_counts = Counter(predicates)

        # Get top 5 predicates
        top_predicates = [p for p, _ in predicate_counts.most_common(5)]

        return PredicateProfile(
            top_predicates_raw=top_predicates
        )

    def consolidate_group(
        self,
        key: Tuple[str, str, str],
        assertions: List[Dict[str, Any]]
    ) -> CanonicalRelation:
        """
        Consolidate a group of assertions into a CanonicalRelation.

        Args:
            key: (subject_id, object_id, predicate_norm) tuple
            assertions: List of assertions in the group

        Returns:
            CanonicalRelation instance
        """
        subject_id, object_id, predicate_norm = key

        # Compute maturity
        maturity = self.compute_maturity(assertions)

        # Build predicate profile
        predicate_profile = self.build_predicate_profile(assertions)

        # ADR Relations Discursivement Déterminées - Compteurs de support
        explicit_count = 0
        discursive_count = 0
        for a in assertions:
            kind_str = a.get("assertion_kind")
            if kind_str:
                try:
                    kind = AssertionKind(kind_str) if isinstance(kind_str, str) else kind_str
                    if kind == AssertionKind.EXPLICIT:
                        explicit_count += 1
                    elif kind == AssertionKind.DISCURSIVE:
                        discursive_count += 1
                except ValueError:
                    explicit_count += 1  # Default to EXPLICIT if unknown
            else:
                explicit_count += 1  # Default to EXPLICIT if not set

        # Compute semantic_grade from counters
        semantic_grade = compute_semantic_grade(explicit_count, discursive_count)

        # Aggregate stats
        doc_ids = set(a.get("source_doc_id", "") for a in assertions)
        chunk_ids = set(a.get("source_chunk_id", "") for a in assertions)
        # Comptage des sections distinctes (via source_segment_id)
        segment_ids = set(
            a.get("source_segment_id", "") for a in assertions
            if a.get("source_segment_id")
        )
        distinct_sections = len(segment_ids) if segment_ids else 0
        confidences = [a.get("confidence_final", 0.0) for a in assertions if a.get("confidence_final")]
        extractor_versions = list(set(a.get("extractor_version", "") for a in assertions if a.get("extractor_version")))

        # Get timestamps
        created_dates = []
        for a in assertions:
            dt = a.get("created_at")
            if dt:
                if isinstance(dt, str):
                    try:
                        created_dates.append(datetime.fromisoformat(dt.replace("Z", "+00:00")))
                    except ValueError:
                        pass
                elif isinstance(dt, datetime):
                    created_dates.append(dt)

        first_seen = min(created_dates) if created_dates else datetime.utcnow()
        last_seen = max(created_dates) if created_dates else datetime.utcnow()

        # Compute canonical ID using predicate_norm
        canonical_id = compute_canonical_relation_id(
            self.tenant_id, subject_id, predicate_norm, object_id
        )

        # Infer relation_type from predicate_norm or use explicit if available
        relation_type = self._infer_relation_type(predicate_norm, assertions)

        return CanonicalRelation(
            canonical_relation_id=canonical_id,
            tenant_id=self.tenant_id,
            relation_type=relation_type,
            predicate_norm=predicate_norm,
            subject_concept_id=subject_id,
            object_concept_id=object_id,
            distinct_documents=len(doc_ids),
            distinct_chunks=len(chunk_ids),
            total_assertions=len(assertions),
            first_seen_utc=first_seen,
            last_seen_utc=last_seen,
            extractor_versions=extractor_versions,
            predicate_profile=predicate_profile,
            confidence_mean=mean(confidences) if confidences else 0.0,
            confidence_p50=median(confidences) if confidences else 0.0,
            quality_score=median(confidences) if confidences else 0.0,
            maturity=maturity,
            status=RelationStatus.ACTIVE,
            mapping_version="v2.12",
            last_rebuilt_at=datetime.utcnow(),
            # ADR Relations Discursivement Déterminées
            explicit_support_count=explicit_count,
            discursive_support_count=discursive_count,
            distinct_sections=distinct_sections,
        )

    def _infer_relation_type(
        self,
        predicate_norm: str,
        assertions: List[Dict[str, Any]]
    ) -> RelationType:
        """
        Infer relation type from predicate_norm or explicit relation_type in assertions.

        Args:
            predicate_norm: Normalized predicate
            assertions: List of assertions (may have explicit relation_type)

        Returns:
            RelationType enum value
        """
        # First, check if any assertion has explicit relation_type
        for a in assertions:
            rel_type = a.get("relation_type")
            if rel_type:
                try:
                    return RelationType(rel_type)
                except ValueError:
                    pass

        # Infer from predicate_norm using keyword mapping
        predicate_lower = predicate_norm.lower()

        # Mapping: predicate keywords → RelationType (using existing enum values)
        mapping = {
            # Dependencies
            RelationType.REQUIRES: [
                "requires", "must comply with", "needs", "depends on", "necessitates",
                "is based on", "based on", "derives from", "built on"
            ],
            RelationType.USES: [
                "uses", "utilizes", "employs", "can be used for", "leverages"
            ],

            # Structural
            RelationType.PART_OF: [
                "includes", "include", "contains", "encompasses", "comprises",
                "is part of", "part of", "belongs to"
            ],
            RelationType.SUBTYPE_OF: [
                "is a type of", "type of", "is a kind of", "subtype of"
            ],

            # Integration
            RelationType.INTEGRATES_WITH: [
                "integrates with", "integrates", "connects to", "interfaces with",
                "implements", "implement", "realizes"
            ],
            RelationType.EXTENDS: [
                "extends", "expands", "augments", "enhances", "supplements"
            ],

            # Capabilities
            RelationType.ENABLES: [
                "enables", "provides", "offers", "supplies", "delivers", "allows"
            ],

            # Governance
            RelationType.APPLIES_TO: [
                "applies to", "applies", "is applicable to", "governs", "regulates"
            ],

            # Causality
            RelationType.CAUSES: [
                "causes", "affects", "affect", "impacts", "influences", "can lead to",
                "results in", "leads to"
            ],
            RelationType.PREVENTS: [
                "prevents", "blocks", "stops", "mitigates", "reduces"
            ],

            # Associations
            RelationType.ASSOCIATED_WITH: [
                "is linked to", "is related to", "refers to", "relates to",
                "associated with", "connected to", "involves"
            ],

            # Conflicts
            RelationType.CONFLICTS_WITH: [
                "conflicts with", "contradicts", "opposes"
            ],
        }

        for rel_type, keywords in mapping.items():
            for keyword in keywords:
                if keyword in predicate_lower or predicate_lower in keyword:
                    return rel_type

        # Default fallback for unmapped predicates
        return RelationType.ASSOCIATED_WITH

    def consolidate_all(
        self,
        subject_concept_id: Optional[str] = None,
        object_concept_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        doc_id: Optional[str] = None
    ) -> List[CanonicalRelation]:
        """
        Consolidate all matching RawAssertions into CanonicalRelations.

        Args:
            subject_concept_id: Filter by subject (optional)
            object_concept_id: Filter by object (optional)
            relation_type: Filter by relation type (optional)
            doc_id: Filter by document (optional)

        Returns:
            List of CanonicalRelation instances
        """
        # Fetch assertions
        assertions = self.fetch_raw_assertions(
            subject_concept_id, object_concept_id, relation_type, doc_id
        )
        logger.info(f"[RelationConsolidator] Fetched {len(assertions)} RawAssertions")

        if not assertions:
            return []

        # Group assertions
        groups = self.group_assertions(assertions)
        logger.info(f"[RelationConsolidator] Grouped into {len(groups)} groups")

        # Consolidate each group
        canonical_relations = []
        for key, group_assertions in groups.items():
            self._stats["groups_processed"] += 1
            canonical = self.consolidate_group(key, group_assertions)
            canonical_relations.append(canonical)
            self._stats["canonical_created"] += 1

        logger.info(
            f"[RelationConsolidator] Created {len(canonical_relations)} CanonicalRelations "
            f"(validated={self._stats['validated']}, ambiguous={self._stats['ambiguous']})"
        )

        return canonical_relations

    def get_stats(self) -> Dict[str, int]:
        """Get consolidation statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "groups_processed": 0,
            "canonical_created": 0,
            "validated": 0,
            "ambiguous": 0,
            "conflicting": 0
        }


# Singleton-like access
_consolidator_instance: Optional[RelationConsolidator] = None


def get_relation_consolidator(
    tenant_id: str = "default",
    **kwargs
) -> RelationConsolidator:
    """Get or create RelationConsolidator instance."""
    global _consolidator_instance
    if _consolidator_instance is None or _consolidator_instance.tenant_id != tenant_id:
        _consolidator_instance = RelationConsolidator(tenant_id=tenant_id, **kwargs)
    return _consolidator_instance
