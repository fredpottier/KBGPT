"""
FacetEngine V2 — Orchestrateur.

Pipeline complet :
  F1. Bootstrap → charger/creer les facettes (reutilise les facettes existantes)
  F2. Normalization → deduplicate facettes proches
  F3. Prototype Build → embeddings composites par facette
  F4. Assignment → scoring multi-signal claim→facette
  F5. Governance → metriques de sante

Usage:
    from knowbase.facets.orchestrator import run_facet_engine_v2
    stats = run_facet_engine_v2(driver, tenant_id="default")
"""
from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

import numpy as np

from knowbase.facets.models import Facet, FacetAssignment, FacetHealth
from knowbase.facets.bootstrap import bootstrap_from_existing_facets
from knowbase.facets.normalizer import normalize_facets
from knowbase.facets.prototype_builder import build_all_prototypes
from knowbase.facets.scorer import batch_score_claims
from knowbase.facets.governance import compute_health

logger = logging.getLogger(__name__)


def _load_claim_entity_map(driver, tenant_id: str) -> Dict[str, List[str]]:
    """Charge le mapping claim_id → [entity_ids] depuis Neo4j."""
    claim_entities: Dict[str, List[str]] = defaultdict(list)
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
            RETURN c.claim_id AS cid, e.entity_id AS eid
            """,
            tid=tenant_id,
        )
        for r in result:
            claim_entities[r["cid"]].append(r["eid"])
    logger.info(f"[FacetEngine] Loaded entity map: {len(claim_entities)} claims with entities")
    return dict(claim_entities)


def _build_entity_facet_affinity(
    driver,
    tenant_id: str,
    facet_ids: List[str],
    facet_vectors: Dict[str, np.ndarray],
    claim_embeddings: np.ndarray,
    claim_ids: List[str],
    claim_id_to_idx: Dict[str, int],
) -> Dict[str, Dict[str, float]]:
    """
    Construit un mapping entity_id → {facet_id: affinity_score}.

    Pour chaque entite, calcule l'affinite avec chaque facette
    en prenant le centroid des claims ABOUT cette entite et en le
    comparant aux prototypes facettes.

    Returns:
        Dict entity_id → Dict facet_id → affinity_score
    """
    from knowbase.facets.scorer import cosine_similarity

    entity_claims: Dict[str, List[int]] = defaultdict(list)
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
            RETURN e.entity_id AS eid, c.claim_id AS cid
            """,
            tid=tenant_id,
        )
        for r in result:
            idx = claim_id_to_idx.get(r["cid"])
            if idx is not None:
                entity_claims[r["eid"]].append(idx)

    affinity: Dict[str, Dict[str, float]] = {}
    for eid, indices in entity_claims.items():
        if len(indices) < 2:
            continue
        # Centroid des claims de cette entite
        centroid = claim_embeddings[indices].mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm

        # Score vs chaque facette
        entity_scores = {}
        for fid in facet_ids:
            entity_scores[fid] = cosine_similarity(centroid, facet_vectors[fid])
        affinity[eid] = entity_scores

    logger.info(
        f"[FacetEngine] Entity-facet affinity: {len(affinity)} entities with affinity scores"
    )
    return affinity


def _load_existing_facets(driver, tenant_id: str) -> List[Facet]:
    """Charge les facettes existantes depuis Neo4j."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (f:Facet {tenant_id: $tid})
            RETURN f.facet_id AS fid, f.facet_name AS name,
                   f.description AS desc, f.facet_family AS family,
                   f.lifecycle AS lifecycle, f.status AS status
            """,
            tid=tenant_id,
        )
        facets = []
        seen = set()
        for r in result:
            fid = r["fid"]
            if fid in seen:
                continue
            seen.add(fid)

            # Construire une description si absente
            name = r["name"] or fid.replace("facet_", "").replace("_", " ").title()
            desc = r["desc"] or ""
            if not desc:
                desc = f"Documents and information related to {name.lower()}."

            facets.append(Facet(
                facet_id=fid,
                canonical_label=name,
                description=desc,
                facet_family=r["family"] or "cross_cutting_concern",
                status=r["status"] or r["lifecycle"] or "candidate",
            ))

    logger.info(f"[FacetEngine] Loaded {len(facets)} existing facets from Neo4j")
    return facets


def _load_claim_embeddings(driver, tenant_id: str) -> tuple:
    """Charge tous les embeddings de claims depuis Neo4j.

    Returns:
        (claim_embeddings: np.ndarray, claim_ids: List[str], claim_doc_ids: List[str])
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WHERE c.embedding IS NOT NULL
            RETURN c.claim_id AS cid, c.embedding AS emb, c.doc_id AS did
            ORDER BY c.claim_id
            """,
            tid=tenant_id,
        )
        claim_ids = []
        claim_doc_ids = []
        embeddings = []
        for r in result:
            claim_ids.append(r["cid"])
            claim_doc_ids.append(r["did"] or "")
            embeddings.append(r["emb"])

    if not embeddings:
        return np.array([]), [], []

    claim_embeddings = np.array(embeddings, dtype=np.float32)
    logger.info(
        f"[FacetEngine] Loaded {len(claim_ids)} claim embeddings "
        f"({claim_embeddings.shape})"
    )
    return claim_embeddings, claim_ids, claim_doc_ids


def _normalize_facets(facets: List[Facet]) -> List[Facet]:
    """Pass F2 — Deduplique les facettes avec le meme label normalise."""
    seen = {}
    normalized = []
    for f in facets:
        key = f.canonical_label.lower().strip()
        if key in seen:
            # Garder la facette validated plutot que candidate
            existing = seen[key]
            if f.status == "validated" and existing.status != "validated":
                seen[key] = f
                normalized = [x for x in normalized if x.facet_id != existing.facet_id]
                normalized.append(f)
            logger.debug(
                f"[FacetEngine:Normalize] Dedup: '{f.canonical_label}' "
                f"({f.facet_id}) merged with {existing.facet_id}"
            )
        else:
            seen[key] = f
            normalized.append(f)

    if len(normalized) < len(facets):
        logger.info(
            f"[FacetEngine:Normalize] {len(facets)} → {len(normalized)} facets "
            f"(removed {len(facets) - len(normalized)} duplicates)"
        )

    return normalized


def _compute_governance(
    facets: List[Facet],
    assignments: List[FacetAssignment],
    claim_doc_ids: List[str],
    claim_id_to_idx: Dict[str, int],
) -> None:
    """Pass F5 — Calcule les metriques de sante pour chaque facette."""
    # Grouper les assignments par facette
    facet_assignments: Dict[str, List[FacetAssignment]] = defaultdict(list)
    for a in assignments:
        facet_assignments[a.facet_id].append(a)

    for facet in facets:
        fa = facet_assignments.get(facet.facet_id, [])
        if not fa:
            facet.health = FacetHealth(facet_id=facet.facet_id)
            continue

        # Docs des claims assignees
        docs = Counter()
        for a in fa:
            idx = claim_id_to_idx.get(a.claim_id)
            if idx is not None:
                docs[claim_doc_ids[idx]] += 1

        strong_count = sum(1 for a in fa if a.promotion_level == "STRONG")
        weak_count = sum(1 for a in fa if a.promotion_level == "WEAK")
        total = len(fa)

        # Concentration max sur un doc
        top_doc_pct = max(docs.values()) / total if docs and total > 0 else 0

        facet.health = FacetHealth(
            facet_id=facet.facet_id,
            info_count=total,
            doc_count=len(docs),
            weak_ratio=weak_count / total if total > 0 else 0,
            strong_ratio=strong_count / total if total > 0 else 0,
            top_doc_concentration=top_doc_pct,
            cross_doc_stability=len(docs) / max(1, len(set(claim_doc_ids))) if docs else 0,
        )

        # Promotion automatique si multi-doc et suffisamment de claims
        if facet.status == "candidate" and len(docs) >= 3 and total >= 10:
            facet.status = "validated"
            logger.info(
                f"[FacetEngine:Governance] Promoted '{facet.canonical_label}' → validated "
                f"({total} claims, {len(docs)} docs)"
            )


def _persist_to_neo4j(
    driver,
    tenant_id: str,
    facets: List[Facet],
    assignments: List[FacetAssignment],
) -> Dict[str, int]:
    """Persiste les facettes et assignments dans Neo4j."""
    stats = {"facets_updated": 0, "links_created": 0, "links_strong": 0, "links_weak": 0}

    with driver.session() as session:
        # 1. Supprimer les anciens liens BELONGS_TO_FACET
        session.run(
            "MATCH ()-[r:BELONGS_TO_FACET]->(:Facet {tenant_id: $tid}) DELETE r",
            tid=tenant_id,
        )

        # 2. Mettre a jour les facettes
        for facet in facets:
            props = facet.to_neo4j_properties()
            props["tenant_id"] = tenant_id
            session.run(
                """
                MERGE (f:Facet {facet_id: $fid, tenant_id: $tid})
                SET f += $props
                """,
                fid=facet.facet_id,
                tid=tenant_id,
                props=props,
            )
            stats["facets_updated"] += 1

        # 3. Creer les liens BELONGS_TO_FACET par batch
        batch_size = 1000
        for i in range(0, len(assignments), batch_size):
            batch = assignments[i:i + batch_size]
            batch_data = [
                {
                    "claim_id": a.claim_id,
                    "facet_id": a.facet_id,
                    "confidence": a.global_score,
                    "promotion_level": a.promotion_level,
                    "score_semantic": a.score_semantic,
                    "assignment_method": a.assignment_method,
                }
                for a in batch
            ]
            session.run(
                """
                UNWIND $batch AS item
                MATCH (c:Claim {claim_id: item.claim_id})
                MATCH (f:Facet {facet_id: item.facet_id, tenant_id: $tid})
                MERGE (c)-[r:BELONGS_TO_FACET]->(f)
                SET r.confidence = item.confidence,
                    r.promotion_level = item.promotion_level,
                    r.score_semantic = item.score_semantic,
                    r.assignment_method = item.assignment_method,
                    r.assigned_at = datetime()
                """,
                batch=batch_data,
                tid=tenant_id,
            )
            stats["links_created"] += len(batch)

        stats["links_strong"] = sum(1 for a in assignments if a.promotion_level == "STRONG")
        stats["links_weak"] = sum(1 for a in assignments if a.promotion_level == "WEAK")

    return stats


def run_facet_engine_v2(
    driver,
    tenant_id: str = "default",
    top_k_prototypes: int = 20,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Execute le FacetEngine V2 complet.

    Args:
        driver: Neo4j driver
        tenant_id: Tenant ID
        top_k_prototypes: Nombre de claims prototypes par facette
        dry_run: Si True, ne persiste pas

    Returns:
        Statistiques d'execution
    """
    start = time.time()

    # === Pass F1 : Bootstrap — charger les facettes existantes ===
    logger.info("[FacetEngine] Pass F1: Loading existing facets...")
    facets = bootstrap_from_existing_facets(driver, tenant_id)

    if not facets:
        logger.warning("[FacetEngine] No facets found. Run rebuild_facets.py first.")
        return {"error": "No facets found"}

    # === Pass F2 : Normalization ===
    logger.info("[FacetEngine] Pass F2: Normalizing facets...")
    from knowbase.common.clients.embeddings import get_embedding_manager
    manager = get_embedding_manager()

    def encode_fn(texts):
        return manager.encode(texts)

    facets = normalize_facets(facets, encode_fn=encode_fn)

    # === Charger les embeddings de claims ===
    logger.info("[FacetEngine] Loading claim embeddings...")
    claim_embeddings, claim_ids, claim_doc_ids = _load_claim_embeddings(driver, tenant_id)

    if len(claim_ids) == 0:
        logger.warning("[FacetEngine] No claim embeddings found.")
        return {"error": "No claim embeddings"}

    claim_id_to_idx = {cid: i for i, cid in enumerate(claim_ids)}

    # === Pass F3 : Prototype Build ===
    logger.info("[FacetEngine] Pass F3: Building prototypes...")

    prototypes = build_all_prototypes(
        facets=facets,
        all_claim_embeddings=claim_embeddings,
        all_claim_ids=claim_ids,
        encode_fn=encode_fn,
        top_k=top_k_prototypes,
    )

    # === Pass F4 : Assignment (multi-signal) ===
    logger.info("[FacetEngine] Pass F4: Scoring and assigning claims...")

    # Construire le dict des prototypes
    facet_vectors = {
        fid: np.array(proto.vector)
        for fid, proto in prototypes.items()
    }
    facet_ids = list(facet_vectors.keys())

    # --- Signal supplementaire : entity-facet affinity ---
    # Si une claim est ABOUT une entite qui est massivement dans une facette,
    # c'est un signal structurel fort.
    logger.info("[FacetEngine] Building entity-facet affinity map...")
    entity_facet_affinity = _build_entity_facet_affinity(
        driver, tenant_id, facet_ids, facet_vectors,
        claim_embeddings, claim_ids, claim_id_to_idx,
    )

    assignments = batch_score_claims(
        claim_embeddings=claim_embeddings,
        claim_ids=claim_ids,
        facet_prototypes=facet_vectors,
        facet_ids=facet_ids,
        entity_facet_affinity=entity_facet_affinity,
        claim_entity_map=_load_claim_entity_map(driver, tenant_id),
        claim_doc_ids=claim_doc_ids,
    )

    # === Pass F5 : Governance ===
    logger.info("[FacetEngine] Pass F5: Computing governance metrics...")
    compute_health(
        facets=facets,
        assignments=assignments,
        claim_doc_ids=claim_doc_ids,
        claim_id_to_idx=claim_id_to_idx,
        facet_prototypes=facet_vectors,
    )

    # Log resume
    for facet in facets:
        h = facet.health
        if h and h.info_count > 0:
            logger.info(
                f"  {facet.canonical_label}: {h.info_count} claims "
                f"({h.strong_ratio:.0%} STRONG, {h.weak_ratio:.0%} WEAK), "
                f"{h.doc_count} docs, status={facet.status}"
            )

    # === Persistance ===
    if dry_run:
        logger.info(f"[FacetEngine] DRY RUN — {len(assignments)} assignments computed")
        stats = {
            "facets": len(facets),
            "assignments": len(assignments),
            "strong": sum(1 for a in assignments if a.promotion_level == "STRONG"),
            "weak": sum(1 for a in assignments if a.promotion_level == "WEAK"),
            "dry_run": True,
        }
    else:
        logger.info("[FacetEngine] Persisting to Neo4j...")
        stats = _persist_to_neo4j(driver, tenant_id, facets, assignments)
        stats["facets"] = len(facets)

    elapsed = time.time() - start
    stats["duration_s"] = round(elapsed, 1)

    logger.info(
        f"[FacetEngine] Done in {elapsed:.1f}s: "
        f"{stats.get('facets', 0)} facets, "
        f"{stats.get('links_created', stats.get('assignments', 0))} links "
        f"({stats.get('links_strong', stats.get('strong', 0))} STRONG, "
        f"{stats.get('links_weak', stats.get('weak', 0))} WEAK)"
    )

    return stats


def run_facet_engine_v2_emergent(
    driver,
    tenant_id: str = "default",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    FacetEngine V2 avec clustering emergent.

    Au lieu de matcher les claims a des facettes pre-definies,
    fait emerger les facettes depuis les clusters de claims.
    """
    from knowbase.facets.clustering import run_emergent_clustering
    from knowbase.facets.models import FacetAssignment

    start = time.time()

    # === Charger les donnees ===
    logger.info("[FacetEngine:Emergent] Loading claim data...")
    claim_embeddings, claim_ids, claim_doc_ids = _load_claim_embeddings(driver, tenant_id)

    if len(claim_ids) == 0:
        return {"error": "No claim embeddings"}

    claim_texts = []
    with driver.session() as session:
        result = session.run(
            "MATCH (c:Claim {tenant_id: $tid}) "
            "RETURN c.claim_id AS cid, c.text AS text ORDER BY c.claim_id",
            tid=tenant_id,
        )
        text_map = {r["cid"]: r["text"] or "" for r in result}
    claim_texts = [text_map.get(cid, "") for cid in claim_ids]

    claim_entity_map = _load_claim_entity_map(driver, tenant_id)

    entity_names = {}
    with driver.session() as session:
        result = session.run(
            "MATCH (e:Entity {tenant_id: $tid}) RETURN e.entity_id AS eid, e.name AS name",
            tid=tenant_id,
        )
        entity_names = {r["eid"]: r["name"] for r in result}

    # === LLM function ===
    def llm_fn(system_prompt: str, user_prompt: str) -> str:
        from knowbase.common.llm_router import get_llm_router, TaskType
        router = get_llm_router()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return router.complete(
            task_type=TaskType.METADATA_EXTRACTION,
            messages=messages,
            temperature=0.2,
            max_tokens=500,
        )

    # === Clustering emergent ===
    logger.info("[FacetEngine:Emergent] Running emergent clustering...")
    emergent_facets = run_emergent_clustering(
        claim_embeddings=claim_embeddings,
        claim_ids=claim_ids,
        claim_texts=claim_texts,
        claim_doc_ids=claim_doc_ids,
        claim_entity_map=claim_entity_map,
        entity_names=entity_names,
        llm_fn=llm_fn,
    )

    if not emergent_facets:
        return {"error": "No clusters found", "duration_s": time.time() - start}

    # === Consolidation : micro-facettes → macro-facettes ===
    from knowbase.facets.consolidator import consolidate_facets

    logger.info("[FacetEngine:Emergent] Consolidating micro-facets into macro-facets...")
    macro_facets, micro_to_macro = consolidate_facets(
        micro_facets=emergent_facets,
        llm_fn=llm_fn,
        claim_texts=claim_texts,
        claim_ids=claim_ids,
    )

    # === Construire les Facet objects depuis les macro-facettes ===
    facets = []
    for mf in macro_facets:
        facets.append(Facet(
            facet_id=mf.facet_id,
            canonical_label=mf.canonical_label,
            description=mf.description,
            facet_family=mf.facet_family,
            status="validated" if mf.total_claims >= 20 and mf.total_docs >= 2 else "candidate",
        ))

    # === Assignment via macro-facettes ===
    logger.info("[FacetEngine:Emergent] Assigning claims to macro-facets...")
    claim_id_to_idx = {cid: i for i, cid in enumerate(claim_ids)}
    assignments: List[FacetAssignment] = []

    # Construire le mapping claim → macro-facette via les micro-clusters
    for ef in emergent_facets:
        # Trouver la macro-facette de cette micro
        macro_id = micro_to_macro.get(ef.facet_id, ef.facet_id)
        for idx in ef.prototype_claim_indices:
            if idx < len(claim_ids):
                assignments.append(FacetAssignment(
                    claim_id=claim_ids[idx],
                    facet_id=macro_id,
                    global_score=0.90,
                    score_semantic=0.90,
                    promotion_level="STRONG",
                    assignment_method="cluster_member",
                ))

    # Non-membres : nearest macro-centroid
    assigned = {a.claim_id for a in assignments}
    from knowbase.facets.scorer import cosine_similarity
    macro_centroids = {mf.facet_id: mf.centroid for mf in macro_facets if mf.centroid is not None}

    for i, cid in enumerate(claim_ids):
        if cid in assigned:
            continue
        best_sim, best_fid = 0, None
        for fid, centroid in macro_centroids.items():
            sim = cosine_similarity(claim_embeddings[i], centroid)
            if sim > best_sim:
                best_sim, best_fid = sim, fid
        if best_fid and best_sim >= 0.85:
            assignments.append(FacetAssignment(
                claim_id=cid, facet_id=best_fid,
                global_score=best_sim, score_semantic=best_sim,
                promotion_level="STRONG" if best_sim >= 0.88 else "WEAK",
                assignment_method="nearest_macro_centroid",
            ))

    # === Governance ===
    compute_health(facets, assignments, claim_doc_ids, claim_id_to_idx)

    for f in facets:
        h = f.health
        if h and h.info_count > 0:
            logger.info(
                f"  {f.canonical_label}: {h.info_count} claims "
                f"({h.strong_ratio:.0%} STRONG), {h.doc_count} docs"
            )

    stats = {
        "facets": len(facets),
        "assignments": len(assignments),
        "strong": sum(1 for a in assignments if a.promotion_level == "STRONG"),
        "weak": sum(1 for a in assignments if a.promotion_level == "WEAK"),
    }

    if not dry_run:
        logger.info("[FacetEngine:Emergent] Persisting...")
        persist_stats = _persist_to_neo4j(driver, tenant_id, facets, assignments)
        stats.update(persist_stats)

    stats["duration_s"] = round(time.time() - start, 1)
    logger.info(f"[FacetEngine:Emergent] Done in {stats['duration_s']}s: {stats['facets']} facets, {stats['assignments']} links")
    return stats
