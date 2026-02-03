# src/knowbase/claimfirst/worker_job.py
"""
Worker Job pour le pipeline Claim-First.

Exécution dans le worker RQ (knowbase-worker), pas le container app.
Même pattern que reprocess_job.py.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

import redis

logger = logging.getLogger(__name__)

# Clé Redis pour l'état du job
CLAIMFIRST_STATE_KEY = "osmose:claimfirst:state"


def _get_redis_client() -> redis.Redis:
    """Crée un client Redis."""
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(redis_url)


def _update_state(
    redis_client: redis.Redis,
    **kwargs,
) -> None:
    """Met à jour l'état du job dans Redis."""
    current = redis_client.hgetall(CLAIMFIRST_STATE_KEY)
    state = {k.decode(): v.decode() for k, v in current.items()} if current else {}
    state.update({k: str(v) for k, v in kwargs.items()})
    state["updated_at"] = str(time.time())
    redis_client.hset(CLAIMFIRST_STATE_KEY, mapping=state)


def _get_state(redis_client: redis.Redis) -> dict:
    """Récupère l'état actuel du job."""
    current = redis_client.hgetall(CLAIMFIRST_STATE_KEY)
    return {k.decode(): v.decode() for k, v in current.items()} if current else {}


def claimfirst_process_job(
    doc_ids: List[str],
    tenant_id: str = "default",
    cache_dir: str = "/data/extraction_cache",
) -> dict:
    """
    RQ job pour le pipeline claim-first.

    Args:
        doc_ids: Liste des document IDs à traiter
        tenant_id: Tenant ID
        cache_dir: Répertoire du cache d'extraction

    Returns:
        Statistiques de traitement
    """
    from knowbase.claimfirst.orchestrator import ClaimFirstOrchestrator
    from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache, list_cached_documents
    from knowbase.claimfirst.extractors.claim_extractor import MockLLMClient

    # Initialisation
    redis_client = _get_redis_client()
    _update_state(
        redis_client,
        status="STARTING",
        total_documents=len(doc_ids),
        processed=0,
        current_document="",
        phase="INIT",
    )

    logger.info(
        f"[OSMOSE:ClaimFirst:Worker] Starting job for {len(doc_ids)} documents, "
        f"tenant={tenant_id}"
    )

    # Obtenir les clients (imports tardifs pour éviter les problèmes de dépendances)
    llm_client = _get_llm_client()
    neo4j_driver = _get_neo4j_driver()

    # Créer l'orchestrateur
    orchestrator = ClaimFirstOrchestrator(
        llm_client=llm_client,
        neo4j_driver=neo4j_driver,
        tenant_id=tenant_id,
        persist_enabled=True,
    )

    # Mapper doc_id → cache_path
    cache_map = _build_cache_map(cache_dir)

    # Traiter chaque document
    results = {
        "processed": 0,
        "failed": 0,
        "skipped": 0,
        "total_claims": 0,
        "total_entities": 0,
        "errors": [],
    }

    for i, doc_id in enumerate(doc_ids):
        try:
            _update_state(
                redis_client,
                status="PROCESSING",
                current_document=doc_id,
                processed=i,
                phase="LOADING",
            )

            # Trouver le cache
            cache_path = cache_map.get(doc_id)
            if not cache_path:
                logger.warning(f"[OSMOSE:ClaimFirst:Worker] No cache for {doc_id}, skipping")
                results["skipped"] += 1
                continue

            # Charger depuis le cache
            cache_result = load_pass0_from_cache(cache_path, tenant_id)
            if not cache_result.success:
                logger.error(f"[OSMOSE:ClaimFirst:Worker] Failed to load cache for {doc_id}")
                results["failed"] += 1
                results["errors"].append(f"{doc_id}: cache load failed")
                continue

            # Traiter
            _update_state(redis_client, phase="EXTRACTING")
            result = orchestrator.process_and_persist(
                doc_id=doc_id,
                cache_result=cache_result,
                tenant_id=tenant_id,
            )

            # Mettre à jour les stats
            results["processed"] += 1
            results["total_claims"] += result.claim_count
            results["total_entities"] += result.entity_count

            logger.info(
                f"[OSMOSE:ClaimFirst:Worker] Processed {doc_id}: "
                f"{result.claim_count} claims, {result.entity_count} entities"
            )

        except Exception as e:
            logger.error(f"[OSMOSE:ClaimFirst:Worker] Error processing {doc_id}: {e}")
            results["failed"] += 1
            results["errors"].append(f"{doc_id}: {str(e)}")

    # Finalisation
    _update_state(
        redis_client,
        status="COMPLETED",
        processed=results["processed"],
        failed=results["failed"],
        phase="DONE",
    )

    logger.info(
        f"[OSMOSE:ClaimFirst:Worker] Job completed: "
        f"{results['processed']}/{len(doc_ids)} processed, "
        f"{results['failed']} failed, {results['skipped']} skipped"
    )

    # Cleanup driver
    if neo4j_driver:
        neo4j_driver.close()

    return results


def _get_llm_client():
    """
    Obtient le client LLM.

    Essaie OpenAI d'abord, puis fallback sur le mock.
    """
    import os

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            from openai import OpenAI
            return OpenAI(api_key=openai_key)
        except ImportError:
            logger.warning("[OSMOSE:ClaimFirst:Worker] OpenAI not installed, using mock")

    # Fallback: mock client
    from knowbase.claimfirst.extractors.claim_extractor import MockLLMClient
    logger.warning("[OSMOSE:ClaimFirst:Worker] Using MockLLMClient (no API key)")
    return MockLLMClient()


def _get_neo4j_driver():
    """Obtient le driver Neo4j."""
    import os

    try:
        from neo4j import GraphDatabase

        uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

        return GraphDatabase.driver(uri, auth=(user, password))
    except Exception as e:
        logger.error(f"[OSMOSE:ClaimFirst:Worker] Failed to connect to Neo4j: {e}")
        return None


def _build_cache_map(cache_dir: str) -> Dict[str, str]:
    """
    Construit un mapping doc_id → cache_path.

    Args:
        cache_dir: Répertoire du cache

    Returns:
        Dict doc_id → cache_path
    """
    from knowbase.stratified.pass0.cache_loader import list_cached_documents

    cache_map = {}
    documents = list_cached_documents(cache_dir)

    for doc_info in documents:
        doc_id = doc_info.get("document_id")
        cache_path = doc_info.get("cache_path")
        if doc_id and cache_path:
            cache_map[doc_id] = cache_path

    return cache_map


def get_claimfirst_status() -> dict:
    """
    Récupère l'état actuel du job claim-first.

    Returns:
        État du job
    """
    redis_client = _get_redis_client()
    return _get_state(redis_client)


def cancel_claimfirst_job() -> bool:
    """
    Annule le job claim-first en cours.

    Returns:
        True si annulé, False sinon
    """
    redis_client = _get_redis_client()
    state = _get_state(redis_client)

    if state.get("status") in ["PROCESSING", "STARTING"]:
        _update_state(redis_client, status="CANCELLING")
        return True

    return False


__all__ = [
    "claimfirst_process_job",
    "get_claimfirst_status",
    "cancel_claimfirst_job",
    "CLAIMFIRST_STATE_KEY",
]
