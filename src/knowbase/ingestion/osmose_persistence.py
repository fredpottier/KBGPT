"""
OSMOSE Persistence - Neo4j Persistence and Relations Methods.

Module extrait de osmose_agentique.py pour améliorer la modularité.
Contient les méthodes de persistance Neo4j et d'extraction de relations.

Author: OSMOSE Refactoring
Date: 2025-01-05
Updated: 2026-01-11 (ADR lex_key normalization)
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional, TYPE_CHECKING
import logging

from knowbase.consolidation.lex_utils import compute_lex_key

if TYPE_CHECKING:
    from knowbase.extraction_v2.context.doc_context_frame import DocContextFrame

logger = logging.getLogger(__name__)


async def persist_hybrid_anchor_to_neo4j(
    proto_concepts: List[Any],
    canonical_concepts: List[Any],
    document_id: str,
    tenant_id: str,
    chunks: Optional[List[Dict[str, Any]]] = None,
    document_name: Optional[str] = None,
    doc_context_frame: Optional["DocContextFrame"] = None,
) -> Dict[str, int]:
    """
    Persiste les concepts Hybrid Anchor dans Neo4j.

    Crée selon l'ADR:
    - Document node avec DocContextFrame (PR4)
    - ProtoConcept nodes avec leurs attributs
    - CanonicalConcept nodes avec stability et needs_confirmation
    - Relations INSTANCE_OF entre Proto et Canonical
    - Relations EXTRACTED_FROM avec propriétés assertion (PR4)
    - DocumentChunk nodes (si chunks fournis)
    - Relations ANCHORED_IN entre concepts et chunks

    ADR_UNIFIED_CORPUS_PROMOTION (2026-01):
    En Pass 1, canonical_concepts est VIDE (liste vide). Les CanonicalConcepts
    sont créés en Pass 2.0 par la phase CORPUS_PROMOTION. Cette fonction
    gère correctement ce cas en créant 0 CanonicalConcepts et 0 relations
    INSTANCE_OF quand la liste est vide.

    Args:
        proto_concepts: Liste des ProtoConcepts extraits
        canonical_concepts: Liste des CanonicalConcepts (vide en Pass 1, ADR_UNIFIED_CORPUS_PROMOTION)
        document_id: ID du document
        tenant_id: ID tenant
        chunks: Liste des chunks avec anchored_concepts (optionnel)
        document_name: Nom du document (PR4)
        doc_context_frame: DocContextFrame pour propriétés Document (PR4)

    Returns:
        Dict avec compteurs créés
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.config.settings import get_settings

    settings = get_settings()
    stats = {
        "document_created": 0,
        "proto_created": 0,
        "canonical_created": 0,
        "relations_created": 0,
        "extracted_from_created": 0,
        "chunks_created": 0,
        "anchored_in_created": 0
    }

    try:
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            logger.warning("[OSMOSE:Persistence:Neo4j] Not connected, skipping persistence")
            return stats

        # ================================================================
        # Étape 0: Créer/mettre à jour le nœud Document (PR4)
        # ================================================================
        stats["document_created"] = _create_document_node(
            neo4j_client, document_id, tenant_id, document_name, doc_context_frame
        )

        # ================================================================
        # Étape 1: Créer les ProtoConcepts
        # ================================================================
        # Build mapping proto_id -> canonical_id pour les relations
        proto_to_canonical: Dict[str, str] = {}
        for cc in canonical_concepts:
            for proto_id in cc.proto_concept_ids:
                proto_to_canonical[proto_id] = cc.canonical_id

        stats["proto_created"] = _create_proto_concepts(
            neo4j_client, proto_concepts, tenant_id
        )

        # ================================================================
        # Étape 2: Créer les CanonicalConcepts avec stability
        # ================================================================
        stats["canonical_created"] = _create_canonical_concepts(
            neo4j_client, canonical_concepts, tenant_id
        )

        # ================================================================
        # Étape 3: Créer les relations INSTANCE_OF (Proto → Canonical)
        # ================================================================
        stats["relations_created"] = _create_instance_of_relations(
            neo4j_client, proto_to_canonical, tenant_id
        )

        # ================================================================
        # Étape 3.5: Créer les relations EXTRACTED_FROM avec assertions (PR4)
        # ================================================================
        stats["extracted_from_created"] = _create_extracted_from_relations(
            neo4j_client, proto_concepts, document_id, tenant_id, doc_context_frame
        )

        # ================================================================
        # Étapes 4 & 5: Créer les DocumentChunks et relations ANCHORED_IN
        # ================================================================
        if chunks:
            stats["chunks_created"] = _create_document_chunks(
                neo4j_client, chunks, tenant_id
            )
            stats["anchored_in_created"] = _create_anchored_in_relations(
                neo4j_client, chunks, tenant_id
            )

        logger.info(
            f"[OSMOSE:Persistence:Neo4j] ✅ Persisted: "
            f"{stats['document_created']} Document, "
            f"{stats['proto_created']} ProtoConcepts, "
            f"{stats['canonical_created']} CanonicalConcepts, "
            f"{stats['relations_created']} INSTANCE_OF, "
            f"{stats['extracted_from_created']} EXTRACTED_FROM, "
            f"{stats['chunks_created']} DocumentChunks, "
            f"{stats['anchored_in_created']} ANCHORED_IN"
        )

        return stats

    except Exception as e:
        logger.error(
            f"[OSMOSE:Persistence:Neo4j] ❌ Persistence error: {e}",
            exc_info=True
        )
        return stats


def _create_document_node(
    neo4j_client,
    document_id: str,
    tenant_id: str,
    document_name: Optional[str],
    doc_context_frame: Optional["DocContextFrame"]
) -> int:
    """Crée ou met à jour le nœud Document."""
    doc_query = """
    MERGE (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
    ON CREATE SET
        d.name = $doc_name,
        d.detected_variant = $detected_variant,
        d.variant_confidence = $variant_confidence,
        d.doc_scope = $doc_scope,
        d.edition = $edition,
        d.global_markers = $global_markers,
        d.created_at = datetime()
    ON MATCH SET
        d.name = COALESCE($doc_name, d.name),
        d.detected_variant = COALESCE($detected_variant, d.detected_variant),
        d.variant_confidence = $variant_confidence,
        d.doc_scope = $doc_scope,
        d.edition = COALESCE($edition, d.edition),
        d.global_markers = $global_markers,
        d.updated_at = datetime()
    RETURN count(d) AS created
    """

    # Extraire les données du DocContextFrame
    detected_variant = None
    variant_confidence = 0.0
    doc_scope = "unknown"
    edition = None
    global_markers: List[str] = []

    if doc_context_frame:
        doc_scope_value = doc_context_frame.doc_scope.value if hasattr(doc_context_frame.doc_scope, 'value') else str(doc_context_frame.doc_scope)
        doc_scope = doc_scope_value
        variant_confidence = doc_context_frame.scope_confidence

        # ADR: Si doc_scope == GENERAL, pas de markers (no inherited markers)
        # Les markers ne sont pertinents que pour VARIANT_SPECIFIC ou MIXED
        if doc_scope_value != "GENERAL":
            detected_variant = doc_context_frame.get_dominant_marker()
            edition = detected_variant if doc_scope_value == "VARIANT_SPECIFIC" else None
            global_markers = list(doc_context_frame.strong_markers) + list(doc_context_frame.weak_markers)
        else:
            detected_variant = None
            edition = None
            global_markers = []  # Pas de markers pour GENERAL

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(
            doc_query,
            doc_id=document_id,
            tenant_id=tenant_id,
            doc_name=document_name,
            detected_variant=detected_variant,
            variant_confidence=variant_confidence,
            doc_scope=doc_scope,
            edition=edition,
            global_markers=global_markers,
        )
        record = result.single()
        return record["created"] if record else 0


def _create_proto_concepts(
    neo4j_client,
    proto_concepts: List[Any],
    tenant_id: str
) -> int:
    """
    Crée les ProtoConcept nodes.

    ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md
    Ajoute lex_key calculé via compute_lex_key() pour matching cross-doc.
    """
    proto_query = """
    UNWIND $protos AS proto
    MERGE (p:ProtoConcept {concept_id: proto.id, tenant_id: $tenant_id})
    ON CREATE SET
        p.concept_name = proto.label,
        p.lex_key = proto.lex_key,
        p.definition = proto.definition,
        p.type_heuristic = proto.type_heuristic,
        p.doc_id = proto.doc_id,
        p.section_id = proto.section_id,
        p.created_at = datetime(),
        p.extraction_method = 'hybrid_anchor',
        p.extract_confidence = proto.extract_confidence,
        p.anchor_status = proto.anchor_status,
        p.fuzzy_best_score = proto.fuzzy_best_score,
        p.anchor_failure_reason = proto.anchor_failure_reason
    ON MATCH SET
        p.definition = COALESCE(proto.definition, p.definition),
        p.lex_key = COALESCE(proto.lex_key, p.lex_key),
        p.extract_confidence = COALESCE(proto.extract_confidence, p.extract_confidence),
        p.anchor_status = proto.anchor_status,
        p.fuzzy_best_score = proto.fuzzy_best_score,
        p.anchor_failure_reason = proto.anchor_failure_reason,
        p.updated_at = datetime()
    RETURN count(p) AS created
    """

    proto_data = [
        {
            "id": pc.concept_id,
            "label": pc.concept_name,
            "lex_key": compute_lex_key(pc.concept_name) if pc.concept_name else "",  # ADR lex_key
            "definition": pc.definition,
            "type_heuristic": pc.type_heuristic,
            "doc_id": pc.doc_id,
            "section_id": getattr(pc, 'section_id', None),
            # QW-2: Confidence score from LLM
            "extract_confidence": getattr(pc, 'extract_confidence', 0.5),
            # 2026-01: Anchor diagnostics
            "anchor_status": getattr(pc, 'anchor_status', 'SPAN'),
            "fuzzy_best_score": getattr(pc, 'fuzzy_best_score', 0.0),
            "anchor_failure_reason": getattr(pc, 'anchor_failure_reason', None)
        }
        for pc in proto_concepts
    ]

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(proto_query, protos=proto_data, tenant_id=tenant_id)
        record = result.single()
        return record["created"] if record else 0


def _create_canonical_concepts(
    neo4j_client,
    canonical_concepts: List[Any],
    tenant_id: str
) -> int:
    """Crée les CanonicalConcept nodes avec stability."""
    canonical_query = """
    UNWIND $canonicals AS cc
    MERGE (c:CanonicalConcept {canonical_id: cc.canonical_id, tenant_id: $tenant_id})
    ON CREATE SET
        c.canonical_name = cc.canonical_name,
        c.canonical_key = toLower(replace(cc.canonical_name, ' ', '_')),
        c.unified_definition = cc.unified_definition,
        c.type_fine = cc.type_fine,
        c.stability = cc.stability,
        c.needs_confirmation = cc.needs_confirmation,
        c.status = 'HYBRID_ANCHOR',
        c.created_at = datetime()
    ON MATCH SET
        c.unified_definition = COALESCE(cc.unified_definition, c.unified_definition),
        c.type_fine = COALESCE(cc.type_fine, c.type_fine),
        c.stability = cc.stability,
        c.needs_confirmation = cc.needs_confirmation,
        c.updated_at = datetime()
    RETURN count(c) AS created
    """

    canonical_data = [
        {
            "canonical_id": cc.canonical_id,
            "canonical_name": cc.canonical_name,
            "unified_definition": cc.unified_definition,
            "type_fine": cc.type_fine,
            "stability": cc.stability.value if hasattr(cc.stability, 'value') else str(cc.stability),
            "needs_confirmation": cc.needs_confirmation
        }
        for cc in canonical_concepts
    ]

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(canonical_query, canonicals=canonical_data, tenant_id=tenant_id)
        record = result.single()
        return record["created"] if record else 0


def _create_instance_of_relations(
    neo4j_client,
    proto_to_canonical: Dict[str, str],
    tenant_id: str
) -> int:
    """Crée les relations INSTANCE_OF (Proto → Canonical)."""
    relation_query = """
    UNWIND $relations AS rel
    MATCH (p:ProtoConcept {concept_id: rel.proto_id, tenant_id: $tenant_id})
    MATCH (c:CanonicalConcept {canonical_id: rel.canonical_id, tenant_id: $tenant_id})
    MERGE (p)-[r:INSTANCE_OF]->(c)
    ON CREATE SET r.created_at = datetime()
    RETURN count(r) AS created
    """

    relation_data = [
        {"proto_id": proto_id, "canonical_id": canonical_id}
        for proto_id, canonical_id in proto_to_canonical.items()
    ]

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(relation_query, relations=relation_data, tenant_id=tenant_id)
        record = result.single()
        return record["created"] if record else 0


def _create_extracted_from_relations(
    neo4j_client,
    proto_concepts: List[Any],
    document_id: str,
    tenant_id: str,
    doc_context_frame: Optional["DocContextFrame"]
) -> int:
    """Crée les relations EXTRACTED_FROM avec propriétés assertion (PR4)."""
    extracted_from_query = """
    UNWIND $assertions AS a
    MATCH (pc:ProtoConcept {concept_id: a.proto_id, tenant_id: $tenant_id})
    MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
    MERGE (pc)-[r:EXTRACTED_FROM]->(d)
    ON CREATE SET
        r.polarity = a.polarity,
        r.scope = a.scope,
        r.markers = a.markers,
        r.confidence = a.confidence,
        r.qualifier_source = a.qualifier_source,
        r.is_override = a.is_override,
        r.created_at = datetime()
    ON MATCH SET
        r.polarity = CASE WHEN a.confidence > COALESCE(r.confidence, 0) THEN a.polarity ELSE r.polarity END,
        r.scope = CASE WHEN a.confidence > COALESCE(r.confidence, 0) THEN a.scope ELSE r.scope END,
        r.confidence = CASE WHEN a.confidence > COALESCE(r.confidence, 0) THEN a.confidence ELSE r.confidence END,
        r.markers = CASE WHEN size(a.markers) > size(COALESCE(r.markers, [])) THEN a.markers ELSE COALESCE(r.markers, []) END,
        r.updated_at = datetime()
    RETURN count(r) AS created
    """

    # Collecter les données d'assertion depuis les ProtoConcepts enrichis
    assertion_data = []
    for pc in proto_concepts:
        polarity = "unknown"
        scope = "unknown"
        markers: List[str] = []
        confidence = 0.5
        qualifier_source = "unknown"
        is_override = False

        # Priorité 1: Contexte agrégé (computed_context ou context)
        if hasattr(pc, 'computed_context') and pc.computed_context:
            ctx = pc.computed_context
            polarity = ctx.aggregated_polarity.value if hasattr(ctx.aggregated_polarity, 'value') else str(ctx.aggregated_polarity)
            scope = ctx.aggregated_scope.value if hasattr(ctx.aggregated_scope, 'value') else str(ctx.aggregated_scope)
            markers = list(ctx.all_markers) if hasattr(ctx, 'all_markers') else []
            confidence = ctx.confidence if hasattr(ctx, 'confidence') else 0.5

        # Priorité 2: Premier anchor avec contexte
        elif hasattr(pc, 'anchors') and pc.anchors:
            for anchor in pc.anchors:
                if hasattr(anchor, 'context') and anchor.context:
                    actx = anchor.context
                    polarity = actx.polarity.value if hasattr(actx.polarity, 'value') else str(actx.polarity) if actx.polarity else "unknown"
                    scope = actx.scope.value if hasattr(actx.scope, 'value') else str(actx.scope) if actx.scope else "unknown"
                    markers = [m.value for m in actx.local_markers] if hasattr(actx, 'local_markers') and actx.local_markers else []
                    confidence = actx.confidence if hasattr(actx, 'confidence') else 0.5
                    qualifier_source = actx.qualifier_source.value if hasattr(actx.qualifier_source, 'value') else str(actx.qualifier_source) if actx.qualifier_source else "unknown"
                    is_override = actx.is_override if hasattr(actx, 'is_override') else False
                    break

        # Fallback: Utiliser les markers du DocContextFrame
        if not markers and doc_context_frame and doc_context_frame.has_markers():
            markers = list(doc_context_frame.strong_markers) + list(doc_context_frame.weak_markers)
            qualifier_source = "inherited"

        assertion_data.append({
            "proto_id": pc.concept_id,
            "polarity": polarity,
            "scope": scope,
            "markers": markers,
            "confidence": confidence,
            "qualifier_source": qualifier_source,
            "is_override": is_override,
        })

    if not assertion_data:
        return 0

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(
            extracted_from_query,
            assertions=assertion_data,
            doc_id=document_id,
            tenant_id=tenant_id,
        )
        record = result.single()
        return record["created"] if record else 0


def _create_document_chunks(
    neo4j_client,
    chunks: List[Dict[str, Any]],
    tenant_id: str
) -> int:
    """Crée les DocumentChunk nodes."""
    chunk_query = """
    UNWIND $chunks AS chunk
    MERGE (dc:DocumentChunk {chunk_id: chunk.id, tenant_id: $tenant_id})
    ON CREATE SET
        dc.doc_id = chunk.document_id,
        dc.document_name = chunk.document_name,
        dc.chunk_index = chunk.chunk_index,
        dc.chunk_type = chunk.chunk_type,
        dc.char_start = chunk.char_start,
        dc.char_end = chunk.char_end,
        dc.token_count = chunk.token_count,
        dc.text_preview = left(chunk.text, 200),
        dc.created_at = datetime()
    ON MATCH SET
        dc.updated_at = datetime()
    RETURN count(dc) AS created
    """

    chunk_data = [
        {
            # ADR Dual Chunking: Préférer chunk_id structuré si disponible, sinon fallback sur id (UUID)
            "id": c.get("chunk_id") or c.get("id"),
            "document_id": c.get("document_id"),
            "document_name": c.get("document_name"),
            "chunk_index": c.get("chunk_index", 0),
            "chunk_type": c.get("chunk_type", "retrieval"),  # Default to retrieval for new chunks
            "char_start": c.get("char_start", 0),
            "char_end": c.get("char_end", 0),
            "token_count": c.get("token_count", 0),
            "text": c.get("text", "")[:200]
        }
        for c in chunks
    ]

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(chunk_query, chunks=chunk_data, tenant_id=tenant_id)
        record = result.single()
        return record["created"] if record else 0


def _create_anchored_in_relations(
    neo4j_client,
    chunks: List[Dict[str, Any]],
    tenant_id: str
) -> int:
    """Crée les relations ANCHORED_IN (Concept → Chunk)."""
    anchored_relations = []
    for chunk in chunks:
        chunk_id = chunk.get("id")
        for ac in chunk.get("anchored_concepts", []):
            concept_id = ac.get("concept_id")
            if concept_id and chunk_id:
                anchored_relations.append({
                    "concept_id": concept_id,
                    "chunk_id": chunk_id,
                    "role": ac.get("role", "mention"),
                    "span_start": ac.get("span", [0, 0])[0] if ac.get("span") else 0,
                    "span_end": ac.get("span", [0, 0])[1] if ac.get("span") else 0
                })

    if not anchored_relations:
        return 0

    anchored_query = """
    UNWIND $relations AS rel
    MATCH (p:ProtoConcept {concept_id: rel.concept_id, tenant_id: $tenant_id})
    MATCH (dc:DocumentChunk {chunk_id: rel.chunk_id, tenant_id: $tenant_id})
    MERGE (p)-[r:ANCHORED_IN]->(dc)
    ON CREATE SET
        r.role = rel.role,
        r.span_start = rel.span_start,
        r.span_end = rel.span_end,
        r.created_at = datetime()
    RETURN count(r) AS created
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(anchored_query, relations=anchored_relations, tenant_id=tenant_id)
        record = result.single()
        return record["created"] if record else 0


# ============================================================================
# DUAL CHUNKING - ADR_DUAL_CHUNKING_ARCHITECTURE.md (2026-01)
# ============================================================================


def _create_coverage_chunks(
    neo4j_client,
    coverage_chunks: List[Dict[str, Any]],
    tenant_id: str
) -> int:
    """
    DEPRECATED: Utilisez anchor_proto_concepts_to_docitems() à la place.

    Crée les CoverageChunk nodes dans Neo4j.

    ADR_COVERAGE_PROPERTY_NOT_NODE: Cette fonction est dépréciée.
    Le système Option C utilise DocItem comme cible de ANCHORED_IN.
    """
    import warnings
    warnings.warn(
        "_create_coverage_chunks is deprecated. Use anchor_proto_concepts_to_docitems() "
        "with DocItem instead (ADR_COVERAGE_PROPERTY_NOT_NODE).",
        DeprecationWarning,
        stacklevel=2
    )
    if not coverage_chunks:
        return 0

    chunk_query = """
    UNWIND $chunks AS chunk
    MERGE (dc:DocumentChunk {chunk_id: chunk.chunk_id, tenant_id: $tenant_id})
    ON CREATE SET
        dc.doc_id = chunk.document_id,
        dc.chunk_type = 'coverage',
        dc.char_start = chunk.char_start,
        dc.char_end = chunk.char_end,
        dc.coverage_seq = chunk.coverage_seq,
        dc.token_count = chunk.token_count,
        dc.context_id = chunk.context_id,
        dc.section_path = chunk.section_path,
        dc.created_at = datetime()
    ON MATCH SET
        dc.updated_at = datetime()
    RETURN count(dc) AS created
    """

    chunk_data = [
        {
            "chunk_id": c.get("chunk_id"),
            "document_id": c.get("document_id"),
            "char_start": c.get("char_start", 0),
            "char_end": c.get("char_end", 0),
            "coverage_seq": c.get("coverage_seq", 0),
            "token_count": c.get("token_count", 0),
            "context_id": c.get("context_id"),
            "section_path": c.get("section_path"),
        }
        for c in coverage_chunks
    ]

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(chunk_query, chunks=chunk_data, tenant_id=tenant_id)
        record = result.single()
        created = record["created"] if record else 0
        logger.info(f"[OSMOSE:DualChunk] Created {created} CoverageChunks")
        return created


def _create_aligns_with_relations(
    neo4j_client,
    alignments: List[Dict[str, Any]],
    tenant_id: str
) -> int:
    """
    DEPRECATED: Les relations ALIGNS_WITH ne sont plus utilisées avec Option C.

    ADR_COVERAGE_PROPERTY_NOT_NODE: Cette fonction est dépréciée.
    Le système Option C n'utilise plus de CoverageChunks ni d'alignements.
    """
    import warnings
    warnings.warn(
        "_create_aligns_with_relations is deprecated. ALIGNS_WITH relations "
        "are no longer used with Option C (ADR_COVERAGE_PROPERTY_NOT_NODE).",
        DeprecationWarning,
        stacklevel=2
    )
    if not alignments:
        return 0

    align_query = """
    UNWIND $alignments AS align
    MATCH (cc:DocumentChunk {chunk_id: align.coverage_chunk_id, tenant_id: $tenant_id})
    MATCH (rc:DocumentChunk {chunk_id: align.retrieval_chunk_id, tenant_id: $tenant_id})
    MERGE (cc)-[r:ALIGNS_WITH]->(rc)
    ON CREATE SET
        r.overlap_chars = align.overlap_chars,
        r.overlap_ratio = align.overlap_ratio,
        r.created_at = datetime()
    RETURN count(r) AS created
    """

    align_data = [
        {
            "coverage_chunk_id": a.get("coverage_chunk_id"),
            "retrieval_chunk_id": a.get("retrieval_chunk_id"),
            "overlap_chars": a.get("overlap_chars", 0),
            "overlap_ratio": a.get("overlap_ratio", 0.0),
        }
        for a in alignments
    ]

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(align_query, alignments=align_data, tenant_id=tenant_id)
        record = result.single()
        created = record["created"] if record else 0
        logger.info(f"[OSMOSE:DualChunk] Created {created} ALIGNS_WITH relations")
        return created


def _create_anchored_in_to_coverage(
    neo4j_client,
    proto_concepts: List[Any],
    coverage_chunks: List[Dict[str, Any]],
    tenant_id: str
) -> int:
    """
    DEPRECATED: Utilisez anchor_proto_concepts_to_docitems() à la place.

    ADR_COVERAGE_PROPERTY_NOT_NODE: Cette fonction est dépréciée.
    Le système Option C utilise DocItem comme cible de ANCHORED_IN
    au lieu de CoverageChunks.
    """
    import warnings
    warnings.warn(
        "_create_anchored_in_to_coverage is deprecated. Use anchor_proto_concepts_to_docitems() "
        "with DocItem instead (ADR_COVERAGE_PROPERTY_NOT_NODE).",
        DeprecationWarning,
        stacklevel=2
    )
    if not proto_concepts or not coverage_chunks:
        return 0

    # Construire l'index des coverage chunks par position
    # Trié par char_start pour recherche efficace
    sorted_coverage = sorted(coverage_chunks, key=lambda c: c.get("char_start", 0))

    anchored_relations = []
    # ADR_STRUCTURAL_CONTEXT_ALIGNMENT: Collecter les context_id pour mise à jour des protos
    proto_context_mappings = []

    for proto in proto_concepts:
        # Vérifier anchor_status
        anchor_status = getattr(proto, 'anchor_status', None)
        if anchor_status != "SPAN":
            continue

        # Récupérer les anchors
        anchors = getattr(proto, 'anchors', []) or []
        concept_id = getattr(proto, 'concept_id', None)

        if not concept_id:
            continue

        for anchor in anchors:
            anchor_start = getattr(anchor, 'span_start', None)
            anchor_end = getattr(anchor, 'span_end', None)
            anchor_role = getattr(anchor, 'role', 'mention')

            if anchor_start is None or anchor_end is None:
                continue

            # Trouver le CoverageChunk contenant cette position
            matching_chunk = None
            for chunk in sorted_coverage:
                chunk_start = chunk.get("char_start", 0)
                chunk_end = chunk.get("char_end", 0)

                # Le chunk contient l'anchor si anchor_start est dans [chunk_start, chunk_end)
                if chunk_start <= anchor_start < chunk_end:
                    matching_chunk = chunk
                    break

            if matching_chunk:
                chunk_id = matching_chunk.get("chunk_id")
                chunk_start = matching_chunk.get("char_start", 0)
                # ADR_STRUCTURAL_CONTEXT_ALIGNMENT: Récupérer context_id du chunk
                context_id = matching_chunk.get("context_id")

                # Calculer span relatif au chunk
                span_start = anchor_start - chunk_start
                span_end = anchor_end - chunk_start

                anchored_relations.append({
                    "concept_id": concept_id,
                    "chunk_id": chunk_id,
                    "role": anchor_role.value if hasattr(anchor_role, 'value') else str(anchor_role),
                    "span_start": span_start,
                    "span_end": span_end,
                })

                # ADR_STRUCTURAL_CONTEXT_ALIGNMENT: Stocker le mapping proto → context_id
                if context_id:
                    proto_context_mappings.append({
                        "concept_id": concept_id,
                        "context_id": context_id,
                    })
            else:
                logger.warning(
                    f"[OSMOSE:DualChunk] No coverage chunk for anchor at "
                    f"position {anchor_start} (concept={concept_id})"
                )

    if not anchored_relations:
        logger.warning("[OSMOSE:DualChunk] No ANCHORED_IN relations to create")
        return 0

    anchored_query = """
    UNWIND $relations AS rel
    MATCH (p:ProtoConcept {concept_id: rel.concept_id, tenant_id: $tenant_id})
    MATCH (dc:DocumentChunk {chunk_id: rel.chunk_id, tenant_id: $tenant_id})
    MERGE (p)-[r:ANCHORED_IN]->(dc)
    ON CREATE SET
        r.role = rel.role,
        r.span_start = rel.span_start,
        r.span_end = rel.span_end,
        r.created_at = datetime()
    RETURN count(r) AS created
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(anchored_query, relations=anchored_relations, tenant_id=tenant_id)
        record = result.single()
        created = record["created"] if record else 0
        logger.info(
            f"[OSMOSE:DualChunk] Created {created} ANCHORED_IN relations "
            f"(from {len(anchored_relations)} candidates)"
        )

        # ADR_STRUCTURAL_CONTEXT_ALIGNMENT: Mettre à jour context_id sur les ProtoConcepts
        if proto_context_mappings:
            _update_proto_context_ids(neo4j_client, proto_context_mappings, tenant_id)

        return created


def _update_proto_context_ids(
    neo4j_client,
    proto_context_mappings: List[Dict[str, str]],
    tenant_id: str
) -> int:
    """
    Met à jour le context_id sur les ProtoConcepts.

    ADR: doc/ongoing/ADR_STRUCTURAL_CONTEXT_ALIGNMENT.md

    Le context_id permet de lier le ProtoConcept à sa SectionContext
    structurelle (via SectionContext.context_id), ce qui est nécessaire
    pour créer des relations MENTIONED_IN précises en Pass 2.

    Args:
        neo4j_client: Client Neo4j
        proto_context_mappings: Liste de {concept_id, context_id}
        tenant_id: ID tenant

    Returns:
        Nombre de ProtoConcepts mis à jour
    """
    if not proto_context_mappings:
        return 0

    # Dédupliquer par concept_id (garder le premier context_id trouvé)
    seen = set()
    unique_mappings = []
    for mapping in proto_context_mappings:
        cid = mapping["concept_id"]
        if cid not in seen:
            seen.add(cid)
            unique_mappings.append(mapping)

    update_query = """
    UNWIND $mappings AS m
    MATCH (p:ProtoConcept {concept_id: m.concept_id, tenant_id: $tenant_id})
    SET p.context_id = m.context_id
    RETURN count(p) AS updated
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(update_query, mappings=unique_mappings, tenant_id=tenant_id)
        record = result.single()
        updated = record["updated"] if record else 0
        logger.info(
            f"[OSMOSE:StructuralContext] Updated {updated} ProtoConcepts with context_id "
            f"(ADR_STRUCTURAL_CONTEXT_ALIGNMENT)"
        )
        return updated


async def persist_dual_chunks_to_neo4j(
    coverage_chunks: List[Dict[str, Any]],
    retrieval_chunks: List[Dict[str, Any]],
    alignments: List[Dict[str, Any]],
    proto_concepts: List[Any],
    tenant_id: str
) -> Dict[str, int]:
    """
    DEPRECATED: Le système Dual Chunking est remplacé par Option C.

    ADR_COVERAGE_PROPERTY_NOT_NODE: Cette fonction est dépréciée.
    Utilisez anchor_proto_concepts_to_docitems() pour les relations ANCHORED_IN.
    Les CoverageChunks et ALIGNS_WITH ne sont plus utilisés.

    Args:
        coverage_chunks: CoverageChunks générés (ignoré avec Option C)
        retrieval_chunks: RetrievalChunks générés (chunks existants)
        alignments: Relations d'alignement (dicts avec coverage_chunk_id, retrieval_chunk_id)
        proto_concepts: ProtoConcepts pour les relations ANCHORED_IN
        tenant_id: ID tenant

    Returns:
        Dict avec compteurs créés
    """
    import warnings
    warnings.warn(
        "persist_dual_chunks_to_neo4j is deprecated. Use anchor_proto_concepts_to_docitems() "
        "for ANCHORED_IN relations (ADR_COVERAGE_PROPERTY_NOT_NODE).",
        DeprecationWarning,
        stacklevel=2
    )
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.config.settings import get_settings

    settings = get_settings()
    stats = {
        "coverage_chunks_created": 0,
        "retrieval_chunks_created": 0,
        "aligns_with_created": 0,
        "anchored_in_created": 0,
    }

    try:
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            logger.warning("[OSMOSE:DualChunk] Neo4j not connected, skipping")
            return stats

        # 1. Créer les CoverageChunks
        stats["coverage_chunks_created"] = _create_coverage_chunks(
            neo4j_client, coverage_chunks, tenant_id
        )

        # 2. Créer les RetrievalChunks (utilise la fonction existante)
        stats["retrieval_chunks_created"] = _create_document_chunks(
            neo4j_client, retrieval_chunks, tenant_id
        )

        # 3. Créer les relations ALIGNS_WITH
        stats["aligns_with_created"] = _create_aligns_with_relations(
            neo4j_client, alignments, tenant_id
        )

        # 4. Créer les relations ANCHORED_IN vers CoverageChunks
        stats["anchored_in_created"] = _create_anchored_in_to_coverage(
            neo4j_client, proto_concepts, coverage_chunks, tenant_id
        )

        logger.info(
            f"[OSMOSE:DualChunk] ✅ Persisted Dual Chunking: "
            f"{stats['coverage_chunks_created']} CoverageChunks, "
            f"{stats['retrieval_chunks_created']} RetrievalChunks, "
            f"{stats['aligns_with_created']} ALIGNS_WITH, "
            f"{stats['anchored_in_created']} ANCHORED_IN"
        )

        return stats

    except Exception as e:
        logger.error(
            f"[OSMOSE:DualChunk] ❌ Persistence error: {e}",
            exc_info=True
        )
        return stats


async def extract_intra_document_relations(
    canonical_concepts: List[Any],
    text_content: str,
    document_id: str,
    tenant_id: str,
    document_chunks: Optional[List[Dict[str, Any]]] = None
) -> int:
    """
    Extrait et persiste les relations intra-document (Pass 1.5).

    Option A' (ADR 2024-12-30): Si document_chunks fournis, utilise
    extract_relations_chunk_aware() qui itère sur les DocumentChunks
    avec fenêtre [i-1, i, i+1] et catalogue filtré par anchored_concepts.

    Args:
        canonical_concepts: Liste des CanonicalConcepts (promus en Pass 1)
        text_content: Texte complet du document (fallback si pas de chunks)
        document_id: ID du document source
        tenant_id: ID tenant
        document_chunks: Liste des DocumentChunks avec anchored_concepts (Option A')

    Returns:
        Nombre de RawAssertions créées
    """
    from knowbase.relations.llm_relation_extractor import LLMRelationExtractor
    from knowbase.relations.raw_assertion_writer import get_raw_assertion_writer

    logger.info(
        f"[OSMOSE:Relations] Extracting intra-document relations "
        f"for {len(canonical_concepts)} concepts"
        f"{f', {len(document_chunks)} chunks (Option A)' if document_chunks else ' (legacy mode)'}"
    )

    # Convertir CanonicalConcepts en format attendu par LLMRelationExtractor
    concepts_for_extraction = []
    for cc in canonical_concepts:
        concept_dict = {
            "canonical_id": cc.canonical_id,
            "canonical_name": cc.canonical_name,
            "concept_type": cc.type_fine or "abstract",
            "surface_forms": list(cc.surface_forms) if hasattr(cc, 'surface_forms') and cc.surface_forms else [],
            "proto_concept_ids": list(cc.proto_concept_ids) if hasattr(cc, 'proto_concept_ids') and cc.proto_concept_ids else []
        }
        concepts_for_extraction.append(concept_dict)

    # Initialiser l'extracteur LLM
    extractor = LLMRelationExtractor(
        model="gpt-4o-mini",
        max_context_chars=8000,
        use_id_first=True
    )

    try:
        # Option A' : Extraction alignée sur DocumentChunks (recommandée)
        if document_chunks and len(document_chunks) > 0:
            logger.info(
                f"[OSMOSE:Relations] Using PARALLEL chunk-aware extraction "
                f"(Option A', async with max_concurrent=10)"
            )
            extraction_result = await extractor.extract_relations_chunk_aware_async(
                document_chunks=document_chunks,
                all_concepts=concepts_for_extraction,
                document_id=document_id,
                tenant_id=tenant_id,
                window_size=1,
                max_concepts=100,
                min_type_confidence=0.65,
                doc_top_k=15,
                lex_fallback_threshold=8,
                max_concurrent=10
            )
        else:
            # Fallback: Extraction legacy sur full_text (déprécié)
            logger.warning(
                f"[OSMOSE:Relations] No chunks provided, "
                f"falling back to legacy extraction (DEPRECATED)"
            )
            extraction_result = extractor.extract_relations_type_first(
                concepts=concepts_for_extraction,
                full_text=text_content,
                document_id=document_id,
                chunk_id=f"{document_id}_full",
                min_type_confidence=0.65
            )

        if not extraction_result.relations:
            logger.info(
                f"[OSMOSE:Relations] No relations extracted "
                f"({extraction_result.stats.get('relations_extracted', 0)} attempted)"
            )
            return 0

        logger.info(
            f"[OSMOSE:Relations] Extracted {len(extraction_result.relations)} relations "
            f"(valid={extraction_result.stats.get('relations_valid', 0)}, "
            f"invalid_type={extraction_result.stats.get('relations_invalid_type', 0)}, "
            f"invalid_index={extraction_result.stats.get('relations_invalid_index', 0)})"
        )

        # Initialiser le writer
        writer = get_raw_assertion_writer(
            tenant_id=tenant_id,
            extractor_version="2.10.0",
            model_used="gpt-4o-mini"
        )
        writer.reset_stats()

        # Écrire chaque relation comme RawAssertion
        for rel in extraction_result.relations:
            writer.write_assertion(
                subject_concept_id=rel.subject_concept_id,
                object_concept_id=rel.object_concept_id,
                predicate_raw=rel.predicate_raw,
                evidence_text=rel.evidence,
                source_doc_id=document_id,
                source_chunk_id=f"{document_id}_full",
                confidence=rel.confidence,
                source_language="MULTI",
                subject_surface_form=rel.subject_surface_form,
                object_surface_form=rel.object_surface_form,
                flags=rel.flags,
                evidence_span_start=rel.evidence_start_char,
                evidence_span_end=rel.evidence_end_char,
                relation_type=rel.relation_type,
                type_confidence=rel.type_confidence,
                alt_type=rel.alt_type,
                alt_type_confidence=rel.alt_type_confidence,
                relation_subtype_raw=rel.relation_subtype_raw,
                context_hint=rel.context_hint
            )

        stats = writer.get_stats()
        logger.info(
            f"[OSMOSE:Relations] ✅ Persisted {stats['written']} RawAssertions "
            f"(skipped: {stats['skipped_duplicate']} duplicates, "
            f"{stats['skipped_no_concept']} missing concepts)"
        )

        return stats['written']

    except Exception as e:
        logger.error(
            f"[OSMOSE:Relations] ❌ Error extracting relations: {e}",
            exc_info=True
        )
        return 0


async def trigger_entity_resolution_reevaluation(
    tenant_id: Optional[str] = None
) -> None:
    """
    Trigger async entity resolution reevaluation.

    Phase 2.12: Called when document count threshold is reached.
    Non-blocking - runs in background.

    Args:
        tenant_id: Tenant ID
    """
    try:
        from knowbase.entity_resolution.deferred_reevaluator import run_reevaluation_job
        result = await run_reevaluation_job(
            tenant_id=tenant_id or "default",
            dry_run=False
        )
        logger.info(
            f"[OSMOSE:EntityResolution] Reevaluation complete: "
            f"{result.promoted_to_auto} promoted to AUTO, "
            f"{result.still_deferred} still deferred"
        )
    except Exception as e:
        logger.warning(f"[OSMOSE:EntityResolution] Reevaluation failed: {e}")


# ============================================================================
# ADR_COVERAGE_PROPERTY_NOT_NODE - Phase 1 & 2 (2026-01)
# Migration CoverageChunk → DocItem pour ANCHORED_IN
# ============================================================================


def lookup_section_id_by_position(
    doc_id: str,
    char_position: int,
    tenant_id: str = "default",
) -> Optional[str]:
    """
    Trouve le section_id UUID correspondant à une position char dans le document.

    Utilise les DocItems avec charspan pour trouver la section contenant
    la position spécifiée.

    ADR: ADR_COVERAGE_PROPERTY_NOT_NODE - Phase 1

    Args:
        doc_id: ID du document
        char_position: Position caractère à localiser
        tenant_id: Tenant ID

    Returns:
        section_id UUID ou None si non trouvé
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.config.settings import get_settings

    settings = get_settings()

    try:
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            return None

        # Query pour trouver le DocItem contenant la position
        query = """
        MATCH (d:DocItem {doc_id: $doc_id, tenant_id: $tenant_id})
        WHERE d.charspan_start IS NOT NULL
          AND d.charspan_end IS NOT NULL
          AND d.charspan_start <= $char_position
          AND d.charspan_end >= $char_position
        RETURN d.section_id AS section_id
        LIMIT 1
        """

        with neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(
                query,
                doc_id=doc_id,
                char_position=char_position,
                tenant_id=tenant_id
            )
            record = result.single()
            if record and record["section_id"]:
                return record["section_id"]

        return None

    except Exception as e:
        logger.warning(f"[OSMOSE:Persistence] lookup_section_id failed: {e}")
        return None


def resolve_section_ids_for_proto_concepts(
    proto_concepts: List[Any],
    doc_id: str,
    tenant_id: str = "default",
) -> int:
    """
    Résout les section_id des ProtoConcepts vers les UUID des SectionContext.

    Utilise la RECHERCHE TEXTUELLE (concept_name) pour trouver le DocItem
    correspondant et obtenir son section_id.

    ADR: ADR_COVERAGE_PROPERTY_NOT_NODE - Fix 2026-01-16
    Le matching par position échoue car les coordonnées ne sont pas alignées.

    Args:
        proto_concepts: Liste des ProtoConcepts à mettre à jour (in-place)
        doc_id: ID du document
        tenant_id: Tenant ID

    Returns:
        Nombre de section_id résolus
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.config.settings import get_settings

    settings = get_settings()
    resolved_count = 0

    # Collecter les concept_names à résoudre
    protos_to_resolve = []
    for proto in proto_concepts:
        concept_name = getattr(proto, 'concept_name', None)
        proto_id = getattr(proto, 'concept_id', None)
        if concept_name and proto_id and len(concept_name) > 2:
            protos_to_resolve.append({
                "proto_id": proto_id,
                "concept_name": concept_name,
                "proto_obj": proto
            })

    if not protos_to_resolve:
        return 0

    try:
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            return 0

        # Query textuelle pour trouver les section_id
        query = """
        UNWIND $proto_data AS pd
        MATCH (d:DocItem {doc_id: $doc_id, tenant_id: $tenant_id})
        WHERE d.text IS NOT NULL
          AND d.section_id IS NOT NULL
          AND d.section_id STARTS WITH 'sec_'
          AND toLower(d.text) CONTAINS toLower(pd.concept_name)
        WITH pd.proto_id AS proto_id, d.section_id AS section_id,
             coalesce(d.reading_order_index, 0) AS roi
        ORDER BY roi
        WITH proto_id, collect(section_id)[0] AS best_section
        WHERE best_section IS NOT NULL
        RETURN proto_id, best_section
        """

        proto_data = [{"proto_id": p["proto_id"], "concept_name": p["concept_name"]}
                      for p in protos_to_resolve]

        # Créer un index pour retrouver les objets proto
        proto_index = {p["proto_id"]: p["proto_obj"] for p in protos_to_resolve}

        with neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(
                query,
                proto_data=proto_data,
                doc_id=doc_id,
                tenant_id=tenant_id
            )

            for record in result:
                proto_id = record["proto_id"]
                section_id = record["best_section"]
                if proto_id in proto_index:
                    proto_index[proto_id].section_id = section_id
                    resolved_count += 1

    except Exception as e:
        logger.error(f"[OSMOSE:Persistence] resolve_section_ids_for_proto_concepts failed: {e}")

    logger.info(
        f"[OSMOSE:Persistence] Resolved {resolved_count}/{len(proto_concepts)} "
        f"section_ids via textual matching for doc={doc_id}"
    )

    return resolved_count


def anchor_proto_concepts_to_docitems(
    proto_concepts: List[Any],
    doc_id: str,
    tenant_id: str = "default",
) -> int:
    """
    Crée les relations ANCHORED_IN entre ProtoConcepts et DocItems.

    Pour chaque ProtoConcept avec anchor SPAN, trouve le DocItem correspondant
    via la position char et crée la relation ANCHORED_IN.

    ADR: ADR_COVERAGE_PROPERTY_NOT_NODE - Phase 2
    Remplace l'ancien système ANCHORED_IN → DocumentChunk

    Args:
        proto_concepts: Liste des ProtoConcepts
        doc_id: ID du document
        tenant_id: Tenant ID

    Returns:
        Nombre de relations ANCHORED_IN créées
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.config.settings import get_settings

    settings = get_settings()

    try:
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        if not neo4j_client.is_connected():
            logger.warning("[OSMOSE:Persistence] Neo4j not connected, skipping ANCHORED_IN creation")
            return 0

        # Collecter les anchors à créer
        anchor_data = []
        for proto in proto_concepts:
            proto_id = getattr(proto, 'concept_id', None)
            if not proto_id:
                continue

            anchors = getattr(proto, 'anchors', [])
            anchor_status = getattr(proto, 'anchor_status', 'NONE')

            # Uniquement les anchors SPAN (position valide)
            if anchor_status != 'SPAN' or not anchors:
                continue

            for anchor in anchors:
                span_start = getattr(anchor, 'span_start', None)
                span_end = getattr(anchor, 'span_end', None)
                role = getattr(anchor, 'role', 'mention')

                if span_start is not None and span_end is not None:
                    anchor_data.append({
                        "proto_id": proto_id,
                        "char_start": span_start,
                        "char_end": span_end,
                        "role": role,
                    })

        if not anchor_data:
            logger.debug(f"[OSMOSE:Persistence] No SPAN anchors to create for doc={doc_id}")
            return 0

        # Phase 1: Créer ANCHORED_IN par recherche TEXTUELLE (plus fiable)
        # Le matching par position échoue souvent car les coordonnées des anchors
        # ne sont pas alignées avec charspan_docwide des DocItems
        # ADR_COVERAGE_PROPERTY_NOT_NODE - Fix 2026-01-16

        # Collecter les concept_names pour recherche textuelle
        # ADR_PROPERTY_NAMING_NORMALIZATION: concept_name est maintenant unifié Python ↔ Neo4j
        proto_names = {}
        for proto in proto_concepts:
            proto_id = getattr(proto, 'concept_id', None)
            concept_name = getattr(proto, 'concept_name', None)
            section_id = getattr(proto, 'section_id', None)
            if proto_id and concept_name and len(concept_name) > 2:
                proto_names[proto_id] = {
                    "concept_name": concept_name,
                    "section_id": section_id
                }

        # ================================================================
        # Charspan Contract v1: Créer ANCHORED_IN avec spans relatifs
        # ADR_CHARSPAN_CONTRACT_V1.md
        # ================================================================

        # Phase 1: Essayer d'utiliser les positions NER PRIMARY (anchors du ProtoConcept)
        # Si les positions docwide sont disponibles, on peut créer des anchors PRIMARY
        primary_anchor_data = []
        fallback_proto_ids = set()

        for proto in proto_concepts:
            proto_id = getattr(proto, 'concept_id', None)
            if not proto_id:
                continue

            anchors = getattr(proto, 'anchors', [])
            anchor_status = getattr(proto, 'anchor_status', 'NONE')

            # Si SPAN et anchors avec positions, utiliser les positions NER
            if anchor_status == 'SPAN' and anchors:
                for anchor in anchors:
                    span_start_docwide = getattr(anchor, 'span_start', None)
                    span_end_docwide = getattr(anchor, 'span_end', None)
                    surface_form = getattr(anchor, 'surface_form', '')
                    role = getattr(anchor, 'role', 'mention')

                    if span_start_docwide is not None and span_end_docwide is not None:
                        primary_anchor_data.append({
                            "proto_id": proto_id,
                            "char_start_docwide": span_start_docwide,
                            "char_end_docwide": span_end_docwide,
                            "quote": surface_form,
                            "role": role.value if hasattr(role, 'value') else str(role),
                        })
                    else:
                        fallback_proto_ids.add(proto_id)
            else:
                # Pas d'anchor SPAN, fallback sur indexOf
                fallback_proto_ids.add(proto_id)

        created_primary = 0

        # Log diagnostic pour PRIMARY anchors
        logger.info(
            f"[OSMOSE:Persistence:PRIMARY] Collected {len(primary_anchor_data)} PRIMARY anchors, "
            f"{len(fallback_proto_ids)} concepts need fallback for doc={doc_id}"
        )
        if primary_anchor_data and len(primary_anchor_data) <= 3:
            # Log les premiers anchors pour debug
            for ad in primary_anchor_data[:3]:
                logger.debug(
                    f"[OSMOSE:Persistence:PRIMARY] Anchor {ad['proto_id']}: "
                    f"char_start={ad['char_start_docwide']}, char_end={ad['char_end_docwide']}"
                )

        # Query PRIMARY: Utiliser les positions docwide NER pour trouver le DocItem
        if primary_anchor_data:
            primary_query = """
            UNWIND $anchor_data AS ad
            MATCH (p:ProtoConcept {concept_id: ad.proto_id, tenant_id: $tenant_id})
            WHERE NOT EXISTS { MATCH (p)-[:ANCHORED_IN]->(:DocItem) }

            // Trouver le DocItem contenant la position docwide
            MATCH (d:DocItem {doc_id: $doc_id, tenant_id: $tenant_id})
            WHERE d.charspan_start_docwide IS NOT NULL
              AND d.charspan_end_docwide IS NOT NULL
              AND d.charspan_start_docwide <= ad.char_start_docwide
              AND d.charspan_end_docwide >= ad.char_end_docwide

            // Calculer span relatif au DocItem.text
            WITH p, d, ad,
                 ad.char_start_docwide - d.charspan_start_docwide AS span_start,
                 ad.char_end_docwide - d.charspan_start_docwide AS span_end

            // Valider que les spans sont valides
            WHERE span_start >= 0 AND span_end > span_start AND span_end <= size(d.text)

            // Extraire le texte pour vérification
            WITH p, d, ad, span_start, span_end,
                 substring(d.text, span_start, span_end - span_start) AS extracted_text

            // Générer anchor_id unique
            WITH p, d, ad, span_start, span_end, extracted_text,
                 p.concept_id + ':' + d.item_id + ':' + toString(span_start) + ':' + toString(span_end) AS anchor_id

            MERGE (p)-[r:ANCHORED_IN {anchor_id: anchor_id}]->(d)
            ON CREATE SET
                r.span_start = span_start,
                r.span_end = span_end,
                r.surface_form = extracted_text,
                r.anchor_quality = 'PRIMARY',
                r.anchor_method = 'ner_extractor',
                r.created_at = datetime()
            RETURN count(r) AS created
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    primary_query,
                    anchor_data=primary_anchor_data,
                    doc_id=doc_id,
                    tenant_id=tenant_id
                )
                record = result.single()
                created_primary = record["created"] if record else 0

            logger.info(
                f"[OSMOSE:Persistence] Created {created_primary} PRIMARY ANCHORED_IN relations "
                f"(NER positions) for doc={doc_id}"
            )

        # Phase 2: Fallback indexOf pour les protos sans positions NER valides
        # Collecter les proto_names pour fallback
        fallback_proto_data = [
            {"proto_id": pid, "concept_name": data["concept_name"], "section_id": data["section_id"]}
            for pid, data in proto_names.items()
            if pid in fallback_proto_ids or created_primary == 0
        ]

        created_approx = 0

        # Log diagnostic pour fallback
        logger.info(
            f"[OSMOSE:Persistence:APPROX] Collected {len(fallback_proto_data)} concepts for indexOf fallback, "
            f"proto_names has {len(proto_names)} entries for doc={doc_id}"
        )

        if fallback_proto_data:
            # Query APPROX: indexOf fallback pour concepts sans positions NER
            textual_query = """
            UNWIND $proto_data AS pd
            MATCH (p:ProtoConcept {concept_id: pd.proto_id, tenant_id: $tenant_id})
            WHERE NOT EXISTS { MATCH (p)-[:ANCHORED_IN]->(:DocItem) }

            // Chercher DocItems contenant le concept_name
            MATCH (d:DocItem {doc_id: $doc_id, tenant_id: $tenant_id})
            WHERE d.text IS NOT NULL
              AND d.charspan_start_docwide IS NOT NULL
              AND toLower(d.text) CONTAINS toLower(pd.concept_name)

            // Calculer span_start relatif au DocItem.text via indexOf
            WITH p, d, pd,
                 apoc.text.indexOf(toLower(d.text), toLower(pd.concept_name), 0) AS span_start,
                 CASE WHEN d.section_id = pd.section_id THEN 0 ELSE 1 END AS section_priority,
                 coalesce(d.reading_order_index, 0) AS roi
            WHERE span_start >= 0

            // Calculer span_end
            WITH p, d, pd, span_start,
                 span_start + size(pd.concept_name) AS span_end,
                 section_priority, roi
            ORDER BY section_priority, roi

            // Prendre le meilleur DocItem pour chaque ProtoConcept
            WITH p, collect({
                docitem: d,
                span_start: span_start,
                span_end: span_end,
                concept_name: pd.concept_name
            })[0] AS best
            WHERE best IS NOT NULL

            // Créer ANCHORED_IN avec propriétés Contract v1
            WITH p, best.docitem AS d, best.span_start AS span_start,
                 best.span_end AS span_end, best.concept_name AS concept_name

            // Générer anchor_id unique
            WITH p, d, span_start, span_end, concept_name,
                 p.concept_id + ':' + d.item_id + ':' + toString(span_start) + ':' + toString(span_end) AS anchor_id

            MERGE (p)-[r:ANCHORED_IN {anchor_id: anchor_id}]->(d)
            ON CREATE SET
                r.span_start = span_start,
                r.span_end = span_end,
                r.surface_form = substring(d.text, span_start, span_end - span_start),
                r.anchor_quality = 'APPROX',
                r.anchor_method = 'indexOf_fallback',
                r.created_at = datetime()
            RETURN count(r) AS created
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    textual_query,
                    proto_data=fallback_proto_data,
                    doc_id=doc_id,
                    tenant_id=tenant_id
                )
                record = result.single()
                created_approx = record["created"] if record else 0

            if created_approx > 0:
                logger.info(
                    f"[OSMOSE:Persistence] Created {created_approx} APPROX ANCHORED_IN relations "
                    f"(indexOf fallback) for doc={doc_id}"
                )

        created = created_primary + created_approx

        logger.info(
            f"[OSMOSE:Persistence] Created {created} ANCHORED_IN relations "
            f"(PRIMARY={created_primary}, APPROX={created_approx}) for doc={doc_id}"
        )

        # Phase 3: Synchroniser section_id des ProtoConcepts avec le DocItem ancré
        if created > 0:
            sync_query = """
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})-[:ANCHORED_IN]->(d:DocItem {doc_id: $doc_id})
            WHERE d.section_id IS NOT NULL
              AND d.section_id STARTS WITH 'sec_'
              AND (p.section_id IS NULL OR p.section_id <> d.section_id)
            SET p.section_id = d.section_id
            RETURN count(p) AS synced
            """
            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(sync_query, doc_id=doc_id, tenant_id=tenant_id)
                record = result.single()
                synced = record["synced"] if record else 0
                if synced > 0:
                    logger.info(
                        f"[OSMOSE:Persistence] Synced {synced} ProtoConcept section_ids "
                        f"with anchored DocItems for doc={doc_id}"
                    )

            # Phase 3b: Calculer char_start_docwide sur ProtoConcept (cache dérivé)
            # Contract v1: docwide = d.charspan_start_docwide + r.span_start
            charspan_sync_query = """
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})-[r:ANCHORED_IN]->(d:DocItem {doc_id: $doc_id})
            WHERE d.charspan_start_docwide IS NOT NULL
              AND r.span_start IS NOT NULL
              AND (p.char_start_docwide IS NULL OR p.char_end_docwide IS NULL)
            SET p.char_start_docwide = d.charspan_start_docwide + r.span_start,
                p.char_end_docwide = d.charspan_start_docwide + r.span_end
            RETURN count(p) AS synced_charspans
            """
            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(charspan_sync_query, doc_id=doc_id, tenant_id=tenant_id)
                record = result.single()
                synced_charspans = record["synced_charspans"] if record else 0
                if synced_charspans > 0:
                    logger.info(
                        f"[OSMOSE:Persistence] Synced {synced_charspans} ProtoConcept charspans "
                        f"(char_start_docwide = d.docwide + r.span_start) for doc={doc_id}"
                    )

        return created

    except Exception as e:
        logger.error(f"[OSMOSE:Persistence] anchor_proto_concepts_to_docitems failed: {e}")
        return 0


__all__ = [
    "persist_hybrid_anchor_to_neo4j",
    "extract_intra_document_relations",
    "trigger_entity_resolution_reevaluation",
    # ADR_COVERAGE_PROPERTY_NOT_NODE
    "lookup_section_id_by_position",
    "resolve_section_ids_for_proto_concepts",
    "anchor_proto_concepts_to_docitems",
]
