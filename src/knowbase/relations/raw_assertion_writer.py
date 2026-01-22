"""
Phase 2.8 / 2.10 - RawAssertion Writer for Neo4j

Writes RawAssertion nodes to Neo4j with edges to CanonicalConcept nodes.
Implements append-only, idempotent writes using raw_fingerprint for dedup.

Phase 2.10 additions:
- relation_type: Type forcé parmi les 12 Core types
- type_confidence: Confiance LLM sur le type
- alt_type: Type alternatif si ambiguïté
- alt_type_confidence: Confiance sur l'alternatif
- relation_subtype_raw: Nuance sémantique fine (audit only)
- context_hint: Scope/contexte local

Author: Claude Code + ChatGPT collaboration
Date: 2025-12-21 (updated 2025-12-22)
"""

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ulid import ULID

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.relations.types import (
    RawAssertion,
    RawAssertionFlags,
    RelationType,
    ExtractionMethod,
    # ADR Relations Discursivement Déterminées
    AssertionKind,
    DiscursiveBasis,
    DiscursiveAbstainReason,
)
from knowbase.relations.assertion_validation import (
    validate_before_write,
    ValidationResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ADR Predicate Validation (Safety Net)
# =============================================================================
# 12 prédicats fermés (ADR Hybrid Anchor Model)
# Ref: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md
ADR_VALID_PREDICATES = {
    "defines", "requires", "enables", "prevents", "causes", "applies_to",
    "part_of", "depends_on", "mitigates", "conflicts_with", "example_of", "governed_by"
}


def normalize_predicate(raw: str) -> str:
    """
    Normalize predicate for grouping (R3 from spec).

    Args:
        raw: Raw predicate string

    Returns:
        Normalized predicate (lower/trim/hyphen collapsed)
    """
    norm = raw.strip().lower().replace("-", " ").replace("_", " ")
    return " ".join(norm.split())  # Collapse multiple spaces


def compute_fingerprint(
    tenant_id: str,
    doc_id: str,
    chunk_id: str,
    subject_id: str,
    object_id: str,
    predicate_raw: str,
    evidence_text: str
) -> str:
    """
    Compute fingerprint hash for dedup/idempotence.

    Args:
        All components of the assertion

    Returns:
        SHA1 hash prefix (first 32 chars)
    """
    content = f"{tenant_id}|{doc_id}|{chunk_id}|{subject_id}|{object_id}|{predicate_raw}|{evidence_text}"
    return hashlib.sha1(content.encode()).hexdigest()[:32]


def compute_quality_penalty(
    evidence_text: str,
    predicate_raw: str,
    flags: RawAssertionFlags,
    subject_name: Optional[str] = None,
    object_name: Optional[str] = None
) -> float:
    """
    Compute quality penalty based on R5 rules.

    Args:
        evidence_text: Evidence supporting the assertion
        predicate_raw: Raw predicate
        flags: Semantic flags
        subject_name: Subject concept name (optional)
        object_name: Object concept name (optional)

    Returns:
        Negative penalty value (0.0 = no penalty)
    """
    penalty = 0.0

    # Evidence too short
    if len(evidence_text) < 20:
        penalty -= 0.20

    # Pronoun heavy (simple heuristic)
    pronouns = ["it", "this", "they", "he", "she", "we", "ce", "cela", "ils", "elles"]
    pronoun_count = sum(1 for word in evidence_text.lower().split() if word in pronouns)
    if pronoun_count > 3:
        penalty -= 0.15

    # Predicate too generic
    generic_predicates = ["is", "has", "are", "have", "related", "associated", "est", "a"]
    if predicate_raw.lower() in generic_predicates:
        penalty -= 0.15

    # Cross-sentence
    if flags.cross_sentence:
        penalty -= 0.10

    # Negated
    if flags.is_negated:
        penalty -= 0.10

    # Generic concepts
    generic_concepts = {
        "system", "process", "management", "solution", "platform", "service",
        "système", "processus", "gestion", "solution", "plateforme", "service"
    }
    if subject_name and subject_name.lower() in generic_concepts:
        penalty -= 0.10
    if object_name and object_name.lower() in generic_concepts:
        penalty -= 0.10

    return penalty


class RawAssertionWriter:
    """
    Writes RawAssertion nodes to Neo4j.

    Implements:
    - Append-only writes (never updates existing assertions)
    - Idempotent via fingerprint check
    - Edges to CanonicalConcept via HAS_SUBJECT/HAS_OBJECT
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default",
        extractor_version: str = "v1.0.0",
        prompt_hash: Optional[str] = None,
        model_used: Optional[str] = None
    ):
        """
        Initialize writer.

        Args:
            neo4j_client: Neo4j client instance (creates one if not provided)
            tenant_id: Tenant ID for multi-tenancy
            extractor_version: Version of the extractor
            prompt_hash: Hash of the prompt used
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
        self.prompt_hash = prompt_hash
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

    def write_assertion(
        self,
        subject_concept_id: str,
        object_concept_id: str,
        predicate_raw: str,
        evidence_text: str,
        source_doc_id: str,
        source_chunk_id: str,
        confidence: float,
        source_segment_id: Optional[str] = None,
        source_language: str = "en",
        subject_surface_form: Optional[str] = None,
        object_surface_form: Optional[str] = None,
        flags: Optional[RawAssertionFlags] = None,
        evidence_span_start: Optional[int] = None,
        evidence_span_end: Optional[int] = None,
        # Phase 2.10 - Type-First fields
        relation_type: Optional[RelationType] = None,
        type_confidence: Optional[float] = None,
        alt_type: Optional[RelationType] = None,
        alt_type_confidence: Optional[float] = None,
        relation_subtype_raw: Optional[str] = None,
        context_hint: Optional[str] = None,
        # ADR_GRAPH_FIRST_ARCHITECTURE Phase B: Lien vers Navigation Layer
        evidence_context_ids: Optional[List[str]] = None,
        # ADR Relations Discursivement Déterminées
        assertion_kind: AssertionKind = AssertionKind.EXPLICIT,
        discursive_basis: Optional[List[DiscursiveBasis]] = None,
        abstain_reason: Optional[DiscursiveAbstainReason] = None,
    ) -> Optional[str]:
        """
        Write a single RawAssertion to Neo4j.

        Args:
            subject_concept_id: ID of source concept
            object_concept_id: ID of target concept
            predicate_raw: Raw predicate string
            evidence_text: Evidence supporting the assertion
            source_doc_id: Source document ID
            source_chunk_id: Source chunk ID
            confidence: Extractor confidence [0-1]
            source_segment_id: Optional segment ID (e.g., slide_7)
            source_language: Language code
            subject_surface_form: How subject appears in text
            object_surface_form: How object appears in text
            flags: Semantic flags
            evidence_span_start: Start position in chunk
            evidence_span_end: End position in chunk
            # Phase 2.10 additions:
            relation_type: Type from closed set (12 Core types)
            type_confidence: LLM confidence on the type [0-1]
            alt_type: Alternative type if ambiguous
            alt_type_confidence: Confidence on alternative type
            relation_subtype_raw: Semantic nuance (audit only)
            context_hint: Local scope/context
            # ADR Relations Discursivement Déterminées:
            assertion_kind: EXPLICIT or DISCURSIVE
            discursive_basis: List of DiscursiveBasis for DISCURSIVE assertions
            abstain_reason: Reason for abstention if assertion is rejected

        Returns:
            raw_assertion_id if written, None if skipped
        """
        flags = flags or RawAssertionFlags()

        # Compute fingerprint for dedup
        fingerprint = compute_fingerprint(
            self.tenant_id,
            source_doc_id,
            source_chunk_id,
            subject_concept_id,
            object_concept_id,
            predicate_raw,
            evidence_text
        )

        # Check if already exists (idempotent)
        if self._assertion_exists(fingerprint):
            self._stats["skipped_duplicate"] += 1
            logger.debug(f"[RawAssertionWriter] Skipped duplicate: {fingerprint[:16]}")
            return None

        # Safety net: Validate predicate is in ADR closed set
        # Ref: ADR Hybrid Anchor Model - 12 predicates only
        predicate_norm_check = normalize_predicate(predicate_raw)
        if not predicate_raw or predicate_norm_check not in ADR_VALID_PREDICATES:
            self._stats["skipped_invalid_predicate"] = self._stats.get("skipped_invalid_predicate", 0) + 1
            logger.warning(
                f"[RawAssertionWriter] Invalid predicate '{predicate_raw}' (norm: '{predicate_norm_check}'). "
                f"Must be one of: {ADR_VALID_PREDICATES}"
            )
            return None

        # Verify concepts exist
        if not self._concept_exists(subject_concept_id) or not self._concept_exists(object_concept_id):
            self._stats["skipped_no_concept"] += 1
            logger.warning(
                f"[RawAssertionWriter] Concept not found: {subject_concept_id} or {object_concept_id}"
            )
            return None

        # ADR validation: C3bis, C4, INV-SEP-01, INV-SEP-02
        # Determine extraction method from model_used or default
        extraction_method = ExtractionMethod.HYBRID
        if self.model_used and "pattern" in self.model_used.lower():
            extraction_method = ExtractionMethod.PATTERN
        elif self.model_used and self.model_used.startswith("gpt"):
            extraction_method = ExtractionMethod.LLM

        validation_result = validate_before_write(
            assertion_kind=assertion_kind,
            relation_type=relation_type,
            extraction_method=extraction_method,
            evidence_text=evidence_text,
            discursive_basis=discursive_basis,
        )

        if not validation_result.is_valid:
            self._stats["skipped_validation"] = self._stats.get("skipped_validation", 0) + 1
            logger.warning(
                f"[RawAssertionWriter] Validation failed: {validation_result.error_code} - "
                f"{validation_result.error_message}"
            )
            # Si on avait déjà un abstain_reason du caller, on le garde
            # Sinon on utilise celui de la validation
            if abstain_reason is None:
                abstain_reason = validation_result.abstain_reason
            return None

        # Log warnings from validation
        for warning in validation_result.warnings:
            logger.debug(f"[RawAssertionWriter] Validation warning: {warning}")

        # Normalize predicate
        predicate_norm = normalize_predicate(predicate_raw)

        # Compute quality penalty
        quality_penalty = compute_quality_penalty(
            evidence_text,
            predicate_raw,
            flags,
            subject_surface_form,
            object_surface_form
        )

        # Compute final confidence (clipped)
        confidence_final = max(0.0, min(1.0, confidence + quality_penalty))

        # Generate ULID
        raw_assertion_id = f"ra_{ULID()}"

        # Build assertion
        assertion = RawAssertion(
            raw_assertion_id=raw_assertion_id,
            tenant_id=self.tenant_id,
            raw_fingerprint=fingerprint,
            predicate_raw=predicate_raw,
            predicate_norm=predicate_norm,
            # Phase 2.10 - Type-First fields
            relation_type=relation_type,
            type_confidence=type_confidence,
            alt_type=alt_type,
            alt_type_confidence=alt_type_confidence,
            relation_subtype_raw=relation_subtype_raw,
            context_hint=context_hint,
            # Concepts
            subject_concept_id=subject_concept_id,
            object_concept_id=object_concept_id,
            subject_surface_form=subject_surface_form,
            object_surface_form=object_surface_form,
            # Evidence
            evidence_text=evidence_text,
            evidence_span_start=evidence_span_start,
            evidence_span_end=evidence_span_end,
            # Scores
            confidence_extractor=confidence,
            quality_penalty=quality_penalty,
            confidence_final=confidence_final,
            # Flags
            flags=flags,
            # Source
            source_doc_id=source_doc_id,
            source_chunk_id=source_chunk_id,
            source_segment_id=source_segment_id,
            source_language=source_language,
            # ADR_GRAPH_FIRST_ARCHITECTURE Phase B: Lien vers Navigation Layer
            evidence_context_ids=evidence_context_ids or [],
            # ADR Relations Discursivement Déterminées
            assertion_kind=assertion_kind,
            discursive_basis=discursive_basis or [],
            abstain_reason=abstain_reason,
            # Traçabilité
            extractor_name="llm_relation_extractor",
            extractor_version=self.extractor_version,
            prompt_hash=self.prompt_hash,
            model_used=self.model_used,
            schema_version="2.10.0",
            created_at=datetime.utcnow()
        )

        # Write to Neo4j
        try:
            self._write_to_neo4j(assertion)
            self._stats["written"] += 1
            logger.debug(f"[RawAssertionWriter] Written: {raw_assertion_id}")
            return raw_assertion_id
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"[RawAssertionWriter] Error writing assertion: {e}")
            return None

    def write_batch(self, assertions: List[Dict[str, Any]]) -> List[str]:
        """
        Write multiple assertions.

        Args:
            assertions: List of assertion dicts (same args as write_assertion)

        Returns:
            List of written raw_assertion_ids
        """
        written_ids = []
        for assertion in assertions:
            result = self.write_assertion(**assertion)
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
            "skipped_invalid_predicate": 0,
            "errors": 0
        }

    def _assertion_exists(self, fingerprint: str) -> bool:
        """Check if assertion with fingerprint exists."""
        query = """
        MATCH (ra:RawAssertion {tenant_id: $tenant_id, raw_fingerprint: $fingerprint})
        RETURN count(ra) > 0 AS exists
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

    def _write_to_neo4j(self, assertion: RawAssertion) -> None:
        """
        Write assertion node and edges to Neo4j.

        Creates:
        - RawAssertion node
        - HAS_SUBJECT edge to subject CanonicalConcept
        - HAS_OBJECT edge to object CanonicalConcept
        """
        query = """
        // Create RawAssertion node
        CREATE (ra:RawAssertion {
            raw_assertion_id: $raw_assertion_id,
            tenant_id: $tenant_id,
            raw_fingerprint: $raw_fingerprint,
            predicate_raw: $predicate_raw,
            predicate_norm: $predicate_norm,
            // Phase 2.10 - Type-First fields
            relation_type: $relation_type,
            type_confidence: $type_confidence,
            alt_type: $alt_type,
            alt_type_confidence: $alt_type_confidence,
            relation_subtype_raw: $relation_subtype_raw,
            context_hint: $context_hint,
            // Concepts
            subject_concept_id: $subject_concept_id,
            object_concept_id: $object_concept_id,
            subject_surface_form: $subject_surface_form,
            object_surface_form: $object_surface_form,
            // Evidence
            evidence_text: $evidence_text,
            evidence_span_start: $evidence_span_start,
            evidence_span_end: $evidence_span_end,
            // Scores
            confidence_extractor: $confidence_extractor,
            quality_penalty: $quality_penalty,
            confidence_final: $confidence_final,
            // Flags
            is_negated: $is_negated,
            is_hedged: $is_hedged,
            is_conditional: $is_conditional,
            cross_sentence: $cross_sentence,
            // Source
            source_doc_id: $source_doc_id,
            source_chunk_id: $source_chunk_id,
            source_segment_id: $source_segment_id,
            source_language: $source_language,
            // ADR_GRAPH_FIRST_ARCHITECTURE Phase B: Lien vers Navigation Layer
            evidence_context_ids: $evidence_context_ids,
            // ADR Relations Discursivement Déterminées
            assertion_kind: $assertion_kind,
            discursive_basis: $discursive_basis,
            abstain_reason: $abstain_reason,
            // Traçabilité
            extractor_name: $extractor_name,
            extractor_version: $extractor_version,
            prompt_hash: $prompt_hash,
            model_used: $model_used,
            schema_version: $schema_version,
            created_at: datetime($created_at)
        })

        // Link to subject concept
        WITH ra
        MATCH (s:CanonicalConcept {canonical_id: $subject_concept_id, tenant_id: $tenant_id})
        CREATE (ra)-[:HAS_SUBJECT]->(s)

        // Link to object concept
        WITH ra
        MATCH (o:CanonicalConcept {canonical_id: $object_concept_id, tenant_id: $tenant_id})
        CREATE (ra)-[:HAS_OBJECT]->(o)

        RETURN ra.raw_assertion_id AS id
        """

        # Extract relation_type values (enum to string, handle both Enum and string)
        if assertion.relation_type:
            relation_type_str = assertion.relation_type.value if hasattr(assertion.relation_type, 'value') else str(assertion.relation_type)
        else:
            relation_type_str = None
        if assertion.alt_type:
            alt_type_str = assertion.alt_type.value if hasattr(assertion.alt_type, 'value') else str(assertion.alt_type)
        else:
            alt_type_str = None

        params = {
            "raw_assertion_id": assertion.raw_assertion_id,
            "tenant_id": assertion.tenant_id,
            "raw_fingerprint": assertion.raw_fingerprint,
            "predicate_raw": assertion.predicate_raw,
            "predicate_norm": assertion.predicate_norm,
            # Phase 2.10 - Type-First fields
            "relation_type": relation_type_str,
            "type_confidence": assertion.type_confidence,
            "alt_type": alt_type_str,
            "alt_type_confidence": assertion.alt_type_confidence,
            "relation_subtype_raw": assertion.relation_subtype_raw,
            "context_hint": assertion.context_hint,
            # Concepts
            "subject_concept_id": assertion.subject_concept_id,
            "object_concept_id": assertion.object_concept_id,
            "subject_surface_form": assertion.subject_surface_form,
            "object_surface_form": assertion.object_surface_form,
            # Evidence
            "evidence_text": assertion.evidence_text,
            "evidence_span_start": assertion.evidence_span_start,
            "evidence_span_end": assertion.evidence_span_end,
            # Scores
            "confidence_extractor": assertion.confidence_extractor,
            "quality_penalty": assertion.quality_penalty,
            "confidence_final": assertion.confidence_final,
            # Flags
            "is_negated": assertion.flags.is_negated,
            "is_hedged": assertion.flags.is_hedged,
            "is_conditional": assertion.flags.is_conditional,
            "cross_sentence": assertion.flags.cross_sentence,
            # Source
            "source_doc_id": assertion.source_doc_id,
            "source_chunk_id": assertion.source_chunk_id,
            "source_segment_id": assertion.source_segment_id,
            "source_language": assertion.source_language,
            # ADR_GRAPH_FIRST_ARCHITECTURE Phase B: Lien vers Navigation Layer
            "evidence_context_ids": assertion.evidence_context_ids,
            # ADR Relations Discursivement Déterminées
            "assertion_kind": assertion.assertion_kind.value if hasattr(assertion.assertion_kind, 'value') else str(assertion.assertion_kind),
            "discursive_basis": [b.value if hasattr(b, 'value') else str(b) for b in assertion.discursive_basis],
            "abstain_reason": assertion.abstain_reason.value if assertion.abstain_reason and hasattr(assertion.abstain_reason, 'value') else (str(assertion.abstain_reason) if assertion.abstain_reason else None),
            # Traçabilité
            "extractor_name": assertion.extractor_name,
            "extractor_version": assertion.extractor_version,
            "prompt_hash": assertion.prompt_hash,
            "model_used": assertion.model_used,
            "schema_version": assertion.schema_version,
            "created_at": assertion.created_at.isoformat()
        }

        self._execute_query(query, params)


# Singleton-like access
_writer_instance: Optional[RawAssertionWriter] = None


def get_raw_assertion_writer(
    tenant_id: str = "default",
    **kwargs
) -> RawAssertionWriter:
    """Get or create RawAssertionWriter instance."""
    global _writer_instance
    if _writer_instance is None or _writer_instance.tenant_id != tenant_id:
        _writer_instance = RawAssertionWriter(tenant_id=tenant_id, **kwargs)
    return _writer_instance
