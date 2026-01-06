"""
OSMOSE Persistence - Neo4j Persistence and Relations Methods.

Module extrait de osmose_agentique.py pour améliorer la modularité.
Contient les méthodes de persistance Neo4j et d'extraction de relations.

Author: OSMOSE Refactoring
Date: 2025-01-05
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional, TYPE_CHECKING
import logging

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

    Args:
        proto_concepts: Liste des ProtoConcepts (promus uniquement)
        canonical_concepts: Liste des CanonicalConcepts
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
                proto_to_canonical[proto_id] = cc.id

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
    MERGE (d:Document {id: $doc_id, tenant_id: $tenant_id})
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
        detected_variant = doc_context_frame.get_dominant_marker()
        variant_confidence = doc_context_frame.scope_confidence
        doc_scope = doc_context_frame.doc_scope.value if hasattr(doc_context_frame.doc_scope, 'value') else str(doc_context_frame.doc_scope)
        edition = detected_variant if doc_context_frame.doc_scope.value == "VARIANT_SPECIFIC" else None
        global_markers = list(doc_context_frame.strong_markers) + list(doc_context_frame.weak_markers)

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
    """Crée les ProtoConcept nodes."""
    proto_query = """
    UNWIND $protos AS proto
    MERGE (p:ProtoConcept {concept_id: proto.id, tenant_id: $tenant_id})
    ON CREATE SET
        p.concept_name = proto.label,
        p.definition = proto.definition,
        p.type_heuristic = proto.type_heuristic,
        p.document_id = proto.document_id,
        p.section_id = proto.section_id,
        p.created_at = datetime(),
        p.extraction_method = 'hybrid_anchor',
        p.extract_confidence = proto.extract_confidence
    ON MATCH SET
        p.definition = COALESCE(proto.definition, p.definition),
        p.extract_confidence = COALESCE(proto.extract_confidence, p.extract_confidence),
        p.updated_at = datetime()
    RETURN count(p) AS created
    """

    proto_data = [
        {
            "id": pc.id,
            "label": pc.label,
            "definition": pc.definition,
            "type_heuristic": pc.type_heuristic,
            "document_id": pc.document_id,
            "section_id": getattr(pc, 'section_id', None),
            # QW-2: Confidence score from LLM
            "extract_confidence": getattr(pc, 'extract_confidence', 0.5)
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
    MERGE (c:CanonicalConcept {canonical_id: cc.id, tenant_id: $tenant_id})
    ON CREATE SET
        c.canonical_name = cc.label,
        c.canonical_key = toLower(replace(cc.label, ' ', '_')),
        c.unified_definition = cc.definition_consolidated,
        c.type_fine = cc.type_fine,
        c.stability = cc.stability,
        c.needs_confirmation = cc.needs_confirmation,
        c.status = 'HYBRID_ANCHOR',
        c.created_at = datetime()
    ON MATCH SET
        c.unified_definition = COALESCE(cc.definition_consolidated, c.unified_definition),
        c.type_fine = COALESCE(cc.type_fine, c.type_fine),
        c.stability = cc.stability,
        c.needs_confirmation = cc.needs_confirmation,
        c.updated_at = datetime()
    RETURN count(c) AS created
    """

    canonical_data = [
        {
            "id": cc.id,
            "label": cc.label,
            "definition_consolidated": cc.definition_consolidated,
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
    MATCH (d:Document {id: $doc_id, tenant_id: $tenant_id})
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
            "proto_id": pc.id,
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
        dc.document_id = chunk.document_id,
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
            "id": c.get("id"),
            "document_id": c.get("document_id"),
            "document_name": c.get("document_name"),
            "chunk_index": c.get("chunk_index", 0),
            "chunk_type": c.get("chunk_type", "document_centric"),
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
            "canonical_id": cc.id,
            "canonical_name": cc.label,
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


__all__ = [
    "persist_hybrid_anchor_to_neo4j",
    "extract_intra_document_relations",
    "trigger_entity_resolution_reevaluation",
]
