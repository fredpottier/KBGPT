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
        logger.info(
            f"[OSMOSE:ClaimFirst:Worker] === Document {i+1}/{len(doc_ids)}: {doc_id} ==="
        )
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

    # Phase 9 : Détection cross-doc (après TOUS les documents)
    if results["processed"] >= 2 and neo4j_driver:
        try:
            _update_state(redis_client, phase="CROSS_DOC_CHAINS")
            logger.info("[OSMOSE:ClaimFirst:Worker] Phase 9: Detecting cross-doc chains...")
            cross_doc_result = _detect_cross_doc_chains(neo4j_driver, tenant_id)
            results["cross_doc_chains"] = cross_doc_result.get("chains_persisted", 0)
            logger.info(
                f"  → {cross_doc_result.get('chains_persisted', 0)} cross-doc chains created"
            )
        except Exception as e:
            logger.error(f"[OSMOSE:ClaimFirst:Worker] Cross-doc detection failed: {e}")
            results["cross_doc_chains"] = 0

    # Phase 10 : Canonicalisation cross-doc des entités (après TOUS les documents)
    if results["processed"] >= 2 and neo4j_driver:
        try:
            _update_state(redis_client, phase="CANONICALIZE_ENTITIES")
            logger.info("[OSMOSE:ClaimFirst:Worker] Phase 10: Canonicalizing entities cross-doc...")
            canon_result = _canonicalize_entities_cross_doc(neo4j_driver, tenant_id)
            results["entities_merged"] = canon_result.get("total_merges", 0)
            results["hubs_annotated"] = canon_result.get("hubs_annotated", 0)
            logger.info(
                f"  → {canon_result.get('total_merges', 0)} entities merged, "
                f"{canon_result.get('hubs_annotated', 0)} hubs annotated"
            )
        except Exception as e:
            logger.error(f"[OSMOSE:ClaimFirst:Worker] Entity canonicalization failed: {e}")
            results["entities_merged"] = 0

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


def _detect_cross_doc_chains(neo4j_driver, tenant_id: str) -> dict:
    """
    Détecte et persiste les chaînes cross-document après import.

    Réutilise la logique de detect_cross_doc_chains.py mais inline
    pour éviter les dépendances script.
    """
    import json
    from collections import defaultdict
    from knowbase.claimfirst.composition.chain_detector import ChainDetector

    with neo4j_driver.session() as session:
        # 1. Charger claims avec structured_form
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WHERE c.structured_form_json IS NOT NULL
            RETURN c.claim_id AS claim_id, c.doc_id AS doc_id,
                   c.structured_form_json AS sf_json, c.confidence AS confidence
            """,
            tid=tenant_id,
        )
        claims = []
        for r in result:
            try:
                sf = json.loads(r["sf_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            claims.append({
                "claim_id": r["claim_id"],
                "doc_id": r["doc_id"],
                "structured_form": sf,
                "confidence": r["confidence"] or 0.5,
            })

        doc_ids = list({c["doc_id"] for c in claims})
        if len(doc_ids) < 2:
            logger.info("[OSMOSE:ClaimFirst:Worker] < 2 documents, skipping cross-doc")
            return {"chains_persisted": 0}

        # 2. Entity index
        eidx = session.run(
            "MATCH (e:Entity {tenant_id: $tid}) RETURN e.normalized_name AS norm, e.entity_id AS eid",
            tid=tenant_id,
        )
        entity_index = {r["norm"]: r["eid"] for r in eidx if r["norm"]}

        # 3. Hub detection
        total_docs = len(doc_ids)
        hub_result = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim)
            WHERE c.structured_form_json IS NOT NULL
            WITH e, count(DISTINCT c.doc_id) AS nb_docs, count(c) AS nb_claims
            RETURN e.normalized_name AS name, nb_docs, nb_claims
            """,
            tid=tenant_id,
        )
        hub_entities = set()
        for r in hub_result:
            if r["nb_claims"] > 200 or (r["nb_docs"] >= total_docs and r["nb_claims"] / max(r["nb_docs"], 1) > 150.0):
                hub_entities.add(r["name"])

        logger.info(f"  → {len(claims)} claims SF, {len(doc_ids)} docs, {len(hub_entities)} hubs exclus")

        # 4. Detect
        idf_map = ChainDetector.compute_idf(claims, entity_index=entity_index)
        detector = ChainDetector()
        links = detector.detect_cross_doc(
            claims, hub_entities=hub_entities,
            entity_index=entity_index, idf_map=idf_map,
        )

        logger.info(f"  → {len(links)} cross-doc chains detected")

        # 5. Persist
        persisted = 0
        for link in links:
            jk_idf = idf_map.get(link.join_key, 0.0)
            r = session.run(
                """
                MATCH (c1:Claim {claim_id: $src, tenant_id: $tid})
                MATCH (c2:Claim {claim_id: $tgt, tenant_id: $tid})
                MERGE (c1)-[r:CHAINS_TO]->(c2)
                SET r.confidence = 1.0,
                    r.basis = $basis,
                    r.join_key = $jk,
                    r.join_key_idf = $idf,
                    r.method = 'spo_join_cross_doc',
                    r.join_method = $jm,
                    r.derived = true,
                    r.cross_doc = true,
                    r.source_doc_id = $sdid,
                    r.target_doc_id = $tdid,
                    r.join_key_freq = $freq
                RETURN r IS NOT NULL AS ok
                """,
                src=link.source_claim_id,
                tgt=link.target_claim_id,
                tid=tenant_id,
                basis=f"join_key={link.join_key}",
                jk=link.join_key,
                idf=jk_idf,
                jm=link.join_method,
                sdid=link.source_doc_id,
                tdid=link.target_doc_id,
                freq=link.join_key_freq,
            )
            if r.single():
                persisted += 1

        return {"chains_persisted": persisted, "chains_detected": len(links)}


def _canonicalize_entities_cross_doc(neo4j_driver, tenant_id: str) -> dict:
    """
    Canonicalise les entités cross-document après import.

    Fusionne les variantes version et les containments,
    puis annote les hubs.
    """
    from collections import defaultdict
    from knowbase.claimfirst.models.entity import (
        Entity,
        strip_version_qualifier,
        is_valid_entity_name,
    )

    with neo4j_driver.session() as session:
        # 1. Charger les entities
        result = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})
            OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
            WITH e, count(c) AS claim_count
            RETURN e.entity_id AS entity_id,
                   e.name AS name,
                   e.normalized_name AS normalized_name,
                   e.entity_type AS entity_type,
                   claim_count
            """,
            tid=tenant_id,
        )
        entities = [dict(record) for record in result]
        logger.info(f"  → {len(entities)} entities loaded")

        if not entities:
            return {"total_merges": 0, "hubs_annotated": 0}

        # 2. Groupes version
        groups: dict = defaultdict(list)
        for e in entities:
            base_name, version = strip_version_qualifier(e["name"])
            base_normalized = Entity.normalize(base_name)
            groups[base_normalized].append((e, version))

        version_merged = 0
        for base_norm, members in groups.items():
            if len(members) <= 1:
                continue
            canonical = None
            for m, version in members:
                if version is None:
                    canonical = m
                    break
            if canonical is None:
                canonical = max([m for m, _ in members], key=lambda m: m["claim_count"])

            for m, _ in members:
                if m["entity_id"] != canonical["entity_id"]:
                    session.run(
                        """
                        MATCH (source:Entity {entity_id: $source_id, tenant_id: $tid})
                        MATCH (target:Entity {entity_id: $target_id, tenant_id: $tid})
                        OPTIONAL MATCH (c:Claim)-[r:ABOUT]->(source)
                        WITH source, target, collect(c) AS claims, collect(r) AS rels
                        FOREACH (r IN rels | DELETE r)
                        WITH source, target, claims
                        UNWIND claims AS c
                        MERGE (c)-[:ABOUT]->(target)
                        WITH source, target
                        SET target.aliases = CASE
                            WHEN target.aliases IS NULL THEN [source.name]
                            WHEN NOT source.name IN target.aliases THEN target.aliases + source.name
                            ELSE target.aliases
                        END
                        WITH source, target
                        DETACH DELETE source
                        """,
                        source_id=m["entity_id"],
                        target_id=canonical["entity_id"],
                        tid=tenant_id,
                    )
                    version_merged += 1

        # 3. Containments
        by_norm: dict = {}
        for e in entities:
            norm = e.get("normalized_name") or Entity.normalize(e["name"])
            if norm not in by_norm:  # Garder le premier (certains ont pu être supprimés)
                by_norm[norm] = e

        parents_by_child: dict = defaultdict(list)
        norms = sorted(by_norm.keys(), key=len)
        for i, short_norm in enumerate(norms):
            if len(short_norm) < 4:
                continue
            for long_norm in norms[i + 1:]:
                words_long = long_norm.split()
                words_short = short_norm.split()
                extra_words = len(words_long) - len(words_short)
                if extra_words > 2 or extra_words < 1:
                    continue
                if words_long[-len(words_short):] == words_short:
                    parents_by_child[short_norm].append(long_norm)

        containment_merged = 0
        for child_norm, parent_norms in parents_by_child.items():
            if len(parent_norms) != 1:
                continue
            source = by_norm.get(child_norm)
            target = by_norm.get(parent_norms[0])
            if not source or not target:
                continue
            if not is_valid_entity_name(source["name"]) or not is_valid_entity_name(target["name"]):
                continue
            session.run(
                """
                MATCH (source:Entity {entity_id: $source_id, tenant_id: $tid})
                MATCH (target:Entity {entity_id: $target_id, tenant_id: $tid})
                OPTIONAL MATCH (c:Claim)-[r:ABOUT]->(source)
                WITH source, target, collect(c) AS claims, collect(r) AS rels
                FOREACH (r IN rels | DELETE r)
                WITH source, target, claims
                UNWIND claims AS c
                MERGE (c)-[:ABOUT]->(target)
                WITH source, target
                SET target.aliases = CASE
                    WHEN target.aliases IS NULL THEN [source.name]
                    WHEN NOT source.name IN target.aliases THEN target.aliases + source.name
                    ELSE target.aliases
                END
                WITH source, target
                DETACH DELETE source
                """,
                source_id=source["entity_id"],
                target_id=target["entity_id"],
                tid=tenant_id,
            )
            containment_merged += 1

        # 4. Annoter les hubs
        hub_result = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim)
            WITH e, count(c) AS degree
            WHERE degree > 50
            SET e.is_hub = true, e.hub_degree = degree
            RETURN count(e) AS hubs_annotated
            """,
            tid=tenant_id,
        )
        hubs_annotated = hub_result.single()["hubs_annotated"]

        logger.info(
            f"  → {version_merged} version + {containment_merged} containment merges, "
            f"{hubs_annotated} hubs"
        )

        return {
            "version_merges": version_merged,
            "containment_merges": containment_merged,
            "total_merges": version_merged + containment_merged,
            "hubs_annotated": hubs_annotated,
        }


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
