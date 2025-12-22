#!/usr/bin/env python3
"""
Phase 2.8 / 2.10 - Consolidation Relations (RawAssertion → CanonicalRelation)

Implémente le flow de consolidation en 6 étapes:
1. SCAN GROUPS (keyset pagination)
2. STATS SCALAIRES par groupe (+ flags ratios Phase 2.10)
3. ASSIGN CLUSTER (Phase 2.10: priorité relation_type depuis RA)
4. LABEL CLUSTER → relation_type
5. ROLLUP par (subject, object, relation_type)
6. UPSERT CR + LINK RA→CR (micro-batches)

Phase 2.10 additions:
- Priorité relation_type depuis RawAssertion (si disponible)
- Maturité épistémique (negated_ratio, hedged_ratio, conditional_ratio)
- AMBIGUOUS_TYPE pour types ambigus
- Quarantaine ASSOCIATED_WITH (max CANDIDATE)

Usage:
    docker exec knowbase-app python /app/scripts/consolidate_relations.py
    # Options:
    docker exec knowbase-app python /app/scripts/consolidate_relations.py --batch-size 50
    docker exec knowbase-app python /app/scripts/consolidate_relations.py --dry-run

Author: Claude Code + ChatGPT collaboration
Date: 2025-12-21 (updated 2025-12-22)
"""

import hashlib
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from neo4j import GraphDatabase

# Configuration
NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"

# Consolidation params
DEFAULT_BATCH_SIZE = 100
MICRO_BATCH_SIZE = 50
MAPPING_VERSION = "v2.10"  # Phase 2.10 with Type-First + epistemic maturity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# Predicate → RelationType Mapping (MVP: Pattern-based, no clustering)
# =============================================================================

PREDICATE_TYPE_PATTERNS: Dict[str, List[str]] = {
    # STRUCTURELLES
    "PART_OF": [
        r"\bpart\s*of\b", r"\bcomponent\s*of\b", r"\bcontains?\b", r"\bincludes?\b",
        r"\bfait\s*partie\b", r"\bcomposant\b", r"\bcontient\b", r"\binclut\b",
    ],
    "SUBTYPE_OF": [
        r"\bis\s*a\s*type\s*of\b", r"\bis\s*a\s*kind\s*of\b", r"\bsubtype\b",
        r"\binherits?\b", r"\bextends\b", r"\bspecializes?\b",
        r"\best\s*un\s*type\s*de\b", r"\bh[eé]rite\b", r"\bsp[eé]cialise\b",
    ],
    # DÉPENDANCES
    "REQUIRES": [
        r"\brequires?\b", r"\bneeds?\b", r"\bdemands?\b", r"\bmandates?\b",
        r"\bmust\s*have\b", r"\bdepends?\s*on\b", r"\bnecessitates?\b",
        r"\bn[eé]cessite\b", r"\brequiert\b", r"\bexige\b", r"\bd[eé]pend\b",
    ],
    "USES": [
        r"\buses?\b", r"\butilizes?\b", r"\bemploys?\b", r"\bleverages?\b",
        r"\bapplies?\b", r"\bconsumes?\b",
        r"\butilise\b", r"\bemploie\b", r"\bapplique\b",
    ],
    # INTÉGRATIONS
    "INTEGRATES_WITH": [
        r"\bintegrates?\s*with\b", r"\bconnects?\s*to\b", r"\binterfaces?\s*with\b",
        r"\bcommunicates?\s*with\b", r"\binteracts?\s*with\b",
        r"\bs['']?int[eè]gre\b", r"\bse\s*connecte\b", r"\bcommunique\b",
    ],
    "EXTENDS": [
        r"\bextends?\b", r"\benhances?\b", r"\baugments?\b", r"\bbuilds?\s*on\b",
        r"\b[eé]tend\b", r"\bam[eé]liore\b", r"\baugmente\b",
    ],
    # CAPACITÉS
    "ENABLES": [
        r"\benables?\b", r"\ballows?\b", r"\bpermits?\b", r"\bfacilitates?\b",
        r"\bsupports?\b", r"\bprovides?\b", r"\bempowers?\b",
        r"\bpermet\b", r"\bautorise\b", r"\bfacilite\b", r"\bfournit\b",
    ],
    # TEMPORELLES
    "VERSION_OF": [
        r"\bversion\s*of\b", r"\brelease\s*of\b", r"\bupgrade\s*of\b",
        r"\bversion\s*de\b", r"\bmise\s*[àa]\s*jour\b",
    ],
    "PRECEDES": [
        r"\bprecedes?\b", r"\bbefore\b", r"\bprior\s*to\b", r"\bearlier\s*than\b",
        r"\bpr[eé]c[eè]de\b", r"\bavant\b", r"\bant[eé]rieur\b",
    ],
    "REPLACES": [
        r"\breplaces?\b", r"\bsupersedes?\b", r"\bsubstitutes?\b",
        r"\bremplace\b", r"\bsucc[eè]de\b", r"\bsubstitue\b",
    ],
    "DEPRECATES": [
        r"\bdeprecates?\b", r"\bobsoletes?\b", r"\bphases?\s*out\b",
        r"\bd[eé]pr[eé]cie\b", r"\bobsol[eè]te\b",
    ],
    # VARIANTES
    "ALTERNATIVE_TO": [
        r"\balternative\s*to\b", r"\binstead\s*of\b", r"\breplacement\s*for\b",
        r"\bcompetes?\s*with\b", r"\brival\s*of\b",
        r"\balternative\s*[àa]\b", r"\bau\s*lieu\s*de\b", r"\bconcurrence\b",
    ],
    # GOUVERNANCE
    "APPLIES_TO": [
        r"\bapplies?\s*to\b", r"\bgoverns?\b", r"\bregulates?\b", r"\baffects?\b",
        r"\btargets?\b", r"\bcovers?\b", r"\bconcerns?\b",
        r"\bs['']?applique\b", r"\bgouverné?\b", r"\br[eé]gule\b", r"\bconcerne\b",
    ],
    "CAUSES": [
        r"\bcauses?\b", r"\bleads?\s*to\b", r"\bresults?\s*in\b", r"\btriggers?\b",
        r"\bproduces?\b", r"\bgenerates?\b", r"\binduces?\b",
        r"\bcause\b", r"\bentra[iî]ne\b", r"\bprovoque\b", r"\bg[eé]n[eè]re\b",
    ],
    # Faible/Neutre
    "ASSOCIATED_WITH": [
        r"\bassociated\s*with\b", r"\brelated\s*to\b", r"\blinked\s*to\b",
        r"\bconnected\s*to\b", r"\bcorrelated\s*with\b",
        r"\bassoci[eé]\s*[àa]\b", r"\bli[eé]\s*[àa]\b", r"\ben\s*rapport\b",
    ],
}

# Compiled patterns for perf
COMPILED_PATTERNS: Dict[str, List[re.Pattern]] = {
    rel_type: [re.compile(p, re.IGNORECASE) for p in patterns]
    for rel_type, patterns in PREDICATE_TYPE_PATTERNS.items()
}

# Definitional cues for STRONG_SINGLE validation
DEFINITIONAL_CUES = [
    re.compile(p, re.IGNORECASE) for p in [
        r"is defined as", r"means\b", r"refers to", r"désigne", r"définit",
        r"is a type of", r"est un type de", r"consiste en",
    ]
]


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class PredicateGroup:
    """Groupe Niveau A: (subject, object, predicate_norm)"""
    tenant_id: str
    subject_concept_id: str
    object_concept_id: str
    predicate_norm: str

    # Stats (from query 7.2)
    total_assertions: int = 0
    distinct_docs: int = 0
    distinct_chunks: int = 0
    conf_mean: float = 0.0
    conf_p50: float = 0.0
    quality_mean: float = 0.0
    first_seen_utc: Optional[datetime] = None
    last_seen_utc: Optional[datetime] = None

    # Phase 2.10 - Flag ratios for epistemic maturity
    negated_ratio: float = 0.0
    hedged_ratio: float = 0.0
    conditional_ratio: float = 0.0

    # Phase 2.10 - Type from RawAssertion (if available)
    relation_type_from_ra: Optional[str] = None
    type_confidence_from_ra: Optional[float] = None
    alt_type_from_ra: Optional[str] = None
    alt_type_confidence_from_ra: Optional[float] = None

    # Clustering (MVP: direct mapping OR from RA)
    predicate_cluster_id: Optional[str] = None
    relation_type: str = "UNKNOWN"
    cluster_label_confidence: float = 0.0

    # Phase 2.10 - Ambiguity flag
    is_ambiguous_type: bool = False


@dataclass
class CanonicalRelationData:
    """Données pour création CanonicalRelation (Niveau B)"""
    canonical_relation_id: str
    tenant_id: str
    subject_concept_id: str
    object_concept_id: str
    relation_type: str

    # Agrégation depuis predicate groups
    distinct_documents: int = 0
    distinct_chunks: int = 0
    total_assertions: int = 0
    first_seen_utc: Optional[datetime] = None
    last_seen_utc: Optional[datetime] = None

    # Scores agrégés
    confidence_mean: float = 0.0
    confidence_p50: float = 0.0
    quality_score: float = 0.0

    # Predicate profile
    top_predicates_raw: List[str] = field(default_factory=list)
    predicate_cluster_id: Optional[str] = None
    cluster_label_confidence: float = 0.0

    # Maturité
    maturity: str = "CANDIDATE"

    # Predicate groups inclus (pour linking RA→CR)
    predicate_groups: List[PredicateGroup] = field(default_factory=list)


# =============================================================================
# Mapping Functions
# =============================================================================

def map_predicate_to_type(predicate_norm: str) -> Tuple[str, float]:
    """
    MVP: Map predicate_norm → relation_type via patterns.

    Returns:
        (relation_type, confidence)
    """
    for rel_type, patterns in COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(predicate_norm):
                return rel_type, 0.85  # Pattern match confidence

    return "UNKNOWN", 0.0


# Phase 2.10 - Core relation types (for validation)
CORE_RELATION_TYPES_V4 = {
    "PART_OF", "SUBTYPE_OF",  # Structurel
    "REQUIRES", "ENABLES", "USES", "INTEGRATES_WITH", "APPLIES_TO",  # Dépendance
    "CAUSES", "PREVENTS",  # Causalité
    "VERSION_OF", "REPLACES",  # Temporel
    "ASSOCIATED_WITH",  # Fallback
}

# Ambiguity threshold
AMBIGUITY_DELTA_THRESHOLD = 0.15


def determine_relation_type_v4(
    predicate_norm: str,
    stats_data: Dict[str, Any]
) -> Tuple[str, float, bool]:
    """
    Phase 2.10 - Determine relation_type with priority: RA > regex.

    Also detects ambiguity (type_confidence ≈ alt_type_confidence).

    Args:
        predicate_norm: Normalized predicate
        stats_data: Stats from query 7.2 (includes relation_types_from_ra)

    Returns:
        (relation_type, confidence, is_ambiguous)
    """
    # Priority 1: Try to get relation_type from RawAssertion (V4 extraction)
    relation_types_from_ra = stats_data.get("relation_types_from_ra", [])
    type_confidence = stats_data.get("avg_type_confidence")
    alt_types_from_ra = stats_data.get("alt_types_from_ra", [])
    alt_type_confidence = stats_data.get("avg_alt_type_confidence")

    # Filter out None values from lists
    relation_types_from_ra = [t for t in relation_types_from_ra if t]
    alt_types_from_ra = [t for t in alt_types_from_ra if t]

    if relation_types_from_ra:
        # Get most common relation_type from RA
        relation_type = relation_types_from_ra[0]

        # Validate it's a known type
        if relation_type not in CORE_RELATION_TYPES_V4:
            # Fallback to regex if type is invalid
            return map_predicate_to_type(predicate_norm) + (False,)

        # Check for ambiguity (delta < threshold)
        is_ambiguous = False
        if type_confidence is not None and alt_type_confidence is not None:
            delta = abs(type_confidence - alt_type_confidence)
            if delta < AMBIGUITY_DELTA_THRESHOLD:
                is_ambiguous = True

        return relation_type, type_confidence or 0.85, is_ambiguous

    # Priority 2: Fallback to regex mapping (V2 style)
    rel_type, confidence = map_predicate_to_type(predicate_norm)
    return rel_type, confidence, False


def get_cluster_id(predicate_norm: str, relation_type: str) -> str:
    """Generate a simple cluster ID (MVP: based on relation_type)."""
    content = f"{relation_type}:{predicate_norm}"
    return f"pred_cluster_{hashlib.sha1(content.encode()).hexdigest()[:8]}"


def has_definitional_cue(evidence_text: str) -> bool:
    """Check if evidence contains definitional cues."""
    for pattern in DEFINITIONAL_CUES:
        if pattern.search(evidence_text):
            return True
    return False


def compute_maturity(
    group: PredicateGroup,
    has_negated: bool = False,
    has_hedged: bool = False,
    cross_sentence: bool = False,
    sample_evidence: str = ""
) -> str:
    """
    Compute maturity based on R8 rules + Phase 2.10 epistemic maturity.

    Phase 2.10 additions:
    - negated_ratio > 0.20 → CONFLICTING
    - conditional_ratio > 0.70 → CONTEXT_DEPENDENT
    - hedged_ratio > 0.50 → block VALIDATED
    - is_ambiguous_type → AMBIGUOUS_TYPE
    - relation_type == ASSOCIATED_WITH → max CANDIDATE

    Args:
        group: Predicate group with stats
        has_negated: Any assertion is negated
        has_hedged: Any assertion is hedged
        cross_sentence: Any assertion is cross-sentence
        sample_evidence: Sample evidence for definitional check

    Returns:
        Maturity status
    """
    # Phase 2.10 - AMBIGUOUS_TYPE (from ambiguity flag)
    if group.is_ambiguous_type:
        return "AMBIGUOUS_TYPE"

    # Phase 2.10 - CONFLICTING (negated_ratio > 0.20)
    if group.negated_ratio > 0.20:
        return "CONFLICTING"

    # Phase 2.10 - CONTEXT_DEPENDENT (conditional_ratio > 0.70)
    if group.conditional_ratio > 0.70:
        return "CONTEXT_DEPENDENT"

    # Phase 2.10 - Quarantine ASSOCIATED_WITH (max CANDIDATE)
    if group.relation_type == "ASSOCIATED_WITH":
        # Can never be VALIDATED
        if group.total_assertions == 1 and group.conf_p50 < 0.45:
            return "REJECTED"
        return "CANDIDATE"

    # Phase 2.10 - hedged_ratio > 0.50 blocks VALIDATED
    block_validated = group.hedged_ratio > 0.50

    # VALIDATED via diversity + confidence (unless blocked)
    if not block_validated:
        if group.distinct_docs >= 2 and group.conf_p50 >= 0.70:
            return "VALIDATED"

        if group.distinct_chunks >= 3 and group.conf_p50 >= 0.75:
            return "VALIDATED"

        # STRONG_SINGLE: définition explicite
        if (group.total_assertions == 1
                and group.conf_p50 >= 0.95
                and not cross_sentence
                and not has_negated
                and not has_hedged
                and has_definitional_cue(sample_evidence)):
            return "VALIDATED"

    # REJECTED si trop faible
    if group.total_assertions == 1 and group.conf_p50 < 0.45:
        return "REJECTED"

    return "CANDIDATE"


def compute_canonical_id(
    tenant_id: str,
    subject_id: str,
    relation_type: str,
    object_id: str
) -> str:
    """Generate canonical_relation_id: sha1(tenant|subject|type|object)[:16]"""
    content = f"{tenant_id}|{subject_id}|{relation_type}|{object_id}"
    return f"cr_{hashlib.sha1(content.encode()).hexdigest()[:16]}"


# =============================================================================
# Neo4j Queries (from spec 7.x)
# =============================================================================

def query_7_1_list_groups(
    session,
    tenant_id: str,
    cursor: Tuple[Optional[str], Optional[str], Optional[str]],
    batch_size: int
) -> List[Dict[str, str]]:
    """
    Query 7.1 - List groups with keyset pagination.

    Args:
        session: Neo4j session
        tenant_id: Tenant ID
        cursor: (last_subject_id, last_object_id, last_predicate_norm)
        batch_size: Number of groups to fetch

    Returns:
        List of group dicts
    """
    last_subject, last_object, last_predicate = cursor

    query = """
    MATCH (ra:RawAssertion {tenant_id: $tenant_id})
    WITH DISTINCT
      ra.subject_concept_id AS subject_id,
      ra.object_concept_id AS object_id,
      ra.predicate_norm AS predicate_norm
    WHERE
      $last_subject IS NULL OR
      subject_id > $last_subject OR
      (subject_id = $last_subject AND object_id > $last_object) OR
      (subject_id = $last_subject AND object_id = $last_object AND predicate_norm > $last_predicate)
    RETURN subject_id, object_id, predicate_norm
    ORDER BY subject_id, object_id, predicate_norm
    LIMIT $batch_size
    """

    result = session.run(
        query,
        tenant_id=tenant_id,
        last_subject=last_subject,
        last_object=last_object,
        last_predicate=last_predicate,
        batch_size=batch_size
    )

    return [dict(r) for r in result]


def query_7_2_stats(
    session,
    tenant_id: str,
    subject_id: str,
    object_id: str,
    predicate_norm: str
) -> Dict[str, Any]:
    """
    Query 7.2 - Stats scalaires for one group.

    Phase 2.10: Includes flag ratios and relation_type from RA.

    Returns:
        Dict with stats
    """
    query = """
    MATCH (ra:RawAssertion {tenant_id: $tenant_id})
    WHERE ra.subject_concept_id = $subject_id
      AND ra.object_concept_id = $object_id
      AND ra.predicate_norm = $predicate_norm
    WITH
      count(ra) AS total_assertions,
      count(DISTINCT ra.source_doc_id) AS distinct_docs,
      count(DISTINCT ra.source_chunk_id) AS distinct_chunks,
      avg(ra.confidence_final) AS conf_mean,
      percentileCont(ra.confidence_final, 0.5) AS conf_p50,
      min(ra.created_at) AS first_seen_utc,
      max(ra.created_at) AS last_seen_utc,
      avg(1.0 + ra.quality_penalty) AS quality_mean,
      // Phase 2.10 - Flag ratios
      toFloat(sum(CASE WHEN ra.is_negated THEN 1 ELSE 0 END)) / count(ra) AS negated_ratio,
      toFloat(sum(CASE WHEN ra.is_hedged THEN 1 ELSE 0 END)) / count(ra) AS hedged_ratio,
      toFloat(sum(CASE WHEN ra.is_conditional THEN 1 ELSE 0 END)) / count(ra) AS conditional_ratio,
      // Phase 2.10 - Relation type from RA (if available)
      collect(DISTINCT ra.relation_type) AS relation_types_from_ra,
      avg(ra.type_confidence) AS avg_type_confidence,
      // Alt type for ambiguity detection
      collect(DISTINCT ra.alt_type) AS alt_types_from_ra,
      avg(ra.alt_type_confidence) AS avg_alt_type_confidence
    RETURN
      total_assertions,
      distinct_docs,
      distinct_chunks,
      conf_mean,
      conf_p50,
      first_seen_utc,
      last_seen_utc,
      quality_mean,
      negated_ratio,
      hedged_ratio,
      conditional_ratio,
      relation_types_from_ra,
      avg_type_confidence,
      alt_types_from_ra,
      avg_alt_type_confidence
    """

    result = session.run(
        query,
        tenant_id=tenant_id,
        subject_id=subject_id,
        object_id=object_id,
        predicate_norm=predicate_norm
    )

    record = result.single()
    if record:
        return dict(record)
    return {}


def query_7_4a_upsert_cr(
    session,
    tenant_id: str,
    cr: CanonicalRelationData
) -> None:
    """
    Query 7.4a - Upsert CanonicalRelation + RELATES edges.
    """
    query = """
    MATCH (s:CanonicalConcept {tenant_id: $tenant_id, concept_id: $subject_id})
    MATCH (o:CanonicalConcept {tenant_id: $tenant_id, concept_id: $object_id})
    MERGE (cr:CanonicalRelation {tenant_id: $tenant_id, canonical_relation_id: $cr_id})
    SET cr += {
      relation_type: $relation_type,
      subject_concept_id: $subject_id,
      object_concept_id: $object_id,
      distinct_documents: $distinct_documents,
      distinct_chunks: $distinct_chunks,
      total_assertions: $total_assertions,
      first_seen_utc: $first_seen_utc,
      last_seen_utc: $last_seen_utc,
      confidence_mean: $confidence_mean,
      confidence_p50: $confidence_p50,
      quality_score: $quality_score,
      predicate_cluster_id: $predicate_cluster_id,
      cluster_label_confidence: $cluster_label_confidence,
      top_predicates_raw: $top_predicates_raw,
      maturity: $maturity,
      status: 'ACTIVE',
      mapping_version: $mapping_version,
      last_rebuilt_at: datetime()
    }
    MERGE (cr)-[:RELATES_FROM]->(s)
    MERGE (cr)-[:RELATES_TO]->(o)
    """

    session.run(
        query,
        tenant_id=tenant_id,
        cr_id=cr.canonical_relation_id,
        subject_id=cr.subject_concept_id,
        object_id=cr.object_concept_id,
        relation_type=cr.relation_type,
        distinct_documents=cr.distinct_documents,
        distinct_chunks=cr.distinct_chunks,
        total_assertions=cr.total_assertions,
        first_seen_utc=cr.first_seen_utc.isoformat() if cr.first_seen_utc else None,
        last_seen_utc=cr.last_seen_utc.isoformat() if cr.last_seen_utc else None,
        confidence_mean=cr.confidence_mean,
        confidence_p50=cr.confidence_p50,
        quality_score=cr.quality_score,
        predicate_cluster_id=cr.predicate_cluster_id,
        cluster_label_confidence=cr.cluster_label_confidence,
        top_predicates_raw=cr.top_predicates_raw,
        maturity=cr.maturity,
        mapping_version=MAPPING_VERSION
    )


def query_7_4b1_fetch_ra_ids(
    session,
    tenant_id: str,
    subject_id: str,
    object_id: str,
    predicate_norm: str,
    last_ra_id: Optional[str],
    micro_batch_size: int
) -> List[str]:
    """
    Query 7.4b step 1 - Fetch RA ids for one predicate group (keyset).
    """
    query = """
    MATCH (ra:RawAssertion {tenant_id: $tenant_id})
    WHERE ra.subject_concept_id = $subject_id
      AND ra.object_concept_id = $object_id
      AND ra.predicate_norm = $predicate_norm
      AND ($last_ra_id IS NULL OR ra.raw_assertion_id > $last_ra_id)
    RETURN ra.raw_assertion_id AS ra_id
    ORDER BY ra.raw_assertion_id
    LIMIT $micro_batch_size
    """

    result = session.run(
        query,
        tenant_id=tenant_id,
        subject_id=subject_id,
        object_id=object_id,
        predicate_norm=predicate_norm,
        last_ra_id=last_ra_id,
        micro_batch_size=micro_batch_size
    )

    return [r["ra_id"] for r in result]


def query_7_4b2_link_ra_cr(
    session,
    tenant_id: str,
    cr_id: str,
    ra_ids: List[str]
) -> None:
    """
    Query 7.4b step 2 - Link micro-batch RA → CR.
    """
    query = """
    MATCH (cr:CanonicalRelation {tenant_id: $tenant_id, canonical_relation_id: $cr_id})
    UNWIND $ra_ids AS ra_id
    MATCH (ra:RawAssertion {tenant_id: $tenant_id, raw_assertion_id: ra_id})
    MERGE (ra)-[:CONSOLIDATED_INTO]->(cr)
    """

    session.run(
        query,
        tenant_id=tenant_id,
        cr_id=cr_id,
        ra_ids=ra_ids
    )


# =============================================================================
# Phase 2.10 - Direct Edge Materialization (VALIDATED only)
# =============================================================================

def query_materialize_direct_edge(
    session,
    tenant_id: str,
    cr: "CanonicalRelationData"
) -> bool:
    """
    Create a direct edge between concepts for navigation.

    Only for VALIDATED relations (not ASSOCIATED_WITH).
    Uses a generic RELATED edge with properties from CR.

    Returns:
        True if edge created, False otherwise
    """
    # Skip ASSOCIATED_WITH (quarantine) and non-VALIDATED
    if cr.maturity != "VALIDATED":
        return False
    if cr.relation_type == "ASSOCIATED_WITH":
        return False

    query = """
    MATCH (s:CanonicalConcept {tenant_id: $tenant_id, canonical_id: $subject_id})
    MATCH (o:CanonicalConcept {tenant_id: $tenant_id, canonical_id: $object_id})
    MERGE (s)-[r:RELATED {relation_type: $relation_type}]->(o)
    SET r += {
        canonical_relation_id: $cr_id,
        confidence_p50: $confidence_p50,
        total_assertions: $total_assertions,
        distinct_documents: $distinct_documents,
        maturity: $maturity,
        created_at: datetime()
    }
    RETURN count(r) > 0 AS created
    """

    result = session.run(
        query,
        tenant_id=tenant_id,
        cr_id=cr.canonical_relation_id,
        subject_id=cr.subject_concept_id,
        object_id=cr.object_concept_id,
        relation_type=cr.relation_type,
        confidence_p50=cr.confidence_p50,
        total_assertions=cr.total_assertions,
        distinct_documents=cr.distinct_documents,
        maturity=cr.maturity
    )

    record = result.single()
    return record["created"] if record else False


def materialize_direct_edges(
    session,
    tenant_id: str,
    canonical_relations: List["CanonicalRelationData"]
) -> Dict[str, int]:
    """
    Phase 2.10 - Create direct RELATED edges for VALIDATED CanonicalRelations.

    These edges enable fast navigation between concepts without
    traversing through CR nodes.

    Args:
        session: Neo4j session
        tenant_id: Tenant ID
        canonical_relations: List of CR data

    Returns:
        Stats dict with edges_created, edges_skipped
    """
    stats = {
        "edges_created": 0,
        "edges_skipped_not_validated": 0,
        "edges_skipped_associated_with": 0,
    }

    for cr in canonical_relations:
        if cr.maturity != "VALIDATED":
            stats["edges_skipped_not_validated"] += 1
            continue
        if cr.relation_type == "ASSOCIATED_WITH":
            stats["edges_skipped_associated_with"] += 1
            continue

        try:
            created = query_materialize_direct_edge(session, tenant_id, cr)
            if created:
                stats["edges_created"] += 1
        except Exception as e:
            logger.warning(f"[CONSOLIDATION] Failed to create direct edge for {cr.canonical_relation_id}: {e}")

    logger.info(
        f"[CONSOLIDATION] Direct edges: {stats['edges_created']} created, "
        f"{stats['edges_skipped_not_validated']} skipped (not VALIDATED), "
        f"{stats['edges_skipped_associated_with']} skipped (ASSOCIATED_WITH)"
    )

    return stats


# =============================================================================
# Rollup Logic
# =============================================================================

def rollup_by_type(
    predicate_groups: List[PredicateGroup],
    tenant_id: str
) -> List[CanonicalRelationData]:
    """
    Rollup predicate groups → CanonicalRelations by (subject, object, relation_type).

    Args:
        predicate_groups: List of enriched predicate groups
        tenant_id: Tenant ID

    Returns:
        List of CanonicalRelationData ready for upsert
    """
    # Group by (subject, object, relation_type)
    cr_map: Dict[str, CanonicalRelationData] = {}

    for pg in predicate_groups:
        key = f"{pg.subject_concept_id}|{pg.object_concept_id}|{pg.relation_type}"

        if key not in cr_map:
            cr_id = compute_canonical_id(
                tenant_id,
                pg.subject_concept_id,
                pg.relation_type,
                pg.object_concept_id
            )
            cr_map[key] = CanonicalRelationData(
                canonical_relation_id=cr_id,
                tenant_id=tenant_id,
                subject_concept_id=pg.subject_concept_id,
                object_concept_id=pg.object_concept_id,
                relation_type=pg.relation_type,
                predicate_cluster_id=pg.predicate_cluster_id,
                cluster_label_confidence=pg.cluster_label_confidence,
            )

        cr = cr_map[key]

        # Aggregate stats
        cr.total_assertions += pg.total_assertions
        cr.distinct_documents += pg.distinct_docs  # Note: will be max-ed
        cr.distinct_chunks += pg.distinct_chunks

        # Update timestamps
        if pg.first_seen_utc:
            if cr.first_seen_utc is None or pg.first_seen_utc < cr.first_seen_utc:
                cr.first_seen_utc = pg.first_seen_utc
        if pg.last_seen_utc:
            if cr.last_seen_utc is None or pg.last_seen_utc > cr.last_seen_utc:
                cr.last_seen_utc = pg.last_seen_utc

        # Track predicates for top_predicates_raw
        if pg.predicate_norm not in cr.top_predicates_raw:
            cr.top_predicates_raw.append(pg.predicate_norm)

        # Add predicate group for linking
        cr.predicate_groups.append(pg)

    # Final pass: compute aggregated scores and maturity
    for cr in cr_map.values():
        if cr.predicate_groups:
            # Weighted average of confidence scores
            total_weight = sum(pg.total_assertions for pg in cr.predicate_groups)
            if total_weight > 0:
                cr.confidence_mean = sum(
                    pg.conf_mean * pg.total_assertions
                    for pg in cr.predicate_groups
                ) / total_weight
                cr.confidence_p50 = sum(
                    pg.conf_p50 * pg.total_assertions
                    for pg in cr.predicate_groups
                ) / total_weight
                cr.quality_score = max(0.0, min(1.0, sum(
                    pg.quality_mean * pg.total_assertions
                    for pg in cr.predicate_groups
                ) / total_weight))

            # Limit top predicates
            cr.top_predicates_raw = cr.top_predicates_raw[:5]

            # Compute maturity from best predicate group
            best_pg = max(cr.predicate_groups, key=lambda pg: pg.conf_p50)
            cr.maturity = compute_maturity(best_pg)

    return list(cr_map.values())


# =============================================================================
# Main Consolidation Flow
# =============================================================================

def consolidate_relations(
    uri: str,
    user: str,
    password: str,
    tenant_id: str = "default",
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    materialize_edges: bool = True  # Phase 2.10: Create direct edges for VALIDATED
) -> Dict[str, int]:
    """
    Main consolidation flow (6 steps from spec section 8 + Phase 2.10).

    Args:
        uri: Neo4j URI
        user: Neo4j user
        password: Neo4j password
        tenant_id: Tenant ID
        batch_size: Number of groups per batch
        dry_run: If True, don't write to Neo4j
        materialize_edges: Phase 2.10 - Create direct RELATED edges for VALIDATED CRs

    Returns:
        Stats dict
    """
    stats = {
        "groups_scanned": 0,
        "canonical_relations_created": 0,
        "canonical_relations_updated": 0,
        "ra_linked": 0,
        "unknown_predicates": 0,
        "errors": 0,
        # Phase 2.10 - Maturity stats
        "maturity_validated": 0,
        "maturity_candidate": 0,
        "maturity_rejected": 0,
        "maturity_conflicting": 0,
        "maturity_ambiguous_type": 0,
        "maturity_context_dependent": 0,
        # Phase 2.10 - Type source stats
        "types_from_ra": 0,
        "types_from_regex": 0,
    }

    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            logger.info(f"[CONSOLIDATION] Starting for tenant: {tenant_id}")

            # Step 1: SCAN GROUPS (keyset pagination)
            cursor: Tuple[Optional[str], Optional[str], Optional[str]] = (None, None, None)
            all_predicate_groups: List[PredicateGroup] = []

            while True:
                groups = query_7_1_list_groups(session, tenant_id, cursor, batch_size)
                if not groups:
                    break

                logger.info(f"[CONSOLIDATION] Processing batch of {len(groups)} groups...")

                for g in groups:
                    # Step 2: STATS SCALAIRES (+ Phase 2.10 flag ratios)
                    stats_data = query_7_2_stats(
                        session,
                        tenant_id,
                        g["subject_id"],
                        g["object_id"],
                        g["predicate_norm"]
                    )

                    # Step 3: ASSIGN CLUSTER (Phase 2.10: priority RA > regex)
                    relation_type, confidence, is_ambiguous = determine_relation_type_v4(
                        g["predicate_norm"],
                        stats_data
                    )

                    # Phase 2.10 - Extract flag ratios
                    negated_ratio = stats_data.get("negated_ratio", 0.0) or 0.0
                    hedged_ratio = stats_data.get("hedged_ratio", 0.0) or 0.0
                    conditional_ratio = stats_data.get("conditional_ratio", 0.0) or 0.0

                    # Phase 2.10 - Extract RA type info
                    relation_types_from_ra = stats_data.get("relation_types_from_ra", [])
                    relation_type_from_ra = relation_types_from_ra[0] if relation_types_from_ra and relation_types_from_ra[0] else None
                    type_confidence_from_ra = stats_data.get("avg_type_confidence")
                    alt_types_from_ra = stats_data.get("alt_types_from_ra", [])
                    alt_type_from_ra = alt_types_from_ra[0] if alt_types_from_ra and alt_types_from_ra[0] else None
                    alt_type_confidence_from_ra = stats_data.get("avg_alt_type_confidence")

                    # Step 4: Build enriched group
                    pg = PredicateGroup(
                        tenant_id=tenant_id,
                        subject_concept_id=g["subject_id"],
                        object_concept_id=g["object_id"],
                        predicate_norm=g["predicate_norm"],
                        total_assertions=stats_data.get("total_assertions", 0),
                        distinct_docs=stats_data.get("distinct_docs", 0),
                        distinct_chunks=stats_data.get("distinct_chunks", 0),
                        conf_mean=stats_data.get("conf_mean", 0.0) or 0.0,
                        conf_p50=stats_data.get("conf_p50", 0.0) or 0.0,
                        quality_mean=stats_data.get("quality_mean", 0.0) or 0.0,
                        first_seen_utc=stats_data.get("first_seen_utc"),
                        last_seen_utc=stats_data.get("last_seen_utc"),
                        # Phase 2.10 - Flag ratios
                        negated_ratio=negated_ratio,
                        hedged_ratio=hedged_ratio,
                        conditional_ratio=conditional_ratio,
                        # Phase 2.10 - RA type info
                        relation_type_from_ra=relation_type_from_ra,
                        type_confidence_from_ra=type_confidence_from_ra,
                        alt_type_from_ra=alt_type_from_ra,
                        alt_type_confidence_from_ra=alt_type_confidence_from_ra,
                        # Clustering
                        predicate_cluster_id=get_cluster_id(g["predicate_norm"], relation_type),
                        relation_type=relation_type,
                        cluster_label_confidence=confidence,
                        # Phase 2.10 - Ambiguity
                        is_ambiguous_type=is_ambiguous,
                    )

                    all_predicate_groups.append(pg)
                    stats["groups_scanned"] += 1

                    if relation_type == "UNKNOWN":
                        stats["unknown_predicates"] += 1

                # Update cursor for next batch
                cursor = (
                    groups[-1]["subject_id"],
                    groups[-1]["object_id"],
                    groups[-1]["predicate_norm"]
                )

            logger.info(f"[CONSOLIDATION] Scanned {stats['groups_scanned']} predicate groups")

            if not all_predicate_groups:
                logger.info("[CONSOLIDATION] No groups to consolidate")
                return stats

            # Step 5: ROLLUP by (subject, object, relation_type)
            canonical_relations = rollup_by_type(all_predicate_groups, tenant_id)
            logger.info(f"[CONSOLIDATION] Created {len(canonical_relations)} CanonicalRelations")

            if dry_run:
                logger.info("[CONSOLIDATION] DRY RUN - skipping writes")
                for cr in canonical_relations[:5]:
                    logger.info(
                        f"  Would create CR: {cr.canonical_relation_id} "
                        f"({cr.relation_type}) - {cr.total_assertions} assertions"
                    )
                return stats

            # Step 6: UPSERT CR + LINK RA→CR
            for cr in canonical_relations:
                try:
                    # 6a. Upsert CR
                    query_7_4a_upsert_cr(session, tenant_id, cr)
                    stats["canonical_relations_created"] += 1

                    # 6b. Link RA → CR (micro-batches)
                    for pg in cr.predicate_groups:
                        ra_cursor: Optional[str] = None
                        while True:
                            ra_ids = query_7_4b1_fetch_ra_ids(
                                session,
                                tenant_id,
                                pg.subject_concept_id,
                                pg.object_concept_id,
                                pg.predicate_norm,
                                ra_cursor,
                                MICRO_BATCH_SIZE
                            )
                            if not ra_ids:
                                break

                            query_7_4b2_link_ra_cr(session, tenant_id, cr.canonical_relation_id, ra_ids)
                            stats["ra_linked"] += len(ra_ids)
                            ra_cursor = ra_ids[-1]

                except Exception as e:
                    logger.error(f"[CONSOLIDATION] Error processing CR {cr.canonical_relation_id}: {e}")
                    stats["errors"] += 1

            # Phase 2.10 - Track maturity stats
            for cr in canonical_relations:
                maturity_key = f"maturity_{cr.maturity.lower()}"
                if maturity_key in stats:
                    stats[maturity_key] += 1

                # Track type source
                if cr.predicate_groups and cr.predicate_groups[0].relation_type_from_ra:
                    stats["types_from_ra"] += 1
                else:
                    stats["types_from_regex"] += 1

            # Phase 2.10 Step 7: Materialize direct edges (optional)
            if materialize_edges:
                logger.info("[CONSOLIDATION] Materializing direct edges for VALIDATED relations...")
                edge_stats = materialize_direct_edges(session, tenant_id, canonical_relations)
                stats["direct_edges_created"] = edge_stats["edges_created"]
                stats["direct_edges_skipped"] = (
                    edge_stats["edges_skipped_not_validated"] +
                    edge_stats["edges_skipped_associated_with"]
                )

            logger.info(f"[CONSOLIDATION] Complete! Stats: {stats}")

    except Exception as e:
        logger.error(f"[CONSOLIDATION] Fatal error: {e}")
        stats["errors"] += 1
    finally:
        if driver:
            driver.close()

    return stats


# =============================================================================
# CLI Entry Point
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 2.8/2.10 - Consolidate RawAssertions → CanonicalRelations")
    parser.add_argument("--tenant", default="default", help="Tenant ID")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Groups per batch")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to Neo4j")
    parser.add_argument("--no-edges", action="store_true", help="Skip direct edge materialization (Phase 2.10)")
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j URI")
    parser.add_argument("--user", default=NEO4J_USER, help="Neo4j user")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j password")

    args = parser.parse_args()

    stats = consolidate_relations(
        uri=args.uri,
        user=args.user,
        password=args.password,
        tenant_id=args.tenant,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        materialize_edges=not args.no_edges  # Phase 2.10
    )

    print("\n=== Consolidation Results ===")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    if stats["errors"] > 0:
        sys.exit(1)
