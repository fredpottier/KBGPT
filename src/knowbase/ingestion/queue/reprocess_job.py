"""
Job RQ pour le reprocess batch Pipeline V2.

Exécuté dans le worker dédié (knowbase-worker) au lieu du process API.
Ref: ADR Isolation Reprocess Worker (2026-02-02)

La logique est extraite de stratified/api/router.py::_run_reprocess_batch.
Le tracking de progression via Redis fonctionne cross-container (même Redis).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# REDIS STATE (réutilise les mêmes clés que le router)
# ============================================================================

REPROCESS_STATE_KEY = "osmose:v2:reprocess:state"
REPROCESS_STATE_TTL = 3600  # 1 heure


def _get_redis_client():
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        return get_redis_client()
    except Exception as e:
        logger.warning(f"[OSMOSE:V2:Worker] Redis unavailable: {e}")
        return None


def _save_reprocess_state(state: dict) -> bool:
    import json
    client = _get_redis_client()
    if not client:
        return False
    if not client.is_connected():
        return False
    try:
        client.client.setex(REPROCESS_STATE_KEY, REPROCESS_STATE_TTL, json.dumps(state))
        return True
    except Exception as e:
        logger.error(f"[OSMOSE:V2:Worker] Failed to save state: {e}")
        return False


def _load_reprocess_state() -> Optional[dict]:
    import json
    client = _get_redis_client()
    if client and client.is_connected():
        try:
            data = client.client.get(REPROCESS_STATE_KEY)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"[OSMOSE:V2:Worker] Failed to load state: {e}")
    return None


def _update_reprocess_state(**kwargs) -> bool:
    state = _load_reprocess_state()
    if state is None:
        state = {
            "status": "running",
            "total_documents": 0,
            "processed": 0,
            "failed": 0,
            "current_document": None,
            "current_phase": None,
            "progress_percent": 0.0,
            "started_at": datetime.utcnow().isoformat(),
            "errors": []
        }
    state.update(kwargs)
    return _save_reprocess_state(state)


def _is_reprocess_cancelled() -> bool:
    state = _load_reprocess_state()
    return state is not None and state.get("status") == "cancelled"


# ============================================================================
# LLM WRAPPER (identique à router.py)
# ============================================================================

class Pass1LLMWrapper:
    """Adapte LLMRouter à l'interface attendue par Pass1."""

    def __init__(self, llm_router):
        self.router = llm_router

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3
    ) -> str:
        from knowbase.common.llm_router import TaskType

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        return self.router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )


def _get_pass1_llm_client():
    try:
        from knowbase.common.llm_router import get_llm_router
        llm_router = get_llm_router()
        return Pass1LLMWrapper(llm_router)
    except Exception as e:
        logger.warning(f"[OSMOSE:V2:Worker] LLM non disponible: {e}")
        return None


def _convert_chunk_to_docitem_map(pass0_chunk_map) -> dict:
    result = {}
    for chunk_id, mapping in pass0_chunk_map.items():
        result[chunk_id] = mapping.docitem_ids
    return result


# ============================================================================
# JOB RQ PRINCIPAL
# ============================================================================

def reprocess_batch_job(
    documents: List[dict],
    run_pass1: bool = True,
    run_pass2: bool = True,
    run_pass3: bool = False,
    tenant_id: str = "default",
) -> dict:
    """
    Job RQ exécuté dans le worker dédié.

    Même logique que l'ancien _run_reprocess_batch de router.py,
    mais synchrone (pas async) car RQ SimpleWorker.

    Args:
        documents: Liste de dicts avec au minimum 'document_id' et 'cache_path'
        run_pass1: Exécuter Pass 1
        run_pass2: Exécuter Pass 2
        run_pass3: Exécuter Pass 3 (consolidation)
        tenant_id: Tenant ID

    Returns:
        Dict avec stats finales
    """
    processed = 0
    failed = 0
    errors = []

    try:
        from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache
        from knowbase.stratified.pass1.orchestrator import Pass1OrchestratorV2
        from knowbase.stratified.pass1.persister import Pass1PersisterV2, persist_vision_observations
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )

        for i, doc in enumerate(documents):
            if _is_reprocess_cancelled():
                logger.info("[OSMOSE:V2:Reprocess] Cancelled by user")
                break

            doc_id = doc["document_id"]
            cache_path = doc["cache_path"]

            _update_reprocess_state(
                current_document=doc_id,
                progress_percent=(i / len(documents)) * 100,
                processed=processed,
                failed=failed
            )

            try:
                # 1. Charger depuis le cache
                _update_reprocess_state(current_phase="LOADING_CACHE")
                cache_result = load_pass0_from_cache(
                    cache_path=cache_path,
                    tenant_id=tenant_id,
                )

                if not cache_result.success:
                    raise Exception(f"Cache load failed: {cache_result.error}")

                pass0_result = cache_result.pass0_result

                # 1b. Persister Pass 0 dans Neo4j
                _update_reprocess_state(current_phase="PERSIST_PASS0")
                from knowbase.stratified.pass0.adapter import persist_pass0_to_neo4j_sync

                pass0_stats = persist_pass0_to_neo4j_sync(
                    pass0_result=pass0_result,
                    neo4j_driver=neo4j_client.driver,
                )
                logger.info(
                    f"[OSMOSE:V2:Reprocess] Pass 0 persisted: "
                    f"{pass0_stats['document']} doc, {pass0_stats['sections']} sections, "
                    f"{pass0_stats['docitems']} docitems"
                )

                # 1c. Persister VisionObservations
                if cache_result.vision_observations:
                    vision_stats = persist_vision_observations(
                        observations=cache_result.vision_observations,
                        doc_id=doc_id,
                        neo4j_driver=neo4j_client.driver,
                        tenant_id=tenant_id
                    )
                    logger.info(
                        f"[OSMOSE:V2:Reprocess] VisionObservations persisted: "
                        f"{vision_stats.get('vision_observations', 0)} observations"
                    )

                # 1d. Layer R: Upsert sub-chunks + embeddings dans Qdrant
                re_meta = cache_result.retrieval_embeddings
                npz_path = cache_result.retrieval_embeddings_path

                if re_meta and re_meta.get("status") == "success" and npz_path:
                    _update_reprocess_state(current_phase="LAYER_R_UPSERT")
                    try:
                        from knowbase.retrieval.rechunker import SubChunk
                        from knowbase.retrieval.qdrant_layer_r import upsert_layer_r
                        import numpy as np

                        npz_data = np.load(npz_path)
                        embeddings = npz_data["embeddings"]

                        sub_chunks_data = re_meta.get("sub_chunks", [])
                        if len(sub_chunks_data) != len(embeddings):
                            raise ValueError(
                                f"Mismatch: {len(sub_chunks_data)} sub-chunks vs {len(embeddings)} embeddings"
                            )

                        pairs = []
                        for idx, sc_data in enumerate(sub_chunks_data):
                            sc = SubChunk(
                                chunk_id=sc_data["chunk_id"],
                                sub_index=sc_data["sub_index"],
                                text=sc_data["text"],
                                parent_chunk_id=sc_data["parent_chunk_id"],
                                section_id=sc_data.get("section_id"),
                                doc_id=doc_id,
                                tenant_id=tenant_id,
                                kind=sc_data["kind"],
                                page_no=sc_data["page_no"],
                                page_span_min=sc_data.get("page_span_min"),
                                page_span_max=sc_data.get("page_span_max"),
                                item_ids=sc_data.get("item_ids", []),
                                text_origin=sc_data.get("text_origin"),
                            )
                            pairs.append((sc, embeddings[idx]))

                        n = upsert_layer_r(pairs, tenant_id=tenant_id)
                        logger.info(f"[OSMOSE:V2:Reprocess] Layer R: {n} points upserted in knowbase_chunks_v2")
                    except Exception as e:
                        logger.warning(f"[OSMOSE:V2:Reprocess] Layer R upsert failed (non-blocking): {e}")
                else:
                    reason = re_meta.get("status", "missing") if re_meta else "no_meta"
                    detail = re_meta.get("reason", "") if re_meta else ""
                    logger.warning(
                        f"[OSMOSE:V2:Reprocess] Layer R cache miss for {doc_id} "
                        f"(status={reason}{', reason=' + detail if detail else ''}) "
                        f"→ recalcul à la volée"
                    )

                    _update_reprocess_state(current_phase="LAYER_R_RECOMPUTE")
                    try:
                        from knowbase.retrieval.rechunker import rechunk_for_retrieval, SubChunk
                        from knowbase.retrieval.qdrant_layer_r import upsert_layer_r
                        from knowbase.common.clients.embeddings import get_embedding_manager

                        raw_chunks = pass0_result.chunks or []
                        if not raw_chunks:
                            logger.warning(
                                f"[OSMOSE:V2:Reprocess] Layer R recompute: "
                                f"no chunks in pass0 for {doc_id}"
                            )
                        else:
                            sub_chunks = rechunk_for_retrieval(
                                chunks=raw_chunks,
                                tenant_id=tenant_id,
                                doc_id=doc_id,
                            )
                            logger.info(
                                f"[OSMOSE:V2:Reprocess] Layer R recompute: "
                                f"{len(raw_chunks)} chunks → {len(sub_chunks)} sub-chunks"
                            )

                            texts = [sc.text for sc in sub_chunks]
                            manager = get_embedding_manager()
                            embeddings = manager.encode(texts)

                            pairs = [
                                (sc, embeddings[i])
                                for i, sc in enumerate(sub_chunks)
                            ]
                            n = upsert_layer_r(pairs, tenant_id=tenant_id)
                            logger.info(
                                f"[OSMOSE:V2:Reprocess] Layer R recomputed: "
                                f"{n} points upserted in knowbase_chunks_v2"
                            )

                    except Exception as e:
                        logger.warning(
                            f"[OSMOSE:V2:Reprocess] Layer R recompute failed "
                            f"(non-blocking): {e}"
                        )

                # 2. Pass 1: Lecture Stratifiée
                if run_pass1:
                    _update_reprocess_state(current_phase="PASS_1")
                    logger.info(f"[OSMOSE:V2:Reprocess] Pass 1 on {doc_id}")

                    content = cache_result.full_text or ""

                    docitems = {}
                    for item in (pass0_result.doc_items or []):
                        docitem_id = f"{tenant_id}:{doc_id}:{item.item_id}"
                        from knowbase.stratified.models import DocItem as StratifiedDocItem, DocItemType
                        try:
                            item_type = DocItemType(item.item_type.lower() if item.item_type else "paragraph")
                        except ValueError:
                            item_type = DocItemType.PARAGRAPH
                        docitems[docitem_id] = StratifiedDocItem(
                            docitem_id=docitem_id,
                            type=item_type,
                            text=item.text,
                            page=item.page_no,
                            char_start=item.charspan_start or 0,
                            char_end=item.charspan_end or 0,
                            order=item.reading_order_index or 0,
                            section_id=item.section_id or ""
                        )

                    chunks_dict = {chunk.chunk_id: chunk.text for chunk in (pass0_result.chunks or [])}

                    chunk_to_docitem_map = _convert_chunk_to_docitem_map(
                        pass0_result.chunk_to_docitem_map
                    )

                    sections_for_pass09 = []
                    for section in (pass0_result.sections or []):
                        sections_for_pass09.append({
                            "id": section.section_id,
                            "section_id": section.section_id,
                            "title": section.title,
                            "level": section.section_level,
                            "chunk_ids": [
                                chunk.chunk_id
                                for chunk in (pass0_result.chunks or [])
                                if any(
                                    item.section_id == section.section_id
                                    for item_id in chunk.item_ids
                                    for item in (pass0_result.doc_items or [])
                                    if item.item_id == item_id
                                )
                            ]
                        })

                    logger.info(
                        f"[OSMOSE:V2:Reprocess] Prepared: {len(docitems)} DocItems from cache, "
                        f"{len(chunks_dict)} chunks, {len(chunk_to_docitem_map)} mappings, "
                        f"{len(sections_for_pass09)} sections for Pass 0.9"
                    )

                    llm_client = _get_pass1_llm_client()
                    if llm_client:
                        logger.info("[OSMOSE:V2:Reprocess] LLM client initialized for Pass 1")
                    else:
                        logger.warning("[OSMOSE:V2:Reprocess] LLM unavailable, using fallback")

                    from knowbase.config.feature_flags import get_stratified_v2_config
                    strict_promotion = get_stratified_v2_config("strict_promotion", tenant_id)
                    if strict_promotion is None:
                        strict_promotion = False

                    enable_pointer_mode = get_stratified_v2_config("enable_pointer_mode", tenant_id)
                    if enable_pointer_mode is None:
                        enable_pointer_mode = False
                    logger.info(f"[OSMOSE:V2:Reprocess] strict_promotion={strict_promotion}, enable_pointer_mode={enable_pointer_mode}")

                    # V2.2: Feature flag
                    use_v22 = get_stratified_v2_config("pass1_v22", tenant_id)
                    if use_v22 is None:
                        use_v22 = False

                    if use_v22:
                        logger.info(f"[OSMOSE:V2:Reprocess] V2.2 activé pour {doc_id}")
                        from knowbase.stratified.pass09 import GlobalViewBuilder
                        from knowbase.stratified.pass1_v22.orchestrator import (
                            Pass1OrchestratorV22,
                        )

                        gv_builder = GlobalViewBuilder(llm_client=llm_client)
                        global_view = gv_builder.build_sync(
                            doc_id=doc_id,
                            tenant_id=tenant_id,
                            sections=sections_for_pass09,
                            chunks=chunks_dict,
                            doc_title=cache_result.doc_title or doc_id,
                            full_text=content,
                        )

                        if global_view and global_view.zones:
                            logger.info(
                                f"[OSMOSE:V2:Reprocess] V2.2: GlobalView avec "
                                f"{len(global_view.zones)} zones"
                            )
                            orchestrator_v22 = Pass1OrchestratorV22(
                                llm_client=llm_client,
                                allow_fallback=(llm_client is None),
                                strict_promotion=strict_promotion,
                                tenant_id=tenant_id,
                            )
                            pass1_result = orchestrator_v22.process(
                                doc_id=doc_id,
                                doc_title=cache_result.doc_title or doc_id,
                                content=content,
                                docitems=docitems,
                                chunks=chunks_dict,
                                global_view=global_view,
                                chunk_to_docitem_map=chunk_to_docitem_map,
                                sections=sections_for_pass09,
                            )
                        else:
                            logger.warning(
                                f"[OSMOSE:V2:Reprocess] V2.2: pas de zones, "
                                "fallback V2.1"
                            )
                            use_v22 = False

                    if not use_v22:
                        orchestrator = Pass1OrchestratorV2(
                            llm_client=llm_client,
                            allow_fallback=(llm_client is None),
                            strict_promotion=strict_promotion,
                            tenant_id=tenant_id,
                            enable_pointer_mode=enable_pointer_mode,
                        )

                        pass1_result = orchestrator.process(
                            doc_id=doc_id,
                            doc_title=cache_result.doc_title or doc_id,
                            content=content,
                            docitems=docitems,
                            chunks=chunks_dict,
                            chunk_to_docitem_map=chunk_to_docitem_map,
                            sections=sections_for_pass09,
                        )

                    persister = Pass1PersisterV2(
                        neo4j_driver=neo4j_client.driver,
                        tenant_id=tenant_id
                    )
                    persist_stats = persister.persist(pass1_result)
                    logger.info(
                        f"[OSMOSE:V2:Reprocess] Pass 1 completed: "
                        f"{len(pass1_result.concepts)} concepts, "
                        f"{len(pass1_result.informations)} informations, "
                        f"persisted: {persist_stats}"
                    )

                    # 2b. Cross-reference Layer R <-> Neo4j Information
                    _update_reprocess_state(current_phase="LAYER_R_BRIDGE")
                    try:
                        from knowbase.retrieval.layer_r_bridge import cross_reference_layer_r

                        concepts_by_id = {c.concept_id: c.name for c in pass1_result.concepts}
                        bridge_stats = cross_reference_layer_r(
                            pass1_result=pass1_result,
                            concepts_by_id=concepts_by_id,
                            doc_id=doc_id,
                            tenant_id=tenant_id,
                            neo4j_driver=neo4j_client.driver,
                        )
                        logger.info(
                            f"[OSMOSE:V2:Reprocess] Layer R Bridge: "
                            f"{bridge_stats.qdrant_points_enriched} points enrichis, "
                            f"{bridge_stats.neo4j_nodes_updated} nodes Neo4j, "
                            f"{bridge_stats.orphan_informations} orphans"
                        )
                    except Exception as e:
                        logger.warning(f"[OSMOSE:V2:Reprocess] Layer R Bridge failed (non-blocking): {e}")

                # 3. Pass 2: Enrichissement
                if run_pass2:
                    _update_reprocess_state(current_phase="PASS_2")
                    logger.info(f"[OSMOSE:V2:Reprocess] Pass 2 on {doc_id}")

                    from knowbase.stratified.pass2.orchestrator import Pass2OrchestratorV2

                    if 'pass1_result' not in locals():
                        logger.info(f"[OSMOSE:V2:Reprocess] Loading Pass 1 result from Neo4j for {doc_id}")
                        from knowbase.stratified.api.router import _load_pass1_result_from_neo4j
                        pass1_result = _load_pass1_result_from_neo4j(
                            neo4j_client.driver,
                            doc_id,
                            tenant_id
                        )
                        if pass1_result is None:
                            logger.warning(f"[OSMOSE:V2:Reprocess] No Pass 1 data in Neo4j - skipping Pass 2 for {doc_id}")
                            errors.append(f"{doc_id}: Pass 1 data not found in Neo4j")
                            _update_reprocess_state(errors=errors)
                            continue

                        if 'llm_client' not in locals():
                            llm_client = _get_pass1_llm_client()

                    if pass1_result:
                        pass2_orchestrator = Pass2OrchestratorV2(
                            llm_client=llm_client,
                            neo4j_driver=neo4j_client.driver,
                            allow_fallback=(llm_client is None),
                            tenant_id=tenant_id
                        )

                        pass2_result = pass2_orchestrator.process(
                            pass1_result=pass1_result,
                            persist=True
                        )

                        logger.info(
                            f"[OSMOSE:V2:Reprocess] Pass 2 completed: "
                            f"{pass2_result.stats.relations_extracted} relations"
                        )

                processed += 1
                _update_reprocess_state(processed=processed)

            except Exception as e:
                logger.error(f"[OSMOSE:V2:Reprocess] Error on {doc_id}: {e}")
                failed += 1
                errors.append(f"{doc_id}: {str(e)}")
                _update_reprocess_state(failed=failed, errors=errors)

        # 4. Pass 3: Consolidation
        if run_pass3 and not _is_reprocess_cancelled():
            _update_reprocess_state(current_phase="PASS_3", current_document="CORPUS")
            logger.info("[OSMOSE:V2:Reprocess] Pass 3 consolidation...")

        # Finaliser
        final_status = "cancelled" if _is_reprocess_cancelled() else "completed"
        _update_reprocess_state(
            current_phase=None,
            current_document=None,
            progress_percent=100.0,
            status=final_status,
            processed=processed,
            failed=failed
        )

        logger.info(
            f"[OSMOSE:V2:Reprocess] Completed: {processed} OK, {failed} failed"
        )

        return {
            "status": final_status,
            "processed": processed,
            "failed": failed,
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"[OSMOSE:V2:Reprocess] Batch error: {e}")
        errors.append(str(e))
        _update_reprocess_state(status="failed", errors=errors)
        raise
