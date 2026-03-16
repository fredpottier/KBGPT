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
    from knowbase.claimfirst.linkers.facet_registry import FacetRegistry
    from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache, list_cached_documents
    from knowbase.claimfirst.extractors.claim_extractor import MockLLMClient

    # Initialisation
    redis_client = _get_redis_client()

    # Récupérer le job_id RQ
    from rq import get_current_job
    rq_job = get_current_job()
    rq_job_id = rq_job.id if rq_job else "unknown"

    job_started_at = time.time()

    _update_state(
        redis_client,
        status="STARTING",
        job_id=rq_job_id,
        total_documents=len(doc_ids),
        processed=0,
        failed=0,
        skipped=0,
        total_claims=0,
        total_entities=0,
        current_document="",
        current_filename="",
        phase="INIT",
        started_at=job_started_at,
    )

    logger.info(
        f"[OSMOSE:ClaimFirst:Worker] Starting job {rq_job_id} for {len(doc_ids)} documents, "
        f"tenant={tenant_id}"
    )

    # Obtenir les clients (imports tardifs pour éviter les problèmes de dépendances)
    llm_client = _get_llm_client()
    neo4j_driver = _get_neo4j_driver()

    # Instancier FacetRegistry partagé entre tous les documents
    facet_registry = FacetRegistry(tenant_id)
    facet_registry.load_from_neo4j(neo4j_driver)

    # Créer l'orchestrateur
    orchestrator = ClaimFirstOrchestrator(
        llm_client=llm_client,
        neo4j_driver=neo4j_driver,
        tenant_id=tenant_id,
        persist_enabled=True,
        facet_registry=facet_registry,
    )

    # Mapper doc_id → cache_path et doc_id → filename lisible
    cache_map = _build_cache_map(cache_dir)
    filename_map = _build_filename_map(doc_ids)

    # Traiter chaque document
    results = {
        "processed": 0,
        "failed": 0,
        "skipped": 0,
        "total_claims": 0,
        "total_entities": 0,
        "errors": [],
    }

    # Circuit breaker : arrêter si trop de docs consécutifs sans claims (vLLM down)
    consecutive_empty = 0
    MAX_CONSECUTIVE_EMPTY = 10  # 10 docs à 0 claims + vLLM health check avant arrêt

    # Persistence incrémentale des facets (crash-resilient)
    FACET_PERSIST_INTERVAL = 10  # Persister les facets toutes les N docs

    for i, doc_id in enumerate(doc_ids):
        filename = filename_map.get(doc_id, doc_id[:40])
        logger.info(
            f"[OSMOSE:ClaimFirst:Worker] === Document {i+1}/{len(doc_ids)}: {filename} ==="
        )
        try:
            _update_state(
                redis_client,
                status="PROCESSING",
                current_document=doc_id,
                current_filename=filename,
                processed=i,
                failed=results["failed"],
                skipped=results["skipped"],
                total_claims=results["total_claims"],
                total_entities=results["total_entities"],
                phase="LOADING",
            )

            # Trouver le cache
            cache_path = cache_map.get(doc_id)
            if not cache_path:
                logger.warning(f"[OSMOSE:ClaimFirst:Worker] No cache for {doc_id}, skipping")
                results["skipped"] += 1
                _update_state(redis_client, skipped=results["skipped"],
                              errors=json.dumps(results["errors"]))
                continue

            # Charger depuis le cache
            cache_result = load_pass0_from_cache(cache_path, tenant_id)
            if not cache_result.success:
                logger.error(f"[OSMOSE:ClaimFirst:Worker] Failed to load cache for {doc_id}")
                results["failed"] += 1
                results["errors"].append(f"{filename}: cache load failed")
                _update_state(redis_client, failed=results["failed"],
                              errors=json.dumps(results["errors"]))
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

            _update_state(
                redis_client,
                processed=results["processed"],
                total_claims=results["total_claims"],
                total_entities=results["total_entities"],
                phase="PERSISTED",
            )

            logger.info(
                f"[OSMOSE:ClaimFirst:Worker] Processed {doc_id}: "
                f"{result.claim_count} claims, {result.entity_count} entities"
            )

            # Persistence incrémentale des facets (crash-resilient)
            if (results["processed"] % FACET_PERSIST_INTERVAL == 0
                    and neo4j_driver and results["processed"] > 0):
                try:
                    fp = facet_registry.persist_to_neo4j(neo4j_driver)
                    if fp > 0:
                        logger.info(
                            f"[OSMOSE:ClaimFirst:Worker] Incremental facet persist: "
                            f"{fp} facets saved (checkpoint at doc {results['processed']})"
                        )
                except Exception as e:
                    logger.warning(
                        f"[OSMOSE:ClaimFirst:Worker] Incremental facet persist failed: {e}"
                    )

            # Circuit breaker : détecter docs vides consécutifs (vLLM down silencieux)
            if result.claim_count == 0:
                consecutive_empty += 1
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                    # Vérifier si vLLM est réellement down avant de couper
                    vllm_actually_down = False
                    try:
                        import httpx
                        burst_state = redis_client.get("osmose:burst:state")
                        if burst_state:
                            import json as _json
                            bs = _json.loads(burst_state)
                            vllm_url = bs.get("vllm_url", "")
                            if vllm_url:
                                resp = httpx.get(f"{vllm_url}/v1/models", timeout=5.0)
                                vllm_actually_down = resp.status_code != 200
                    except Exception:
                        vllm_actually_down = True

                    if vllm_actually_down:
                        remaining = doc_ids[i + 1:]
                        logger.error(
                            f"[OSMOSE:ClaimFirst:Worker] CIRCUIT BREAKER: "
                            f"{consecutive_empty} documents consécutifs avec 0 claims "
                            f"ET vLLM confirmé down. Arrêt du job. "
                            f"{len(remaining)} documents restants non traités."
                        )
                        # Persister les facets avant arrêt
                        if neo4j_driver:
                            try:
                                fp = facet_registry.persist_to_neo4j(neo4j_driver)
                                logger.info(f"[OSMOSE:ClaimFirst:Worker] Emergency facet persist: {fp} facets saved before circuit breaker")
                            except Exception:
                                pass
                        results["circuit_breaker"] = True
                        results["remaining_doc_ids"] = remaining
                        _update_state(
                            redis_client,
                            status="STOPPED_CIRCUIT_BREAKER",
                            phase="VLLM_UNAVAILABLE",
                            remaining=len(remaining),
                        )
                        break
                    else:
                        logger.warning(
                            f"[OSMOSE:ClaimFirst:Worker] {consecutive_empty} docs "
                            f"consécutifs à 0 claims mais vLLM OK — on continue."
                        )
                        consecutive_empty = 0
            else:
                consecutive_empty = 0

        except Exception as e:
            # Circuit breaker : arrêt immédiat si vLLM explicitement down
            error_str = str(e)
            if "vLLM" in error_str or "VLLMUnavailable" in type(e).__name__:
                remaining = doc_ids[i + 1:]
                logger.error(
                    f"[OSMOSE:ClaimFirst:Worker] CIRCUIT BREAKER (vLLM error): {e}. "
                    f"Arrêt du job. {len(remaining)} documents restants."
                )
                # Persister les facets avant arrêt
                if neo4j_driver:
                    try:
                        fp = facet_registry.persist_to_neo4j(neo4j_driver)
                        logger.info(f"[OSMOSE:ClaimFirst:Worker] Emergency facet persist: {fp} facets saved before circuit breaker")
                    except Exception:
                        pass
                results["failed"] += 1
                results["errors"].append(f"{doc_id}: {error_str}")
                results["circuit_breaker"] = True
                results["remaining_doc_ids"] = remaining
                _update_state(
                    redis_client,
                    status="STOPPED_CIRCUIT_BREAKER",
                    phase="VLLM_UNAVAILABLE",
                    remaining=len(remaining),
                    failed=results["failed"],
                    errors=json.dumps(results["errors"]),
                )
                break

            logger.error(f"[OSMOSE:ClaimFirst:Worker] Error processing {doc_id}: {e}")
            results["failed"] += 1
            results["errors"].append(f"{filename}: {error_str}")
            _update_state(redis_client, failed=results["failed"],
                          errors=json.dumps(results["errors"]))

    # Phase 8.5 : Persister le FacetRegistry (après TOUS les documents)
    if neo4j_driver:
        try:
            facets_persisted = facet_registry.persist_to_neo4j(neo4j_driver)
            results["facets_persisted"] = facets_persisted
            near_dups = facet_registry.get_near_duplicate_queue()
            if near_dups:
                logger.info(
                    f"[OSMOSE:ClaimFirst:Worker] FacetRegistry: {len(near_dups)} "
                    f"near-duplicates détectés (review manuelle requise)"
                )
                for k1, k2, score in near_dups[:10]:
                    logger.info(f"  → '{k1}' ≈ '{k2}' (score={score:.2f})")
            reg_stats = facet_registry.get_stats()
            logger.info(
                f"[OSMOSE:ClaimFirst:Worker] FacetRegistry: "
                f"{reg_stats['total']} total, "
                f"{reg_stats['by_lifecycle']} lifecycle, "
                f"{facets_persisted} persisted"
            )
        except Exception as e:
            logger.error(f"[OSMOSE:ClaimFirst:Worker] FacetRegistry persist failed: {e}")

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

    # Phase 11 : Clustering cross-doc (après canonicalisation des entités)
    if results["processed"] >= 2 and neo4j_driver:
        try:
            _update_state(redis_client, phase="CROSS_DOC_CLUSTERING")
            logger.info("[OSMOSE:ClaimFirst:Worker] Phase 11: Cross-doc clustering...")
            cluster_result = _cluster_cross_doc(neo4j_driver, tenant_id)
            results["cross_doc_clusters"] = cluster_result.get("clusters_created", 0)
            logger.info(
                f"  → {cluster_result.get('clusters_created', 0)} cross-doc clusters created"
            )
        except Exception as e:
            logger.error(f"[OSMOSE:ClaimFirst:Worker] Cross-doc clustering failed: {e}")
            results["cross_doc_clusters"] = 0

    # Phase 12 : Comparaison cross-doc QuestionSignatures
    if results["processed"] >= 2 and neo4j_driver:
        try:
            _update_state(redis_client, phase="QS_CROSS_DOC_COMPARISON")
            logger.info("[OSMOSE:ClaimFirst:Worker] Phase 12: QS cross-doc comparison...")
            qs_result = _compare_question_signatures_cross_doc(neo4j_driver, tenant_id)
            results["qs_comparisons"] = qs_result.get("comparisons_persisted", 0)
            logger.info(
                f"  → {qs_result.get('comparisons_persisted', 0)} QS comparisons persisted "
                f"({qs_result.get('evolutions', 0)} evolutions, "
                f"{qs_result.get('contradictions', 0)} contradictions)"
            )
        except Exception as e:
            logger.error(f"[OSMOSE:ClaimFirst:Worker] QS comparison failed: {e}")
            results["qs_comparisons"] = 0

    # Phase 13 : KG Hygiene Layer 1 (post-ingestion, scope = document_set)
    if results["processed"] >= 1 and neo4j_driver:
        try:
            _update_state(redis_client, phase="KG_HYGIENE_L1")
            logger.info("[OSMOSE:ClaimFirst:Worker] Phase 13: KG Hygiene L1...")
            from knowbase.hygiene.engine import HygieneEngine
            from knowbase.hygiene.models import HygieneRunScope
            hygiene = HygieneEngine(neo4j_driver, tenant_id)
            hygiene_result = hygiene.run(
                dry_run=False,
                layers=[1],
                scope=HygieneRunScope.DOCUMENT_SET,
                scope_params={"doc_ids": list(doc_ids)},
            )
            results["hygiene_l1"] = hygiene_result.total_actions
            logger.info(
                f"  → {hygiene_result.total_actions} hygiene actions "
                f"({hygiene_result.applied} applied, {hygiene_result.proposed} proposed)"
            )
        except Exception as e:
            logger.error(f"[OSMOSE:ClaimFirst:Worker] KG Hygiene L1 failed: {e}")
            results["hygiene_l1"] = 0

    # Finalisation
    elapsed = time.time() - job_started_at
    _update_state(
        redis_client,
        status="COMPLETED",
        processed=results["processed"],
        failed=results["failed"],
        skipped=results["skipped"],
        total_claims=results["total_claims"],
        total_entities=results["total_entities"],
        current_document="",
        current_filename="",
        phase="DONE",
        elapsed_seconds=int(elapsed),
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
                    r.join_key_freq = $freq,
                    r.join_key_name = $jkn
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
                jkn=link.join_key_name,
            )
            if r.single():
                persisted += 1

        return {"chains_persisted": persisted, "chains_detected": len(links)}


def _canonicalize_entities_cross_doc(neo4j_driver, tenant_id: str) -> dict:
    """
    Canonicalise les entités cross-document via MergeArbiter.

    Phase 10a: Gates déterministes (prefix-dedup, case-only, version strip)
    Phase 10b: LLM Merge Arbiter (corpus-grounded)
    Phase 10c: Orphan cleanup (hub annotation)
    """
    from knowbase.claimfirst.extractors.merge_arbiter import MergeArbiter

    with neo4j_driver.session() as session:
        # 1. Charger entités + 1 claim excerpt par entité
        result = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})
            OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
            WITH e, count(c) AS claim_count, collect(c.text)[0] AS sample_claim
            RETURN e.entity_id AS entity_id,
                   e.name AS name,
                   e.normalized_name AS normalized_name,
                   e.entity_type AS entity_type,
                   claim_count,
                   sample_claim
            """,
            tid=tenant_id,
        )
        entities = []
        claim_contexts: Dict[str, str] = {}
        for record in result:
            e = dict(record)
            entities.append(e)
            if e.get("sample_claim"):
                claim_contexts[e["entity_id"]] = e["sample_claim"]

        logger.info(f"  → {len(entities)} entities loaded")

        if not entities:
            return {"total_merges": 0, "hubs_annotated": 0}

        # 2. MergeArbiter resolve
        arbiter = MergeArbiter(batch_size=15, max_concurrent=3)
        merge_result = arbiter.resolve(entities, claim_contexts)

        # 3. Appliquer les merges déterministes + LLM
        all_merges = merge_result.deterministic_merges + merge_result.llm_merges
        total_merged = 0
        for merge in all_merges:
            for source_id in merge.source_ids:
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
                    source_id=source_id,
                    target_id=merge.target_id,
                    tid=tenant_id,
                )
                total_merged += 1

        # 4. Créer les relations SIMILAR_TO
        similar_created = 0
        for pair in merge_result.similar_pairs:
            session.run(
                """
                MATCH (e1:Entity {entity_id: $id1, tenant_id: $tid})
                MATCH (e2:Entity {entity_id: $id2, tenant_id: $tid})
                MERGE (e1)-[r:SIMILAR_TO]->(e2)
                SET r.confidence = $confidence,
                    r.reason = $reason,
                    r.evidence = $evidence
                """,
                id1=pair.entity_id_1,
                id2=pair.entity_id_2,
                tid=tenant_id,
                confidence=pair.confidence,
                reason=pair.reason,
                evidence=pair.evidence,
            )
            similar_created += 1

        # 5. Annoter les hubs
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

        stats = merge_result.stats
        logger.info(
            f"  → {stats['prefix_dedup']} prefix + {stats['case_only']} case + "
            f"{stats['version_strip']} version + {stats['llm_merge']} LLM merges, "
            f"{similar_created} SIMILAR_TO, {hubs_annotated} hubs"
        )

        return {
            "total_merges": total_merged,
            "deterministic_merges": stats["prefix_dedup"] + stats["case_only"] + stats["version_strip"],
            "llm_merges": stats["llm_merge"],
            "similar_to_created": similar_created,
            "hubs_annotated": hubs_annotated,
        }


def _cluster_cross_doc(neo4j_driver, tenant_id: str) -> dict:
    """
    Clustering cross-document via Jaccard sur entités partagées.

    Algorithme :
    1. Charger claims avec entités depuis Neo4j
    2. Index inversé entité → claims (entités dans 2+ docs uniquement)
    3. Comparer pairwise cross-doc au sein de chaque groupe d'entité
    4. Union-Find → clusters
    5. Persister ClaimCluster + IN_CLUSTER

    Pas de dépendance numpy — Jaccard + règles inline.
    """
    import re
    import uuid
    from collections import defaultdict

    # --- Fonctions utilitaires inline (copiées de ClaimClusterer) ---

    STOP_WORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "must", "shall",
        "can", "need", "to", "of", "in", "for", "on", "with", "at",
        "by", "from", "as", "into", "through", "during", "before",
        "after", "above", "below", "between", "under", "again",
        "further", "then", "once", "here", "there", "when", "where",
        "why", "how", "all", "each", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same",
        "so", "than", "too", "very", "just", "and", "but", "if",
        "or", "because", "until", "while", "this", "that", "these",
        "those", "which", "who", "whom", "what", "whose",
    }
    STRONG_OBLIGATION = {"must", "shall", "required", "mandatory", "obligatory"}
    WEAK_OBLIGATION = {"should", "recommended", "advisable"}
    PERMISSION = {"may", "can", "allowed", "permitted", "optional"}
    NEGATION_PATTERNS = [
        re.compile(r"\bnot\b"), re.compile(r"\bno\b"),
        re.compile(r"\bnever\b"), re.compile(r"\bnone\b"),
        re.compile(r"\bcannot\b"), re.compile(r"\bcan't\b"),
        re.compile(r"\bwon't\b"), re.compile(r"\bdon't\b"),
        re.compile(r"\bwithout\b"), re.compile(r"\bexcept\b"),
        re.compile(r"\bexclud"),
    ]

    def extract_key_tokens(text: str) -> set:
        tokens = re.findall(r"\b[a-zA-Z]+\b", text.lower())
        return {t for t in tokens if t not in STOP_WORDS and len(t) > 2}

    def jaccard(s1: set, s2: set) -> float:
        if not s1 or not s2:
            return 0.0
        return len(s1 & s2) / len(s1 | s2)

    def extract_modality(text: str) -> str:
        tl = text.lower()
        for w in STRONG_OBLIGATION:
            if re.search(rf"\b{w}\b", tl):
                return "strong"
        for w in WEAK_OBLIGATION:
            if re.search(rf"\b{w}\b", tl):
                return "weak"
        for w in PERMISSION:
            if re.search(rf"\b{w}\b", tl):
                return "permission"
        return "neutral"

    def has_inverted_negation(text1: str, text2: str) -> bool:
        def count_neg(text):
            tl = text.lower()
            return sum(1 for p in NEGATION_PATTERNS if p.search(tl))
        return (count_neg(text1) > 0) != (count_neg(text2) > 0)

    # --- Union-Find ---
    uf_parent: dict = {}

    def uf_find(x: str) -> str:
        if x not in uf_parent:
            uf_parent[x] = x
        if uf_parent[x] != x:
            uf_parent[x] = uf_find(uf_parent[x])
        return uf_parent[x]

    def uf_union(x: str, y: str) -> None:
        px, py = uf_find(x), uf_find(y)
        if px != py:
            uf_parent[px] = py

    MIN_JACCARD = 0.30
    MAX_CLAIMS_PER_ENTITY = 200

    with neo4j_driver.session() as session:
        # 1. Charger claims avec entités
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
            RETURN c.claim_id AS claim_id, c.doc_id AS doc_id,
                   c.text AS text, c.confidence AS confidence,
                   c.structured_form_json AS structured_form_json,
                   c.quality_scores_json AS quality_scores_json,
                   collect(e.normalized_name) AS entity_names
            """,
            tid=tenant_id,
        )
        claims_data = {}
        entity_to_claims = defaultdict(set)
        for r in result:
            cid = r["claim_id"]
            claims_data[cid] = {
                "claim_id": cid,
                "doc_id": r["doc_id"],
                "text": r["text"] or "",
                "confidence": r["confidence"] or 0.5,
                "entity_names": r["entity_names"] or [],
                "structured_form_json": r.get("structured_form_json"),
                "quality_scores_json": r.get("quality_scores_json"),
            }
            for ename in r["entity_names"]:
                entity_to_claims[ename].add(cid)

        logger.info(f"  → {len(claims_data)} claims avec entités chargées")

        # 2. Filtrer : entités dans 2+ docs, exclure hubs
        cross_doc_groups = {}
        for ename, cids in entity_to_claims.items():
            doc_ids = {claims_data[cid]["doc_id"] for cid in cids if cid in claims_data}
            if len(doc_ids) < 2:
                continue
            if len(cids) > MAX_CLAIMS_PER_ENTITY:
                logger.debug(f"  Hub exclu: '{ename}' ({len(cids)} claims)")
                continue
            cross_doc_groups[ename] = cids

        logger.info(f"  → {len(cross_doc_groups)} entités cross-doc candidates")

        if not cross_doc_groups:
            return {"clusters_created": 0, "pairs_validated": 0}

        # 3. Pré-calculer tokens par claim
        tokens_cache = {}
        modality_cache = {}
        for cid, cdata in claims_data.items():
            tokens_cache[cid] = extract_key_tokens(cdata["text"])
            modality_cache[cid] = extract_modality(cdata["text"])

        # 4. Comparer pairwise cross-doc au sein de chaque groupe
        pairs_validated = 0
        for ename, cids in cross_doc_groups.items():
            cids_list = sorted(cids)
            for i, cid1 in enumerate(cids_list):
                c1 = claims_data.get(cid1)
                if not c1:
                    continue
                for cid2 in cids_list[i + 1:]:
                    c2 = claims_data.get(cid2)
                    if not c2:
                        continue
                    # Cross-doc uniquement
                    if c1["doc_id"] == c2["doc_id"]:
                        continue
                    # Jaccard sur tokens
                    j = jaccard(tokens_cache[cid1], tokens_cache[cid2])
                    if j < MIN_JACCARD:
                        continue
                    # Même modalité
                    if modality_cache[cid1] != modality_cache[cid2]:
                        continue
                    # Pas de négation inversée
                    if has_inverted_negation(c1["text"], c2["text"]):
                        continue
                    # Validé → union
                    uf_union(cid1, cid2)
                    pairs_validated += 1

        logger.info(f"  → {pairs_validated} paires cross-doc validées")

        if pairs_validated == 0:
            return {"clusters_created": 0, "pairs_validated": 0}

        # 5. Grouper par racine Union-Find
        groups = defaultdict(set)
        for cid in uf_parent:
            root = uf_find(cid)
            groups[root].add(cid)

        # Filtrer les groupes cross-doc (2+ docs)
        cross_clusters = []
        for root, cids in groups.items():
            doc_ids = {claims_data[cid]["doc_id"] for cid in cids if cid in claims_data}
            if len(doc_ids) < 2:
                continue
            cross_clusters.append((sorted(cids), sorted(doc_ids)))

        logger.info(f"  → {len(cross_clusters)} clusters cross-doc formés")

        # 6. Persister
        clusters_created = 0
        for cids, doc_ids in cross_clusters:
            cluster_id = f"cluster_xd_{uuid.uuid4().hex[:12]}"
            claim_objs = [claims_data[cid] for cid in cids if cid in claims_data]
            if not claim_objs:
                continue
            best = max(claim_objs, key=lambda c: c["confidence"])
            avg_conf = sum(c["confidence"] for c in claim_objs) / len(claim_objs)

            # MERGE le ClaimCluster
            session.run(
                """
                MERGE (cc:ClaimCluster {cluster_id: $cid, tenant_id: $tid})
                SET cc.canonical_label = $label,
                    cc.claim_count = $claim_count,
                    cc.doc_count = $doc_count,
                    cc.doc_ids = $doc_ids,
                    cc.avg_confidence = $avg_conf,
                    cc.cross_doc = true,
                    cc.method = 'jaccard_cross_doc'
                """,
                cid=cluster_id,
                tid=tenant_id,
                label=best["text"][:100],
                claim_count=len(cids),
                doc_count=len(doc_ids),
                doc_ids=doc_ids,
                avg_conf=avg_conf,
            )

            # Créer les relations IN_CLUSTER
            for claim_id in cids:
                session.run(
                    """
                    MATCH (c:Claim {claim_id: $claim_id, tenant_id: $tid})
                    MATCH (cc:ClaimCluster {cluster_id: $cluster_id, tenant_id: $tid})
                    MERGE (c)-[:IN_CLUSTER]->(cc)
                    """,
                    claim_id=claim_id,
                    tid=tenant_id,
                    cluster_id=cluster_id,
                )

            clusters_created += 1

        logger.info(f"  → {clusters_created} clusters cross-doc persistés")

        # 7. Champion/Redundant marking (quality-based scoring)
        champions_marked = 0
        redundants_marked = 0
        for cids, doc_ids_cluster in cross_clusters:
            claim_objs = [claims_data[cid] for cid in cids if cid in claims_data]
            if not claim_objs:
                continue

            # Score: 100*verif + 10*has_sf + 5*entity_count - 0.02*text_len
            def _score_quality(c: dict) -> float:
                import json as _json
                verif = 0.85
                qs_json = c.get("quality_scores_json")
                if qs_json:
                    try:
                        qs = _json.loads(qs_json)
                        verif = qs.get("verif_score", 0.85)
                    except (ValueError, TypeError):
                        pass
                has_sf = 1.0 if c.get("structured_form_json") else 0.0
                entity_count = len(c.get("entity_names", []))
                text_len = len(c.get("text", ""))
                return 100 * verif + 10 * has_sf + 5 * entity_count - 0.02 * text_len

            scored = [(c, _score_quality(c)) for c in claim_objs]
            scored.sort(key=lambda x: x[1], reverse=True)
            champion = scored[0][0]

            session.run(
                """
                MATCH (c:Claim {claim_id: $cid, tenant_id: $tid})
                SET c.is_champion = true
                """,
                cid=champion["claim_id"],
                tid=tenant_id,
            )
            champions_marked += 1

            for c, _ in scored[1:]:
                session.run(
                    """
                    MATCH (c:Claim {claim_id: $cid, tenant_id: $tid})
                    SET c.redundant = true, c.champion_claim_id = $champion_id
                    """,
                    cid=c["claim_id"],
                    tid=tenant_id,
                    champion_id=champion["claim_id"],
                )
                redundants_marked += 1

        logger.info(
            f"  → {champions_marked} champions, {redundants_marked} redundants marked"
        )

        return {
            "clusters_created": clusters_created,
            "pairs_validated": pairs_validated,
            "champions_marked": champions_marked,
            "redundants_marked": redundants_marked,
        }


def _compare_question_signatures_cross_doc(neo4j_driver, tenant_id: str) -> dict:
    """
    Compare les QuestionSignatures cross-document.

    Phase 12 : Charge toutes les QS depuis Neo4j, exécute compare_all(),
    puis persiste les ComparisonResult comme relations QS_COMPARED.
    """
    from knowbase.claimfirst.models.question_signature import QuestionSignature
    from knowbase.claimfirst.comparisons.qs_comparator import compare_all

    with neo4j_driver.session() as session:
        # 1. Charger toutes les QS
        result = session.run(
            """
            MATCH (qs:QuestionSignature {tenant_id: $tid})
            RETURN qs
            """,
            tid=tenant_id,
        )
        signatures = []
        for record in result:
            node = record["qs"]
            try:
                qs = QuestionSignature.from_neo4j_record(dict(node))
                signatures.append(qs)
            except Exception as e:
                logger.debug(f"  Skipping QS: {e}")
                continue

        logger.info(f"  → {len(signatures)} QuestionSignatures loaded from Neo4j")

        if len(signatures) < 2:
            return {"comparisons_persisted": 0, "evolutions": 0, "contradictions": 0}

        # 2. Comparer
        comparisons = compare_all(signatures)
        logger.info(f"  → {len(comparisons)} comparisons produced")

        # 3. Persister les résultats comme relations
        persisted = 0
        type_counts = {"EVOLUTION": 0, "CONTRADICTION": 0, "CONVERGENCE": 0, "AGREEMENT": 0}

        for comp in comparisons:
            comp_type = comp.comparison_type.value
            type_counts[comp_type] = type_counts.get(comp_type, 0) + 1

            session.run(
                """
                MATCH (qs1:QuestionSignature {qs_id: $qs_a_id})
                MATCH (qs2:QuestionSignature {qs_id: $qs_b_id})
                MERGE (qs1)-[r:QS_COMPARED]->(qs2)
                SET r.comparison_type = $comp_type,
                    r.confidence = $confidence,
                    r.explanation = $explanation,
                    r.dimension_key = $dim_key,
                    r.same_scope = $same_scope,
                    r.value_a = $value_a,
                    r.value_b = $value_b,
                    r.direction = $direction,
                    r.cross_doc = true
                """,
                qs_a_id=comp.qs_a_id,
                qs_b_id=comp.qs_b_id,
                comp_type=comp_type,
                confidence=comp.confidence,
                explanation=comp.explanation,
                dim_key=comp.dimension_key,
                same_scope=comp.same_scope,
                value_a=comp.value_diff.value_a if comp.value_diff else None,
                value_b=comp.value_diff.value_b if comp.value_diff else None,
                direction=comp.value_diff.direction if comp.value_diff else None,
            )
            persisted += 1

        logger.info(f"  → Type distribution: {type_counts}")

        return {
            "comparisons_persisted": persisted,
            "evolutions": type_counts.get("EVOLUTION", 0),
            "contradictions": type_counts.get("CONTRADICTION", 0),
            "convergences": type_counts.get("CONVERGENCE", 0),
            "agreements": type_counts.get("AGREEMENT", 0),
            "total_qs": len(signatures),
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


def _build_filename_map(doc_ids: List[str]) -> Dict[str, str]:
    """
    Construit un mapping doc_id → filename lisible.

    Extrait le nom humain depuis le doc_id (format: 004_SAP-016_nom_fichier_hashcourt).
    """
    import re
    filename_map = {}
    for doc_id in doc_ids:
        # doc_id format: "004_SAP-016_Name_Of_File_hashcourt"
        # Retirer le hash court final (8 chars hex après le dernier _)
        cleaned = re.sub(r'_[0-9a-f]{8,12}$', '', doc_id)
        # Remplacer les underscores par des espaces pour lisibilité
        cleaned = cleaned.replace('_', ' ')
        # Tronquer si trop long
        if len(cleaned) > 60:
            cleaned = cleaned[:57] + "..."
        filename_map[doc_id] = cleaned
    return filename_map


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
