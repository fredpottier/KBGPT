# src/knowbase/api/routers/post_import.py
"""
API Post-Import — Pipeline d'enrichissement qualité du KG.

Opérations post-import exécutables manuellement après un batch d'import.
L'admin sélectionne les étapes et les lance dans l'ordre optimal.
Exécution asynchrone via RQ (ne bloque pas la requête HTTP).

Ordre d'exécution :
1. Canonicalisation entités
2. Facettes (extraction LLM + matching)
3. Clustering cross-doc
4. Chaînes cross-doc
5. Domain Pack reprocess
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from knowbase.api.dependencies import get_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/post-import",
    tags=["Post-Import"],
)


# ============================================================================
# Schemas
# ============================================================================


class StepInfo(BaseModel):
    id: str
    name: str
    description: str
    order: int
    estimated_duration: str
    requires_llm: bool = False
    requires_pack: bool = False
    estimated_minutes: Optional[float] = None  # Estimation dynamique basée sur le volume


class PipelineRequest(BaseModel):
    steps: List[str] = Field(..., description="IDs des étapes à exécuter")
    tenant_id: str = "default"


class StepResult(BaseModel):
    step_id: str
    status: str  # success | error | skipped
    message: str
    duration_s: float = 0.0
    details: Dict = Field(default_factory=dict)


class PipelineStatusResponse(BaseModel):
    running: bool = False
    current_step: Optional[str] = None
    current_step_name: Optional[str] = None
    step_progress: float = 0.0  # 0-100, progression de l'étape en cours
    step_detail: str = ""  # ex: "142/500 paires évaluées"
    completed_steps: List[str] = Field(default_factory=list)
    total_steps: int = 0
    progress: float = 0.0
    results: List[StepResult] = Field(default_factory=list)
    job_id: Optional[str] = None


class PipelineStartResponse(BaseModel):
    success: bool
    job_id: str = ""
    message: str = ""
    steps_queued: List[str] = Field(default_factory=list)


# ============================================================================
# Définition des étapes
# ============================================================================


STEPS = [
    StepInfo(
        id="canonicalize",
        name="Canonicalisation entités",
        description="Regroupe les variantes d'une meme entite sous une CanonicalEntity unique via LLM (ex: acronymes, noms courts, variantes orthographiques).",
        order=1,
        estimated_duration="1 - 5min",
        requires_llm=True,
    ),
    StepInfo(
        id="facets",
        name="Reconstruction facettes",
        description="Ré-extrait les facettes thématiques (1 appel LLM/doc), puis matche les claims aux facettes validées.",
        order=2,
        estimated_duration="10 - 25min",
        requires_llm=True,
    ),
    StepInfo(
        id="cluster_cross_doc",
        name="Clustering cross-document",
        description="Regroupe les claims similaires de documents différents en clusters (Jaccard sur tokens + filtres modalité/négation).",
        order=3,
        estimated_duration="30s - 2min",
    ),
    StepInfo(
        id="chains_cross_doc",
        name="Chaînes cross-document",
        description="Détecte les chaînes logiques S/P/O entre claims de documents différents via jointure sur entités partagées.",
        order=4,
        estimated_duration="30s - 2min",
    ),
    StepInfo(
        id="detect_contradictions",
        name="Détection de contradictions",
        description="Analyse les claims au sein des clusters cross-doc et des claims partageant les mêmes entités pour détecter CONTRADICTS, REFINES et QUALIFIES via arbitrage LLM.",
        order=5,
        estimated_duration="5 - 20min",
        requires_llm=True,
    ),
    StepInfo(
        id="domain_pack_reprocess",
        name="Domain Pack reprocess",
        description="Soumet toutes les claims au NER specialise du Domain Pack actif pour detecter les entites domaine, et resout les aliases canoniques sur les entites existantes.",
        order=6,
        estimated_duration="30s - 2min",
        requires_pack=True,
    ),
    StepInfo(
        id="claim_embeddings",
        name="Indexation embeddings claims",
        description="Génère les embeddings vectoriels (e5-large 1024d) sur toutes les claims et crée le vector index Neo4j pour la recherche sémantique cross-langue.",
        order=7,
        estimated_duration="5 - 15min",
    ),
    StepInfo(
        id="claim_chunk_bridge",
        name="Pont Claim ↔ Chunk",
        description="Relie chaque claim à son chunk de preuve dans Qdrant via matching du verbatim_quote. Permet l'affichage de citations longues sourcées.",
        order=8,
        estimated_duration="1 - 3min",
    ),
    StepInfo(
        id="archive_isolated",
        name="Archivage claims isolées",
        description="Marque les claims sans structured_form et sans relations (ABOUT, CHAINS_TO, REFINES...) comme archivées. Elles restent dans le KG mais sont exclues des recherches.",
        order=9,
        estimated_duration="10 - 30s",
    ),
    StepInfo(
        id="garbage_collection",
        name="Garbage collection entités",
        description="Marque les entités selon leur qualité : VALID (>= 2 claims ou canonical), UNCERTAIN (1 claim orpheline), NOISY (0 claims). Pas de suppression, juste du marquage pour filtrage.",
        order=10,
        estimated_duration="5 - 15s",
    ),
    StepInfo(
        id="c4_relations",
        name="C4 Relations Evidence-First",
        description="Détecte CONTRADICTS/QUALIFIES/REFINES entre claims cross-doc via embedding similarity + adjudication LLM (Claude Haiku). Chaque relation a des preuves verbatim.",
        order=11,
        estimated_duration="5 - 30min",
        requires_llm=True,
    ),
    StepInfo(
        id="c6_pivots",
        name="C6 Cross-doc Pivots",
        description="Détecte COMPLEMENTS/EVOLVES_TO/SPECIALIZES entre claims cross-doc partageant une entité pivot. Exploite les entités canoniques comme liens inter-documents.",
        order=12,
        estimated_duration="5 - 30min",
        requires_llm=True,
    ),
    StepInfo(
        id="build_perspectives",
        name="Construction Perspectives V2",
        description="Reconstruit les Perspectives thématiques (HDBSCAN sur embeddings claims, labellisation LLM, linking sujets). Skippé si moins de 50 nouveaux claims depuis le dernier build.",
        order=13,
        estimated_duration="3 - 10min",
        requires_llm=True,
    ),
]

STEPS_BY_ID = {s.id: s for s in STEPS}


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/steps", response_model=List[StepInfo])
async def list_steps():
    """Liste les étapes avec estimation dynamique basée sur le volume Neo4j."""
    steps = sorted(STEPS, key=lambda s: s.order)

    # Charger le volume actuel + benchmarks historiques
    try:
        volume = _get_kg_volume()
        benchmarks = _get_step_benchmarks()

        for step in steps:
            bench = benchmarks.get(step.id)
            if bench and bench.get("duration_s") and bench.get("volume"):
                # Règle de trois : durée proportionnelle au volume
                ratio = volume / bench["volume"] if bench["volume"] > 0 else 1.0
                estimated_s = bench["duration_s"] * ratio
                step.estimated_minutes = round(estimated_s / 60, 1)
                step.estimated_duration = _format_duration(estimated_s)
    except Exception:
        pass  # Garder les estimations statiques

    return steps


@router.get("/status", response_model=PipelineStatusResponse)
async def pipeline_status(
    tenant_id: str = Depends(get_tenant_id),
):
    """État du pipeline en cours d'exécution."""
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        raw = rc.client.get(f"osmose:post_import:state:{tenant_id}")
        if raw:
            data = json.loads(raw)
            return PipelineStatusResponse(**data)
    except Exception as e:
        logger.debug(f"Error reading post-import status: {e}")

    return PipelineStatusResponse()


@router.post("/run", response_model=PipelineStartResponse)
async def run_pipeline(
    request: PipelineRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Lance le pipeline en arrière-plan via RQ."""
    tenant_id = request.tenant_id or tenant_id

    for step_id in request.steps:
        if step_id not in STEPS_BY_ID:
            raise HTTPException(status_code=400, detail=f"Étape inconnue : '{step_id}'")

    ordered_steps = sorted(request.steps, key=lambda s: STEPS_BY_ID[s].order)

    # Enqueue dans RQ
    try:
        from redis import Redis
        from rq import Queue

        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        redis_conn = Redis.from_url(redis_url)
        queue = Queue("reprocess", connection=redis_conn)

        job = queue.enqueue(
            run_pipeline_job,
            ordered_steps,
            tenant_id,
            job_timeout="45m",
        )

        return PipelineStartResponse(
            success=True,
            job_id=job.id,
            message=f"{len(ordered_steps)} étapes lancées en arrière-plan",
            steps_queued=ordered_steps,
        )
    except Exception as e:
        logger.error(f"[PostImport] Error enqueueing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel")
async def cancel_pipeline(
    tenant_id: str = Depends(get_tenant_id),
):
    """Annule le pipeline en cours (marque comme terminé dans Redis)."""
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        rc.client.delete(f"osmose:post_import:state:{tenant_id}")
        return {"success": True, "message": "Pipeline annulé"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ============================================================================
# Job RQ (exécuté par le worker)
# ============================================================================


def run_pipeline_job(steps: List[str], tenant_id: str) -> dict:
    """Job RQ — exécute les étapes séquentiellement."""
    results: List[dict] = []
    pipeline_start = time.time()

    _update_state(tenant_id, running=True, all_steps=steps, completed=[])

    for step_id in steps:
        step_info = STEPS_BY_ID.get(step_id)
        step_name = step_info.name if step_info else step_id
        logger.info(f"[PostImport] Exécution : {step_name}")

        completed_so_far = [r["step_id"] for r in results if r["status"] == "success"]

        # Callback de progression pour l'étape en cours
        def on_step_progress(pct: float, detail: str = ""):
            _update_state(
                tenant_id, running=True, all_steps=steps,
                completed=completed_so_far,
                current_step=step_id,
                current_step_name=step_name,
                results=results,
                step_progress=pct,
                step_detail=detail,
            )

        _update_state(
            tenant_id, running=True, all_steps=steps,
            completed=completed_so_far,
            current_step=step_id,
            current_step_name=step_name,
            results=results,
            step_progress=0.0,
        )

        step_start = time.time()
        try:
            details = _execute_step(step_id, tenant_id, on_step_progress)
            duration = round(time.time() - step_start, 1)
            results.append({
                "step_id": step_id,
                "status": "success",
                "message": f"{step_name} terminé",
                "duration_s": duration,
                "details": details or {},
            })
            logger.info(f"[PostImport] {step_name} terminé en {duration}s")

            # Sauvegarder le benchmark pour estimation future
            try:
                volume = _get_kg_volume()
                _save_step_benchmark(step_id, duration, volume)
            except Exception:
                pass

        except Exception as e:
            duration = round(time.time() - step_start, 1)
            logger.error(f"[PostImport] Erreur {step_id}: {e}")
            results.append({
                "step_id": step_id,
                "status": "error",
                "message": str(e)[:200],
                "duration_s": duration,
                "details": {},
            })

    total_duration = round(time.time() - pipeline_start, 1)

    # Invalider les caches corpus-dependants (IDF + stopwords multilingues)
    # car l'ingestion peut avoir modifie la distribution du corpus ou ajoute
    # des documents dans une nouvelle langue
    try:
        from knowbase.common.corpus_stats import invalidate_cache as invalidate_corpus_stats
        invalidate_corpus_stats()
        logger.info("[PostImport] Caches corpus_stats + stopwords invalides")
    except Exception:
        pass

    _update_state(
        tenant_id, running=False, all_steps=steps,
        completed=[r["step_id"] for r in results if r["status"] == "success"],
        results=results,
    )

    return {
        "steps": results,
        "total_duration_s": total_duration,
        "success_count": sum(1 for r in results if r["status"] == "success"),
        "error_count": sum(1 for r in results if r["status"] == "error"),
    }


# ============================================================================
# Exécution des étapes
# ============================================================================


def _execute_step(step_id: str, tenant_id: str, on_progress=None) -> dict:
    noop = lambda pct, detail="": None
    progress = on_progress or noop
    if step_id == "canonicalize":
        return _run_canonicalize(tenant_id, progress)
    elif step_id == "facets":
        return _run_facets(tenant_id, progress)
    elif step_id == "cluster_cross_doc":
        return _run_cluster_cross_doc(tenant_id, progress)
    elif step_id == "chains_cross_doc":
        return _run_chains_cross_doc(tenant_id, progress)
    elif step_id == "detect_contradictions":
        return _run_detect_contradictions(tenant_id, progress)
    elif step_id == "domain_pack_reprocess":
        return _run_domain_pack_reprocess(tenant_id, progress)
    elif step_id == "claim_embeddings":
        return _run_claim_embeddings(tenant_id, progress)
    elif step_id == "claim_chunk_bridge":
        return _run_claim_chunk_bridge(tenant_id, progress)
    elif step_id == "archive_isolated":
        return _run_archive_isolated(tenant_id)
    elif step_id == "garbage_collection":
        return _run_garbage_collection(tenant_id)
    elif step_id == "c4_relations":
        return _run_c4_relations(tenant_id, progress)
    elif step_id == "c6_pivots":
        return _run_c6_pivots(tenant_id, progress)
    elif step_id == "build_perspectives":
        return _run_build_perspectives(tenant_id, progress)
    else:
        raise ValueError(f"Étape inconnue: {step_id}")


def _run_canonicalize(tenant_id: str, progress=None) -> dict:
    _p = progress or (lambda pct, detail="": None)
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    _p(5, "Comptage des entites canoniques existantes...")
    with driver.session() as session:
        before = session.run(
            "MATCH (ce:CanonicalEntity) RETURN count(ce) as cnt"
        ).single()["cnt"]
        total_entities = session.run(
            "MATCH (e:Entity {tenant_id: $tid}) RETURN count(e) as cnt",
            tid=tenant_id,
        ).single()["cnt"]

    _p(10, f"Canonicalisation de {total_entities} entites...")
    from knowbase.claimfirst.worker_job import _canonicalize_entities_cross_doc
    result = _canonicalize_entities_cross_doc(driver, tenant_id)

    _p(95, "Comptage final...")
    with driver.session() as session:
        after = session.run(
            "MATCH (ce:CanonicalEntity) RETURN count(ce) as cnt"
        ).single()["cnt"]

    _p(100, f"{after - before} nouveaux canoniques crees")
    return {
        "canonical_before": before,
        "canonical_after": after,
        "new_canonicals": after - before,
        **result,
    }


def _run_facets(tenant_id: str, progress=None) -> dict:
    import subprocess
    result = subprocess.run(
        ["python", "scripts/rebuild_facets.py", "--execute", "--purge-old",
         "--tenant-id", tenant_id],
        capture_output=True, text=True, timeout=1800,
        cwd="/app",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"rebuild_facets failed: {result.stderr[-300:] if result.stderr else result.stdout[-300:]}"
        )

    lines = result.stdout.split("\n")
    stats = {}
    for line in lines:
        if "Facettes persistees:" in line:
            stats["facets_persisted"] = int(line.split(":")[-1].strip())
        elif "Total facettes:" in line:
            stats["total_facets"] = int(line.split(":")[-1].strip())
        elif "claim→facet" in line.lower() or "claim→facette" in line.lower():
            # Parse "Liens claim→facette: 1234"
            try:
                stats["facet_links"] = int(line.split(":")[-1].strip())
            except ValueError:
                pass

    return stats


def _run_cluster_cross_doc(tenant_id: str, progress=None) -> dict:
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    from knowbase.claimfirst.worker_job import _cluster_cross_doc
    return _cluster_cross_doc(driver, tenant_id)


def _run_chains_cross_doc(tenant_id: str, progress=None) -> dict:
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    with driver.session() as session:
        # Charger claims avec structured_form
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WHERE c.structured_form_json IS NOT NULL
            RETURN c.claim_id AS cid, c.doc_id AS did,
                   c.structured_form_json AS sf
            """,
            tid=tenant_id,
        )
        claims = []
        for r in result:
            try:
                sf = json.loads(r["sf"]) if isinstance(r["sf"], str) else r["sf"]
                claims.append({
                    "claim_id": r["cid"],
                    "doc_id": r["did"],
                    "structured_form": sf,
                })
            except Exception:
                continue

        doc_ids = list({c["doc_id"] for c in claims})
        if len(doc_ids) < 2:
            return {"chains_detected": 0, "message": "Moins de 2 documents"}

        # Entity index
        eidx_result = session.run(
            "MATCH (e:Entity {tenant_id: $tid}) "
            "RETURN e.normalized_name AS norm, e.entity_id AS eid",
            tid=tenant_id,
        )
        entity_index = {r["norm"]: r["eid"] for r in eidx_result}

        # Hub entities
        hub_result = session.run(
            "MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim) "
            "WITH e, count(c) AS cc WHERE cc > 200 "
            "RETURN e.normalized_name AS norm",
            tid=tenant_id,
        )
        hub_entities = {r["norm"] for r in hub_result}

    # Detect (hors session pour éviter timeout)
    from knowbase.claimfirst.composition.chain_detector import ChainDetector
    idf_map = ChainDetector.compute_idf(claims, entity_index=entity_index)
    detector = ChainDetector()
    links = detector.detect_cross_doc(
        claims, hub_entities=hub_entities,
        entity_index=entity_index, idf_map=idf_map,
    )

    # Persist
    persisted = 0
    with driver.session() as session:
        for link in links:
            r = session.run(
                """
                MATCH (c1:Claim {claim_id: $c1id, tenant_id: $tid})
                MATCH (c2:Claim {claim_id: $c2id, tenant_id: $tid})
                MERGE (c1)-[r:CHAINS_TO]->(c2)
                SET r.confidence = 1.0,
                    r.method = 'spo_join_cross_doc',
                    r.cross_doc = true,
                    r.source_doc_id = $sdid,
                    r.target_doc_id = $tdid,
                    r.join_key_name = $jkn
                RETURN r IS NOT NULL AS ok
                """,
                c1id=link.source_claim_id,
                c2id=link.target_claim_id,
                tid=tenant_id,
                sdid=link.source_doc_id or "",
                tdid=link.target_doc_id or "",
                jkn=link.join_key_name or "",
            )
            if r.single():
                persisted += 1

    return {"chains_detected": len(links), "chains_persisted": persisted}


def _run_detect_contradictions(tenant_id: str, progress=None) -> dict:
    """
    Détection de contradictions cross-doc en 2 phases :
    Phase A : Formelle (claims avec S/P/O structuré)
    Phase B : LLM directe (claims sans S/P/O, au sein des clusters cross-doc)
    """
    _p = progress or (lambda pct, detail="": None)
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.claimfirst.models.claim import Claim
    from knowbase.claimfirst.clustering.relation_detector import RelationDetector
    from knowbase.claimfirst.models.result import ClaimCluster
    from collections import defaultdict

    driver = get_neo4j_client().driver
    _p(5, "Chargement des clusters cross-document...")

    # Compter les relations existantes
    with driver.session() as session:
        existing = session.run(
            "MATCH ()-[r:CONTRADICTS|REFINES|QUALIFIES]->() "
            "RETURN type(r) as t, count(r) as c"
        )
        existing_counts = {r["t"]: r["c"] for r in existing}

    # Charger claims dans des clusters cross-doc
    with driver.session() as session:
        result = session.run(
            """
            MATCH (cc:ClaimCluster {tenant_id: $tid})<-[:IN_CLUSTER]-(c:Claim)
            WHERE cc.cross_doc = true
            RETURN cc.cluster_id as cluster_id,
                   c.claim_id as claim_id, c.text as text,
                   c.doc_id as doc_id, c.tenant_id as tenant_id,
                   c.structured_form_json as sf_json
            """,
            tid=tenant_id,
        )

        claims_by_id = {}
        cluster_claim_ids = defaultdict(list)

        for r in result:
            cid = r["claim_id"]
            cluster_claim_ids[r["cluster_id"]].append(cid)

            if cid not in claims_by_id:
                sf = None
                if r["sf_json"]:
                    try:
                        sf = json.loads(r["sf_json"]) if isinstance(r["sf_json"], str) else r["sf_json"]
                    except Exception:
                        pass

                claims_by_id[cid] = {
                    "claim_id": cid,
                    "text": r["text"] or "",
                    "doc_id": r["doc_id"] or "",
                    "sf": sf,
                }

    logger.info(
        f"[PostImport:Contradictions] {len(claims_by_id)} claims "
        f"dans {len(cluster_claim_ids)} clusters cross-doc"
    )

    _p(15, f"{len(claims_by_id)} claims dans {len(cluster_claim_ids)} clusters")

    if not claims_by_id:
        _p(100, "Aucun cluster cross-doc")
        return {"message": "Aucun cluster cross-doc trouvé", "pairs_analyzed": 0}

    # ========================================================================
    # Phase A : Formelle (détecteur existant, claims avec S/P/O)
    # ========================================================================
    # (gardée pour les claims avec structured_form — ~12% du corpus)
    formal_claims = []
    formal_clusters = []
    for cluster_id, cids in cluster_claim_ids.items():
        sf_cids = [cid for cid in cids if claims_by_id[cid]["sf"]]
        if len(sf_cids) >= 2:
            for cid in sf_cids:
                cd = claims_by_id[cid]
                formal_claims.append(Claim.model_construct(
                    claim_id=cid, text=cd["text"], doc_id=cd["doc_id"],
                    tenant_id=tenant_id, unit_ids=[], claim_type="FACTUAL",
                    verbatim_quote=cd["text"], passage_id="unknown",
                    structured_form=cd["sf"],
                ))
            formal_clusters.append(ClaimCluster.model_construct(
                cluster_id=cluster_id, tenant_id=tenant_id,
                claim_ids=sf_cids, canonical_label="",
            ))

    _p(20, f"Phase A: analyse formelle de {len(formal_claims)} claims...")
    formal_relations = []
    if formal_claims and formal_clusters:
        detector = RelationDetector(min_confidence=0.7)
        formal_relations = detector.detect(claims=formal_claims, clusters=formal_clusters)
        logger.info(
            f"[PostImport:Contradictions] Phase A (formelle): "
            f"{len(formal_relations)} relations (stats: {detector.stats})"
        )

    # ========================================================================
    # Phase B : LLM directe (claims sans S/P/O, texte brut)
    # Cap : max 10 paires cross-doc par cluster pour éviter l'explosion
    # combinatoire sur les gros clusters (167 claims → 14k paires)
    # ========================================================================
    import random
    MAX_PAIRS_PER_CLUSTER = 50

    cross_doc_pairs = []
    skipped_identical = 0
    for cluster_id, cids in cluster_claim_ids.items():
        cluster_pairs = []
        for i, cid1 in enumerate(cids):
            for cid2 in cids[i + 1:]:
                c1 = claims_by_id[cid1]
                c2 = claims_by_id[cid2]
                if c1["doc_id"] == c2["doc_id"]:
                    continue
                if c1["sf"] and c2["sf"]:
                    continue
                if len(c1["text"]) < 30 or len(c2["text"]) < 30:
                    continue
                # Gate : textes identiques ou quasi-identiques → pas une contradiction
                # mais une confirmation cross-doc (versions du meme doc, copie, etc.)
                t1 = c1["text"].lower().strip()
                t2 = c2["text"].lower().strip()
                if t1 == t2:
                    skipped_identical += 1
                    continue
                # Jaccard sur tokens — si > 0.9, trop similaires pour etre en contradiction
                words1 = set(t1.split())
                words2 = set(t2.split())
                if words1 and words2:
                    jaccard = len(words1 & words2) / len(words1 | words2)
                    if jaccard > 0.9:
                        skipped_identical += 1
                        continue
                cluster_pairs.append((c1, c2))

        # Échantillonner si trop de paires dans ce cluster
        if len(cluster_pairs) > MAX_PAIRS_PER_CLUSTER:
            cluster_pairs = random.sample(cluster_pairs, MAX_PAIRS_PER_CLUSTER)
        cross_doc_pairs.extend(cluster_pairs)

    logger.info(
        f"[PostImport:Contradictions] Phase B (LLM): "
        f"{len(cross_doc_pairs)} paires cross-doc à analyser "
        f"({skipped_identical} paires identiques/quasi-identiques filtrées)"
    )

    _p(35, f"Phase B: {len(cross_doc_pairs)} paires a analyser via LLM...")
    llm_relations = []
    if cross_doc_pairs:
        llm_relations = _llm_batch_compare(cross_doc_pairs, tenant_id, on_progress=_p)
        logger.info(
            f"[PostImport:Contradictions] Phase B: "
            f"{len(llm_relations)} relations trouvées"
        )

    # ========================================================================
    # Persistance
    # ========================================================================
    _p(90, f"Persistance de {len(formal_relations) + len(llm_relations)} relations...")
    all_relations = formal_relations + llm_relations

    CYPHER_BY_TYPE = {
        "CONTRADICTS": """
            MATCH (c1:Claim {claim_id: $c1id, tenant_id: $tid})
            MATCH (c2:Claim {claim_id: $c2id, tenant_id: $tid})
            MERGE (c1)-[r:CONTRADICTS]->(c2)
            SET r.confidence = $conf, r.method = 'post_import_cross_doc', r.basis = $basis
        """,
        "REFINES": """
            MATCH (c1:Claim {claim_id: $c1id, tenant_id: $tid})
            MATCH (c2:Claim {claim_id: $c2id, tenant_id: $tid})
            MERGE (c1)-[r:REFINES]->(c2)
            SET r.confidence = $conf, r.method = 'post_import_cross_doc', r.basis = $basis
        """,
        "QUALIFIES": """
            MATCH (c1:Claim {claim_id: $c1id, tenant_id: $tid})
            MATCH (c2:Claim {claim_id: $c2id, tenant_id: $tid})
            MERGE (c1)-[r:QUALIFIES]->(c2)
            SET r.confidence = $conf, r.method = 'post_import_cross_doc', r.basis = $basis
        """,
    }

    persisted = 0
    with driver.session() as session:
        for rel in all_relations:
            # Supporter les 2 formats (ClaimRelation objet ou dict)
            if isinstance(rel, dict):
                rel_type = rel["relation_type"]
                c1id = rel["source_claim_id"]
                c2id = rel["target_claim_id"]
                conf = rel.get("confidence", 0.7)
                basis = rel.get("basis", "")
            else:
                rel_type = rel.relation_type.value
                c1id = rel.source_claim_id
                c2id = rel.target_claim_id
                conf = rel.confidence
                basis = rel.basis or ""

            cypher = CYPHER_BY_TYPE.get(rel_type)
            if not cypher:
                continue
            try:
                session.run(
                    cypher,
                    c1id=c1id, c2id=c2id, tid=tenant_id,
                    conf=conf, basis=basis,
                )
                persisted += 1
            except Exception as e:
                logger.warning(f"[PostImport:Contradictions] Persist error: {e}")

    # Compter les nouvelles relations
    with driver.session() as session:
        after = session.run(
            "MATCH ()-[r:CONTRADICTS|REFINES|QUALIFIES]->() "
            "RETURN type(r) as t, count(r) as c"
        )
        after_counts = {r["t"]: r["c"] for r in after}

    return {
        "formal_pairs": len(formal_relations),
        "llm_pairs_analyzed": len(cross_doc_pairs),
        "llm_relations_found": len(llm_relations),
        "total_persisted": persisted,
        "new_contradicts": after_counts.get("CONTRADICTS", 0) - existing_counts.get("CONTRADICTS", 0),
        "new_refines": after_counts.get("REFINES", 0) - existing_counts.get("REFINES", 0),
        "new_qualifies": after_counts.get("QUALIFIES", 0) - existing_counts.get("QUALIFIES", 0),
        "total_contradicts": after_counts.get("CONTRADICTS", 0),
        "total_refines": after_counts.get("REFINES", 0),
        "total_qualifies": after_counts.get("QUALIFIES", 0),
    }


# ============================================================================
# LLM direct comparison (Phase B)
# ============================================================================

_LLM_COMPARE_SYSTEM = """You compare pairs of scientific claims from different documents.
For each pair, determine the relationship between Claim A and Claim B.

Answer with EXACTLY one label per pair:
- CONTRADICTS: The claims are mutually exclusive — both cannot be true in the same context.
- REFINES: Claim B adds precision or detail to Claim A (or vice versa).
- QUALIFIES: One claim adds a condition, exception, or nuance to the other.
- COMPATIBLE: The claims are consistent, complementary, or say the same thing differently.
- UNRELATED: The claims discuss different topics despite being in the same cluster.

IMPORTANT:
- Different numerical values for the same measurement IS a contradiction.
- Different study populations or conditions is NOT a contradiction (it's QUALIFIES or UNRELATED).
- One claim being more specific than the other is REFINES, not CONTRADICTS.
- When in doubt, choose COMPATIBLE. False contradictions are worse than missed ones.

Respond as JSON: {"results": [{"pair": 1, "label": "...", "reason": "brief explanation"}, ...]}"""


def _llm_batch_compare(
    pairs: list,
    tenant_id: str,
    batch_size: int = 10,
    max_workers: int = 5,
    on_progress=None,
) -> list:
    """Compare des paires de claims via LLM en batch, parallélisé."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _p = on_progress or (lambda pct, detail="": None)

    # Découper en batches
    batches = []
    for batch_start in range(0, len(pairs), batch_size):
        batches.append(pairs[batch_start:batch_start + batch_size])

    total_batches = len(batches)
    logger.info(
        f"[PostImport:Contradictions] {total_batches} batches LLM "
        f"({max_workers} workers parallèles)"
    )

    all_results = []
    completed_count = 0

    def process_batch(batch):
        return _call_llm_compare_batch(batch)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_batch, batch): i
            for i, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            try:
                batch_results = future.result()
                all_results.extend(batch_results)
            except Exception as e:
                logger.warning(f"[PostImport:Contradictions] Batch future error: {e}")
            completed_count += 1
            pct = 35 + (completed_count / total_batches) * 55  # 35% → 90%
            _p(pct, f"Phase B: {completed_count}/{total_batches} batches ({len(all_results)} relations)")

    return all_results


def _call_llm_compare_batch(batch: list) -> list:
    """Appelle le LLM pour un batch de paires."""
    from knowbase.common.llm_router import get_llm_router, TaskType

    router = get_llm_router()
    results = []

    pair_texts = []
    for i, (c1, c2) in enumerate(batch, 1):
        pair_texts.append(
            f"Pair {i}:\n"
            f"  Claim A [{c1['doc_id'][:30]}]: {c1['text'][:200]}\n"
            f"  Claim B [{c2['doc_id'][:30]}]: {c2['text'][:200]}"
        )

    user_prompt = "\n\n".join(pair_texts)

    try:
        response = router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=[
                {"role": "system", "content": _LLM_COMPARE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
            response_format={"type": "json_object"},
        ).strip()

        data = json.loads(response)

        for item in data.get("results", []):
            pair_idx = item.get("pair", 0) - 1
            label = item.get("label", "").upper()
            reason = item.get("reason", "")

            if pair_idx < 0 or pair_idx >= len(batch):
                continue
            if label not in ("CONTRADICTS", "REFINES", "QUALIFIES"):
                continue

            c1, c2 = batch[pair_idx]
            results.append({
                "source_claim_id": c1["claim_id"],
                "target_claim_id": c2["claim_id"],
                "relation_type": label,
                "confidence": 0.7,
                "basis": reason[:200],
            })

    except Exception as e:
        logger.warning(f"[PostImport:Contradictions] LLM call error: {e}")

    return results


def _run_claim_embeddings(tenant_id: str, progress=None) -> dict:
    """Génère les embeddings sur les claims via script."""
    _p = progress or (lambda pct, detail="": None)
    _p(5, "Generation des embeddings en cours...")
    import subprocess
    result = subprocess.run(
        ["python", "scripts/backfill_claim_embeddings.py",
         "--batch-size", "256", "--tenant-id", tenant_id],
        capture_output=True, text=True, timeout=1800,
        cwd="/app",
    )
    if result.returncode != 0:
        raise RuntimeError(f"backfill_claim_embeddings failed: {result.stderr[-300:]}")

    # Parser les stats depuis la sortie
    lines = result.stdout.split("\n")
    stats = {}
    for line in lines:
        if "Claims traitées:" in line:
            try:
                stats["claims_processed"] = int(line.split(":")[-1].strip())
            except ValueError:
                pass
        elif "Claims avec embedding:" in line:
            stats["claims_with_embedding"] = line.split(":")[-1].strip()
    return stats


def _run_claim_chunk_bridge(tenant_id: str, progress=None) -> dict:
    """Bridge claims↔chunks via script."""
    _p = progress or (lambda pct, detail="": None)
    _p(5, "Construction des liens claims-chunks...")
    import subprocess
    result = subprocess.run(
        ["python", "scripts/backfill_claim_chunk_bridge.py",
         "--tenant-id", tenant_id],
        capture_output=True, text=True, timeout=600,
        cwd="/app",
    )
    if result.returncode != 0:
        raise RuntimeError(f"backfill_claim_chunk_bridge failed: {result.stderr[-300:]}")

    lines = result.stdout.split("\n")
    stats = {}
    for line in lines:
        if "Matchées:" in line:
            stats["matched"] = line.split(":")[1].strip()
        elif "liens persistés" in line:
            try:
                stats["links_persisted"] = int(line.split(":")[0].strip().split()[-1])
            except (ValueError, IndexError):
                pass
    return stats


def _run_archive_isolated(tenant_id: str) -> dict:
    """Archive les claims isolées (sans SF, sans relations)."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    with driver.session() as session:
        # Compter total
        total = session.run(
            "MATCH (c:Claim {tenant_id: $tid}) RETURN count(c) as c",
            tid=tenant_id,
        ).single()["c"]

        # Identifier les isolées
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WHERE c.structured_form_json IS NULL
              AND (c.archived IS NULL OR c.archived = false)
              AND NOT EXISTS { (c)-[:CHAINS_TO]->() }
              AND NOT EXISTS { ()-[:CHAINS_TO]->(c) }
              AND NOT EXISTS { (c)-[:ABOUT]->() }
              AND NOT EXISTS { (c)-[:REFINES]->() }
              AND NOT EXISTS { ()-[:REFINES]->(c) }
              AND NOT EXISTS { (c)-[:QUALIFIES]->() }
              AND NOT EXISTS { ()-[:QUALIFIES]->(c) }
              AND NOT EXISTS { (c)-[:CONTRADICTS]->() }
              AND NOT EXISTS { ()-[:CONTRADICTS]->(c) }
            RETURN c.claim_id AS claim_id
            """,
            tid=tenant_id,
        )
        isolated_ids = [r["claim_id"] for r in result]

        if not isolated_ids:
            return {"total_claims": total, "newly_archived": 0, "message": "Aucune claim isolée"}

        # Archiver par batch
        archived = 0
        for i in range(0, len(isolated_ids), 500):
            batch = isolated_ids[i:i + 500]
            r = session.run(
                """
                UNWIND $ids AS cid
                MATCH (c:Claim {claim_id: cid, tenant_id: $tid})
                SET c.archived = true,
                    c.archived_at = datetime(),
                    c.archived_reason = 'isolated_claim_post_import'
                RETURN count(c) AS archived
                """,
                ids=batch, tid=tenant_id,
            )
            archived += r.single()["archived"]

        total_archived = session.run(
            "MATCH (c:Claim {tenant_id: $tid, archived: true}) RETURN count(c) as c",
            tid=tenant_id,
        ).single()["c"]

    return {
        "total_claims": total,
        "newly_archived": archived,
        "total_archived": total_archived,
        "isolated_percentage": round(100 * len(isolated_ids) / total, 1) if total else 0,
    }


def _run_garbage_collection(tenant_id: str) -> dict:
    """C3 Garbage collection — marque les entites VALID/UNCERTAIN/NOISY."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    with driver.session() as session:
        # Marquer NOISY : 0 claims, pas de canonical
        noisy = session.run("""
            MATCH (e:Entity {tenant_id: $tid})
            WHERE NOT (e)<-[:ABOUT]-(:Claim) AND NOT (e)-[:SAME_CANON_AS]->(:CanonicalEntity)
            SET e.quality_status = 'NOISY', e.status_updated_at = datetime()
            RETURN count(e) AS cnt
        """, tid=tenant_id).single()["cnt"]

        # Marquer UNCERTAIN : 1 claim, pas de canonical
        uncertain = session.run("""
            MATCH (e:Entity {tenant_id: $tid})
            WHERE NOT (e)-[:SAME_CANON_AS]->(:CanonicalEntity)
              AND e.quality_status IS NULL
            WITH e
            MATCH (e)<-[:ABOUT]-(c:Claim)
            WITH e, count(c) AS claims
            WHERE claims = 1
            SET e.quality_status = 'UNCERTAIN', e.status_updated_at = datetime()
            RETURN count(e) AS cnt
        """, tid=tenant_id).single()["cnt"]

        # Marquer VALID : tout le reste non marque
        valid = session.run("""
            MATCH (e:Entity {tenant_id: $tid})
            WHERE e.quality_status IS NULL
            SET e.quality_status = 'VALID', e.status_updated_at = datetime()
            RETURN count(e) AS cnt
        """, tid=tenant_id).single()["cnt"]

    return {
        "noisy": noisy,
        "uncertain": uncertain,
        "valid": valid,
        "total": noisy + uncertain + valid,
    }


def _run_c4_relations(tenant_id: str, progress=None) -> dict:
    """C4 Relations Evidence-First : mining + adjudication + persistance."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.relations.candidate_miner_c4 import CandidateMinerC4
    from knowbase.relations.nli_adjudicator import NLIAdjudicator
    from knowbase.relations.relation_persister_c4 import RelationPersisterC4

    _p = progress or (lambda pct, detail="": None)

    driver = get_neo4j_client().driver

    # Stage 1 : Mining
    _p(5, "Stage 1 : Mining paires candidates...")
    miner = CandidateMinerC4(driver, tenant_id=tenant_id)
    pre_stats = miner.get_mining_stats()

    pairs = miner.mine_candidates(
        cosine_threshold=0.85,
        max_neighbors=5,
        max_total_pairs=5000,
        exclude_existing=True,
    )

    if not pairs:
        _p(100, "Aucune paire candidate")
        return {"message": "Aucune paire candidate trouvee", "pairs": 0}

    _p(30, f"Stage 2 : Adjudication de {len(pairs)} paires...")

    # Stage 2 : Adjudication NLI
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _p(100, "ANTHROPIC_API_KEY manquante")
        return {"error": "ANTHROPIC_API_KEY non definie"}

    adjudicator = NLIAdjudicator(max_workers=3)

    def on_adj(done, total):
        pct = 30 + int(50 * done / total)
        _p(pct, f"Adjudication: {done}/{total}")

    results = adjudicator.adjudicate_batch(pairs, on_progress=on_adj)

    if not results:
        _p(100, "Aucune relation detectee")
        return {
            "pairs_mined": len(pairs),
            "relations_found": 0,
            "message": "Aucune relation detectee apres adjudication",
        }

    # Stage 3 : Persistance
    _p(85, f"Stage 3 : Persistance de {len(results)} relations...")
    persister = RelationPersisterC4(driver, tenant_id=tenant_id)
    counts_before = persister.get_relation_counts()
    persist_stats = persister.persist_batch(results)
    counts_after = persister.get_relation_counts()

    _p(100, f"{persist_stats.created} nouvelles relations creees")

    by_type = {}
    for r in results:
        by_type[r.relation] = by_type.get(r.relation, 0) + 1

    return {
        "corpus_claims": pre_stats["total_claims"],
        "corpus_docs": pre_stats["total_docs"],
        "pairs_mined": len(pairs),
        "relations_found": len(results),
        "by_type": by_type,
        "created": persist_stats.created,
        "updated": persist_stats.updated,
        "errors": persist_stats.errors,
        "counts_before": counts_before,
        "counts_after": counts_after,
    }


def _run_c6_pivots(tenant_id: str, progress=None) -> dict:
    """C6 Cross-doc Pivots : mining via entites partagees + adjudication + persistance."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.relations.pivot_miner_c6 import PivotMinerC6
    from knowbase.relations.pivot_adjudicator_c6 import PivotAdjudicatorC6
    from knowbase.relations.relation_persister_c4 import RelationPersisterC4

    _p = progress or (lambda pct, detail="": None)

    driver = get_neo4j_client().driver

    _p(5, "Stage 1 : Mining paires via pivots...")
    miner = PivotMinerC6(driver, tenant_id=tenant_id)

    pairs = miner.mine_candidates(
        min_pivot_docs=2,
        max_pairs_per_pivot=10,
        max_total_pairs=3000,
        exclude_existing=True,
    )

    if not pairs:
        _p(100, "Aucune paire candidate")
        return {"message": "Aucune paire pivot trouvee", "pairs": 0}

    _p(30, f"Stage 2 : Adjudication de {len(pairs)} paires...")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        _p(100, "ANTHROPIC_API_KEY manquante")
        return {"error": "ANTHROPIC_API_KEY non definie"}

    adjudicator = PivotAdjudicatorC6(max_workers=3)

    def on_adj(done, total):
        pct = 30 + int(50 * done / total)
        _p(pct, f"Adjudication: {done}/{total}")

    results = adjudicator.adjudicate_batch(pairs, on_progress=on_adj)

    if not results:
        _p(100, "Aucune relation C6 detectee")
        return {"pairs_mined": len(pairs), "relations_found": 0}

    _p(85, f"Stage 3 : Persistance de {len(results)} relations...")
    persister = RelationPersisterC4(driver, tenant_id=tenant_id)
    counts_before = persister.get_relation_counts()
    persist_stats = persister.persist_batch(results)
    counts_after = persister.get_relation_counts()

    _p(100, f"{persist_stats.created} nouvelles relations C6")

    by_type = {}
    for r in results:
        by_type[r.relation] = by_type.get(r.relation, 0) + 1

    return {
        "pairs_mined": len(pairs),
        "relations_found": len(results),
        "by_type": by_type,
        "created": persist_stats.created,
        "updated": persist_stats.updated,
        "counts_before": counts_before,
        "counts_after": counts_after,
    }


def _run_build_perspectives(tenant_id: str, progress=None) -> dict:
    """Reconstruit les Perspectives V2 (HDBSCAN + labellisation LLM).

    Skip conditionnel : si moins de MIN_NEW_CLAIMS nouveaux claims depuis
    le dernier build, on saute l'etape (evite le cout inutile a chaque petit ajout).
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    _p = progress or (lambda pct, detail="": None)
    MIN_NEW_CLAIMS = int(os.environ.get("PERSPECTIVE_MIN_NEW_CLAIMS", "50"))

    driver = get_neo4j_client().driver

    # --- Staleness check ---
    _p(5, "Verification staleness Perspectives...")
    with driver.session() as session:
        # Dernier build
        result = session.run(
            "MATCH (p:Perspective) WHERE p.tenant_id = $tid "
            "RETURN max(p.updated_at) AS last_build",
            tid=tenant_id,
        ).single()
        last_build = result["last_build"] if result else None

        if last_build:
            # Compter les claims crees apres le dernier build
            new_claims = session.run(
                "MATCH (c:Claim {tenant_id: $tid}) "
                "WHERE c.created_at > $lb RETURN count(c) AS cnt",
                tid=tenant_id, lb=last_build,
            ).single()["cnt"]
        else:
            # Jamais de build → forcer
            new_claims = MIN_NEW_CLAIMS + 1

    if new_claims < MIN_NEW_CLAIMS:
        msg = f"Skip: seulement {new_claims} nouveaux claims (seuil: {MIN_NEW_CLAIMS})"
        logger.info(f"[POST-IMPORT:PERSPECTIVES] {msg}")
        _p(100, msg)
        return {"skipped": True, "new_claims": new_claims, "threshold": MIN_NEW_CLAIMS}

    # --- Build ---
    _p(15, f"{new_claims} nouveaux claims detectes, lancement build Perspectives...")

    from knowbase.perspectives.orchestrator import run_perspective_engine
    stats = run_perspective_engine(
        tenant_id=tenant_id,
        dry_run=False,
        skip_llm=False,
    )

    _p(100, f"{stats.get('perspectives', 0)} perspectives, {stats.get('claims_linked', 0)} claims lies")
    return {
        "skipped": False,
        "new_claims_trigger": new_claims,
        **stats,
    }


def _run_domain_pack_reprocess(tenant_id: str, progress=None) -> dict:
    from knowbase.domain_packs.reprocess_job import run_reprocess
    from knowbase.domain_packs.registry import get_pack_registry

    registry = get_pack_registry()
    active_packs = registry.get_active_packs(tenant_id)

    if not active_packs:
        return {"message": "Aucun pack actif", "skipped": True}

    total_entities = 0
    total_links = 0
    for pack in active_packs:
        result = run_reprocess(pack.name, tenant_id)
        total_entities += result.get("entities_created", 0)
        total_links += result.get("claims_linked", 0)

    return {
        "packs_processed": len(active_packs),
        "entities_created": total_entities,
        "claims_linked": total_links,
    }


# ============================================================================
# State management (Redis)
# ============================================================================


# ============================================================================
# Estimation dynamique
# ============================================================================

REDIS_BENCHMARK_KEY = "osmose:post_import:benchmarks"


def _get_kg_volume() -> int:
    """Retourne le nombre de claims dans le KG (indicateur de volume)."""
    try:
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        client = get_neo4j_client()
        with client.driver.session(database=client.database) as session:
            result = session.run(
                "MATCH (c:Claim {tenant_id: 'default'}) RETURN count(c) as cnt"
            )
            return result.single()["cnt"]
    except Exception:
        return 0


def _get_step_benchmarks() -> dict:
    """Charge les benchmarks historiques depuis Redis."""
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        raw = rc.client.get(REDIS_BENCHMARK_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {}


def _save_step_benchmark(step_id: str, duration_s: float, volume: int) -> None:
    """Sauvegarde le benchmark d'une étape après exécution."""
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        raw = rc.client.get(REDIS_BENCHMARK_KEY)
        benchmarks = json.loads(raw) if raw else {}
        benchmarks[step_id] = {
            "duration_s": round(duration_s, 1),
            "volume": volume,
            "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        rc.client.set(REDIS_BENCHMARK_KEY, json.dumps(benchmarks))
    except Exception:
        pass


def _format_duration(seconds: float) -> str:
    """Formate une durée en texte lisible."""
    if seconds < 60:
        return f"~{int(seconds)}s"
    elif seconds < 3600:
        mins = seconds / 60
        if mins < 2:
            return f"~{mins:.1f} min"
        return f"~{int(mins)} min"
    else:
        hours = seconds / 3600
        return f"~{hours:.1f}h"


def _update_state(
    tenant_id: str,
    running: bool,
    all_steps: List[str],
    completed: List[str],
    current_step: str = None,
    current_step_name: str = None,
    results: List[dict] = None,
    step_progress: float = 0.0,
    step_detail: str = "",
) -> None:
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        data = {
            "running": running,
            "current_step": current_step,
            "current_step_name": current_step_name,
            "step_progress": step_progress,
            "step_detail": step_detail,
            "step_started_at": time.time() if current_step and step_progress == 0 else None,
            "completed_steps": completed,
            "total_steps": len(all_steps),
            "progress": len(completed) / len(all_steps) if all_steps else 0,
            "results": results or [],
            "updated_at": time.time(),
        }
        rc.client.set(
            f"osmose:post_import:state:{tenant_id}",
            json.dumps(data),
            ex=3600,
        )
    except Exception:
        pass
