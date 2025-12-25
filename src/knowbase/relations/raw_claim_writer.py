"""
Phase 2.11 - RawClaim Writer for Neo4j

Writes RawClaim nodes to Neo4j with edges to CanonicalConcept nodes.
Implements append-only, idempotent writes using raw_fingerprint for dedup.

A RawClaim is a unary assertion: Subject → Attribute = Value
Example: "S/4HANA SLA is 99.7%" → subject=S/4HANA, claim_type=SLA_AVAILABILITY, value=99.7%

Author: Claude Code
Date: 2025-12-24
"""

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ulid import ULID

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.relations.types import (
    RawClaim,
    RawClaimFlags,
    ClaimValueType,
)

logger = logging.getLogger(__name__)


def compute_claim_fingerprint(
    tenant_id: str,
    doc_id: str,
    subject_id: str,
    claim_type: str,
    scope_key: str,
    value_raw: str
) -> str:
    """
    Compute fingerprint hash for claim dedup/idempotence.

    Args:
        tenant_id: Tenant ID
        doc_id: Source document ID
        subject_id: Subject concept ID
        claim_type: Type of claim (SLA_AVAILABILITY, etc.)
        scope_key: Canonical scope hash
        value_raw: Raw value string

    Returns:
        SHA1 hash prefix (first 32 chars)
    """
    content = f"{tenant_id}|{doc_id}|{subject_id}|{claim_type}|{scope_key}|{value_raw}"
    return hashlib.sha1(content.encode()).hexdigest()[:32]


def compute_scope_key(scope_struct: dict) -> str:
    """
    Compute canonical scope key from scope structure.

    Args:
        scope_struct: Scope key-value dict

    Returns:
        Canonical hash for grouping
    """
    if not scope_struct:
        return ""
    # Sort keys for deterministic hashing
    sorted_items = sorted(scope_struct.items())
    content = "|".join(f"{k}={v}" for k, v in sorted_items)
    return hashlib.sha1(content.encode()).hexdigest()[:16]


def parse_numeric_value(value_raw: str, value_type: ClaimValueType) -> Optional[float]:
    """
    Extract numeric value from raw value string.

    Args:
        value_raw: Raw value string (e.g., "99.7%", "64 Go", "$1000")
        value_type: Type of value

    Returns:
        Numeric value if parseable, None otherwise
    """
    if value_type == ClaimValueType.BOOLEAN:
        lower = value_raw.lower().strip()
        if lower in ("true", "yes", "enabled", "oui", "activé"):
            return 1.0
        if lower in ("false", "no", "disabled", "non", "désactivé"):
            return 0.0
        return None

    # Try to extract number from string
    import re
    numbers = re.findall(r"[-+]?\d*\.?\d+", value_raw)
    if numbers:
        try:
            return float(numbers[0])
        except ValueError:
            return None
    return None


def extract_unit(value_raw: str, value_type: ClaimValueType) -> Optional[str]:
    """
    Extract unit from raw value string.

    Args:
        value_raw: Raw value string
        value_type: Type of value

    Returns:
        Unit string if found
    """
    if value_type == ClaimValueType.PERCENTAGE:
        return "%"
    if value_type == ClaimValueType.CURRENCY:
        # Detect currency symbol
        for symbol in ["€", "$", "£", "¥", "CHF"]:
            if symbol in value_raw:
                return symbol
        return None

    # Common units
    import re
    unit_patterns = [
        r"(Go|GB|Mo|MB|Ko|KB|To|TB)",  # Storage
        r"(ms|s|min|h|j|d)",  # Time
        r"(users?|utilisateurs?)",  # Count
    ]
    for pattern in unit_patterns:
        match = re.search(pattern, value_raw, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


class RawClaimWriter:
    """
    Writes RawClaim nodes to Neo4j.

    Implements:
    - Append-only writes (never updates existing claims)
    - Idempotent via fingerprint check
    - Edges to CanonicalConcept via HAS_SUBJECT
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default",
        extractor_version: str = "v1.0.0",
        model_used: Optional[str] = None
    ):
        """
        Initialize writer.

        Args:
            neo4j_client: Neo4j client instance (creates one if not provided)
            tenant_id: Tenant ID for multi-tenancy
            extractor_version: Version of the extractor
            model_used: LLM model used
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
        self.extractor_version = extractor_version
        self.model_used = model_used

        self._stats = {
            "written": 0,
            "skipped_duplicate": 0,
            "skipped_no_concept": 0,
            "errors": 0
        }

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query using the Neo4j driver session.

        Args:
            query: Cypher query string
            params: Query parameters

        Returns:
            List of record dicts
        """
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def write_claim(
        self,
        subject_concept_id: str,
        claim_type: str,
        value_raw: str,
        value_type: ClaimValueType,
        evidence_text: str,
        source_doc_id: str,
        source_chunk_id: str,
        confidence: float,
        scope_struct: Optional[dict] = None,
        scope_raw: str = "",
        valid_time_hint: Optional[str] = None,
        source_segment_id: Optional[str] = None,
        page_number: Optional[int] = None,
        subject_surface_form: Optional[str] = None,
        flags: Optional[RawClaimFlags] = None,
    ) -> Optional[str]:
        """
        Write a single RawClaim to Neo4j.

        Args:
            subject_concept_id: ID of subject concept
            claim_type: Type of claim (SLA_AVAILABILITY, PRICING, etc.)
            value_raw: Raw value string (e.g., "99.7%")
            value_type: Type of value (PERCENTAGE, NUMBER, etc.)
            evidence_text: Evidence supporting the claim
            source_doc_id: Source document ID
            source_chunk_id: Source chunk ID
            confidence: Extractor confidence [0-1]
            scope_struct: Scope key-value dict (optional)
            scope_raw: Raw scope text (optional)
            valid_time_hint: Temporal indication (optional)
            source_segment_id: Optional segment ID
            page_number: Optional page number
            subject_surface_form: How subject appears in text
            flags: Semantic flags

        Returns:
            raw_claim_id if written, None if skipped
        """
        flags = flags or RawClaimFlags()
        scope_struct = scope_struct or {}
        scope_key = compute_scope_key(scope_struct)

        # Compute fingerprint for dedup
        fingerprint = compute_claim_fingerprint(
            self.tenant_id,
            source_doc_id,
            subject_concept_id,
            claim_type,
            scope_key,
            value_raw
        )

        # Check if already exists (idempotent)
        if self._claim_exists(fingerprint):
            self._stats["skipped_duplicate"] += 1
            logger.debug(f"[RawClaimWriter] Skipped duplicate: {fingerprint[:16]}")
            return None

        # Verify concept exists
        if not self._concept_exists(subject_concept_id):
            self._stats["skipped_no_concept"] += 1
            logger.warning(
                f"[RawClaimWriter] Concept not found: {subject_concept_id}"
            )
            return None

        # Parse numeric value and unit
        value_numeric = parse_numeric_value(value_raw, value_type)
        unit = extract_unit(value_raw, value_type)

        # Generate ULID
        raw_claim_id = f"rc_{ULID()}"

        # Build claim
        claim = RawClaim(
            raw_claim_id=raw_claim_id,
            tenant_id=self.tenant_id,
            raw_fingerprint=fingerprint,
            subject_concept_id=subject_concept_id,
            subject_surface_form=subject_surface_form,
            claim_type=claim_type,
            value_raw=value_raw,
            value_type=value_type,
            value_numeric=value_numeric,
            unit=unit,
            scope_raw=scope_raw,
            scope_struct=scope_struct,
            scope_key=scope_key,
            valid_time_hint=valid_time_hint,
            source_doc_id=source_doc_id,
            source_chunk_id=source_chunk_id,
            source_segment_id=source_segment_id,
            evidence_text=evidence_text,
            page_number=page_number,
            confidence=confidence,
            flags=flags,
            extractor_name="llm_claim_extractor",
            extractor_version=self.extractor_version,
            model_used=self.model_used,
            schema_version="2.11.0",
            created_at=datetime.utcnow()
        )

        # Write to Neo4j
        try:
            self._write_to_neo4j(claim)
            self._stats["written"] += 1
            logger.debug(f"[RawClaimWriter] Written: {raw_claim_id}")
            return raw_claim_id
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"[RawClaimWriter] Error writing claim: {e}")
            return None

    def write_batch(self, claims: List[Dict[str, Any]]) -> List[str]:
        """
        Write multiple claims.

        Args:
            claims: List of claim dicts (same args as write_claim)

        Returns:
            List of written raw_claim_ids
        """
        written_ids = []
        for claim in claims:
            result = self.write_claim(**claim)
            if result:
                written_ids.append(result)
        return written_ids

    def get_stats(self) -> Dict[str, int]:
        """Get write statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "written": 0,
            "skipped_duplicate": 0,
            "skipped_no_concept": 0,
            "errors": 0
        }

    def _claim_exists(self, fingerprint: str) -> bool:
        """Check if claim with fingerprint exists."""
        query = """
        MATCH (rc:RawClaim {tenant_id: $tenant_id, raw_fingerprint: $fingerprint})
        RETURN count(rc) > 0 AS exists
        """
        result = self._execute_query(
            query,
            {"tenant_id": self.tenant_id, "fingerprint": fingerprint}
        )
        return result[0]["exists"] if result else False

    def _concept_exists(self, concept_id: str) -> bool:
        """Check if concept exists."""
        query = """
        MATCH (c:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
        RETURN count(c) > 0 AS exists
        """
        result = self._execute_query(
            query,
            {"concept_id": concept_id, "tenant_id": self.tenant_id}
        )
        return result[0]["exists"] if result else False

    def _write_to_neo4j(self, claim: RawClaim) -> None:
        """
        Write claim node and edges to Neo4j.

        Creates:
        - RawClaim node
        - HAS_SUBJECT edge to subject CanonicalConcept
        """
        query = """
        // Create RawClaim node
        CREATE (rc:RawClaim {
            raw_claim_id: $raw_claim_id,
            tenant_id: $tenant_id,
            raw_fingerprint: $raw_fingerprint,
            subject_concept_id: $subject_concept_id,
            subject_surface_form: $subject_surface_form,
            claim_type: $claim_type,
            value_raw: $value_raw,
            value_type: $value_type,
            value_numeric: $value_numeric,
            unit: $unit,
            scope_raw: $scope_raw,
            scope_struct: $scope_struct_json,
            scope_key: $scope_key,
            valid_time_hint: $valid_time_hint,
            source_doc_id: $source_doc_id,
            source_chunk_id: $source_chunk_id,
            source_segment_id: $source_segment_id,
            evidence_text: $evidence_text,
            page_number: $page_number,
            confidence: $confidence,
            negated: $negated,
            hedged: $hedged,
            conditional: $conditional,
            ambiguous_scope: $ambiguous_scope,
            extractor_name: $extractor_name,
            extractor_version: $extractor_version,
            model_used: $model_used,
            schema_version: $schema_version,
            created_at: datetime($created_at)
        })

        // Link to subject concept
        WITH rc
        MATCH (s:CanonicalConcept {canonical_id: $subject_concept_id, tenant_id: $tenant_id})
        CREATE (rc)-[:HAS_SUBJECT]->(s)

        RETURN rc.raw_claim_id AS id
        """

        import json
        params = {
            "raw_claim_id": claim.raw_claim_id,
            "tenant_id": claim.tenant_id,
            "raw_fingerprint": claim.raw_fingerprint,
            "subject_concept_id": claim.subject_concept_id,
            "subject_surface_form": claim.subject_surface_form,
            "claim_type": claim.claim_type,
            "value_raw": claim.value_raw,
            "value_type": claim.value_type.value if isinstance(claim.value_type, ClaimValueType) else claim.value_type,
            "value_numeric": claim.value_numeric,
            "unit": claim.unit,
            "scope_raw": claim.scope_raw,
            "scope_struct_json": json.dumps(claim.scope_struct),
            "scope_key": claim.scope_key,
            "valid_time_hint": claim.valid_time_hint,
            "source_doc_id": claim.source_doc_id,
            "source_chunk_id": claim.source_chunk_id,
            "source_segment_id": claim.source_segment_id,
            "evidence_text": claim.evidence_text,
            "page_number": claim.page_number,
            "confidence": claim.confidence,
            "negated": claim.flags.negated,
            "hedged": claim.flags.hedged,
            "conditional": claim.flags.conditional,
            "ambiguous_scope": claim.flags.ambiguous_scope,
            "extractor_name": claim.extractor_name,
            "extractor_version": claim.extractor_version,
            "model_used": claim.model_used,
            "schema_version": claim.schema_version,
            "created_at": claim.created_at.isoformat()
        }

        self._execute_query(query, params)


# Singleton-like access
_writer_instance: Optional[RawClaimWriter] = None


def get_raw_claim_writer(
    tenant_id: str = "default",
    **kwargs
) -> RawClaimWriter:
    """Get or create RawClaimWriter instance."""
    global _writer_instance
    if _writer_instance is None or _writer_instance.tenant_id != tenant_id:
        _writer_instance = RawClaimWriter(tenant_id=tenant_id, **kwargs)
    return _writer_instance
