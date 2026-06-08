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

from knowbase.api.dependencies import get_tenant_id, get_cockpit_tenant

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
    # Cancel state (A2.6 — cancel-flag dans run_pipeline_job)
    cancelled: bool = False
    cancelled_before_step: Optional[str] = None
    cancelled_at: Optional[float] = None


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
        id="facet_consolidate",
        name="Consolidation racines facettes",
        description="Fusionne les racines sémantiquement équivalentes (privacy + data_protection + gdpr → privacy) via LLM. Crée les CanonicalFacetRoot pour éviter la re-fragmentation lors des futurs imports.",
        order=2,
        estimated_duration="2 - 5min",
        requires_llm=True,
    ),
    StepInfo(
        id="purge_orphan_facets",
        name="Purge facets orphelines",
        description="Deprecated les facets candidates sans claim et avec 1 seul document source (bruit d'extraction LLM).",
        order=2,
        estimated_duration="< 10s",
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
        description="Détecte CONTRADICTS/QUALIFIES/REFINES entre claims cross-doc via embedding similarity + adjudication NLI LLM (Qwen3-235B via DeepInfra, task FAST_CLASSIFICATION). Chaque relation a des preuves verbatim.",
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
        id="explicit_lineage",
        name="Lignée explicite (SUPERSEDES)",
        description="Récolte la lignée de document énoncée explicitement dans les claims (« This AC cancels AC 21-25A »…) et matérialise SUPERSEDES_DOC au niveau document + DECLARES_SUPERSESSION (claim-preuve). Déterministe, sans LLM.",
        order=12,
        estimated_duration="< 10s",
    ),
    StepInfo(
        id="lineage_resolution",
        name="Résolution contradictions par lignée",
        description="ADR_RESOLUTION_CONTRADICTIONS niveaux 1-2 : infère la lignée par convention de version (corroborée par dates), invalide les claims contredits des documents superséd és (CONTRADICTS→SUPERSEDES), et pose le marqueur épistémique 'withdrawn' sur le reste du doc annulé. Déterministe, sans LLM.",
        order=12,
        estimated_duration="< 30s",
    ),
    StepInfo(
        id="adjudicate_contradictions",
        name="Adjudication des contradictions (en contexte)",
        description="#446 : pour chaque paire CONTRADICTS, un juge LLM reçoit les deux claims AVEC leurs passages sources (doc, page) et classe CONFIRMED / DIFFERENT_SCOPE / COMPLEMENTARY / EQUIVALENT / UNCLEAR. Pré-passe déterministe d'équivalence d'unités + double-check des CONFIRMED. Verdict posé sur l'arête (réversible) + rapport JSON tracé. Le runtime ne surface en « divergence » que les CONFIRMED.",
        order=12,
        estimated_duration="5 - 15min",
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
    tenant_id: str = Depends(get_cockpit_tenant),
):
    """État du pipeline en cours d'exécution.

    Multi-tenant : un admin peut suivre un autre tenant via `?tenant_id=X`
    (ex: suivre un import comparatif sur le tenant `aero` depuis le compte
    `default`). Cf get_cockpit_tenant.
    """
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
            job_timeout="3h",  # 8561 paires contradictions = ~1h, + C4/C6/perspectives
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
    """Annule le pipeline en cours.

    Pose un flag Redis (`osmose:post_import:cancel:{tenant_id}`, TTL 10min) que
    `run_pipeline_job` checke avant chaque étape (cf §A2.6 ADR_RELATIONS_CLAIM_CLAIM).
    Le job s'interrompt proprement à la fin de l'étape en cours sans nécessiter
    un restart du worker container.

    La clé d'état Redis (`osmose:post_import:state:{tenant_id}`) sera finalisée
    par le job lui-même avec `cancelled=True` + `cancelled_at`.
    """
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        # Pose le flag (TTL 10min, suffisant pour qu'une étape courte voie le flag)
        rc.client.set(
            f"osmose:post_import:cancel:{tenant_id}",
            "1",
            ex=600,
        )
        return {
            "success": True,
            "message": "Cancel flag posé — pipeline s'arrêtera à la fin de l'étape en cours",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


def _is_cancel_requested(tenant_id: str) -> bool:
    """Vérifie si un cancel a été demandé pour ce tenant.

    Lu par `run_pipeline_job` au début de chaque itération de la boucle steps.
    """
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        return rc.client.exists(f"osmose:post_import:cancel:{tenant_id}") > 0
    except Exception as e:
        logger.debug(f"[PostImport] cancel-check failed: {e}")
        return False


def _clear_cancel_flag(tenant_id: str) -> None:
    """Supprime le flag de cancel (en fin de job, ou au lancement d'un nouveau run)."""
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        rc.client.delete(f"osmose:post_import:cancel:{tenant_id}")
    except Exception as e:
        logger.debug(f"[PostImport] cancel-clear failed: {e}")


# ============================================================================
# Job RQ (exécuté par le worker)
# ============================================================================


def _ensure_vllm_for_full_local() -> bool:
    """En mode full_local, s'assure que vLLM local tourne pour le parallelisme.

    Si vLLM n'est pas actif, le lance automatiquement et active le burst provider.
    Retourne True si vLLM est actif (lance ou deja present), False sinon (fallback Ollama).
    """
    try:
        from knowbase.common.llm_router import get_llm_router, LlmMode
        from knowbase.ingestion.burst.provider_switch import (
            get_burst_state_from_redis,
            start_local_vllm,
            is_local_vllm_running,
            activate_burst_providers,
            _unload_all_ollama_models,
            VLLM_LOCAL_PORT,
            VLLM_LOCAL_CONTAINER,
        )

        # Burst EC2 actif (vLLM DISTANT) = backend parallélisable, quel que soit
        # le LlmMode local. Ce check DOIT précéder le test FULL_LOCAL : sinon un
        # burst distant tombe dans le fallback Ollama séquentiel (#461 — constaté
        # sur l'import aero 08/06, post-import bloqué en mode 1-appel-à-la-fois).
        redis_state = get_burst_state_from_redis()
        if redis_state and redis_state.get("active"):
            logger.info("[PostImport] vLLM burst actif (EC2/distant) — mode parallèle")
            return True

        mode = get_llm_router()._get_llm_mode()
        if mode != LlmMode.FULL_LOCAL:
            return False

        # vLLM container deja lance mais burst pas active?
        if is_local_vllm_running():
            logger.info("[PostImport] vLLM container running, activating burst provider...")
            activate_burst_providers(
                vllm_url=f"http://{VLLM_LOCAL_CONTAINER}:8000",
                embeddings_url="",
                vllm_model="Qwen/Qwen2.5-14B-Instruct-AWQ",
            )
            return True

        # Lancer vLLM automatiquement
        logger.info("[PostImport] Mode full_local — lancement automatique vLLM local...")
        _unload_all_ollama_models()
        result = start_local_vllm()
        if result.get("success"):
            logger.info(f"[PostImport] vLLM local demarre (container: {result.get('container_id')})")
            return True
        else:
            logger.warning(f"[PostImport] vLLM start failed: {result.get('error')} — fallback Ollama")
            return False

    except Exception as e:
        logger.warning(f"[PostImport] vLLM auto-start failed: {e} — fallback Ollama")
        return False


def run_pipeline_job(steps: List[str], tenant_id: str) -> dict:
    """Job RQ — exécute les étapes séquentiellement.

    En mode full_local, lance automatiquement vLLM local pour le parallelisme.

    Cancel : checke le flag Redis `osmose:post_import:cancel:{tenant_id}` au
    début de chaque itération (cf §A2.6 ADR_RELATIONS_CLAIM_CLAIM). Si présent,
    le job s'arrête proprement et finalise l'état avec `cancelled=True`.
    """
    results: List[dict] = []
    pipeline_start = time.time()
    cancelled = False
    cancelled_before_step: Optional[str] = None

    # Clear tout cancel-flag résiduel d'un run précédent (évite cancel "fantôme")
    _clear_cancel_flag(tenant_id)

    # Auto-start vLLM en mode full_local (parallelisme pour C4/C6/perspectives)
    vllm_active = _ensure_vllm_for_full_local()
    if vllm_active:
        logger.info("[PostImport] Pipeline using vLLM local (parallel mode)")
    else:
        logger.info("[PostImport] Pipeline using Ollama (sequential mode)")

    _update_state(tenant_id, running=True, all_steps=steps, completed=[])

    for step_id in steps:
        # Check cancel-flag avant chaque étape (cf A2.6)
        if _is_cancel_requested(tenant_id):
            logger.info(f"[PostImport] Cancel demandé avant '{step_id}' — arrêt propre")
            cancelled = True
            cancelled_before_step = step_id
            break

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

    # Finalisation état (incluant flag cancelled si applicable)
    final_state_kwargs = dict(
        tenant_id=tenant_id,
        running=False,
        all_steps=steps,
        completed=[r["step_id"] for r in results if r["status"] == "success"],
        results=results,
    )
    if cancelled:
        final_state_kwargs["cancelled"] = True
        final_state_kwargs["cancelled_before_step"] = cancelled_before_step
        final_state_kwargs["cancelled_at"] = time.time()
    _update_state(**final_state_kwargs)

    # Nettoyer le flag cancel (idempotent : pas d'effet si pas posé)
    _clear_cancel_flag(tenant_id)

    return {
        "steps": results,
        "total_duration_s": total_duration,
        "success_count": sum(1 for r in results if r["status"] == "success"),
        "error_count": sum(1 for r in results if r["status"] == "error"),
        "cancelled": cancelled,
        "cancelled_before_step": cancelled_before_step,
    }


# ============================================================================
# Exécution des étapes
# ============================================================================


def _execute_step(step_id: str, tenant_id: str, on_progress=None) -> dict:
    noop = lambda pct, detail="": None
    progress = on_progress or noop
    if step_id == "canonicalize":
        return _run_canonicalize(tenant_id, progress)
    elif step_id == "facet_consolidate":
        return _run_facet_consolidate(tenant_id, progress)
    elif step_id == "purge_orphan_facets":
        return _run_purge_orphan_facets(tenant_id, progress)
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
    elif step_id == "explicit_lineage":
        return _run_explicit_lineage(tenant_id, progress)
    elif step_id == "lineage_resolution":
        return _run_lineage_resolution(tenant_id, progress)
    elif step_id == "adjudicate_contradictions":
        return _run_adjudicate_contradictions(tenant_id, progress)
    elif step_id == "build_perspectives":
        return _run_build_perspectives(tenant_id, progress)
    else:
        raise ValueError(f"Étape inconnue: {step_id}")


def _run_adjudicate_contradictions(tenant_id: str, progress=None) -> dict:
    """#446 — adjudication EN CONTEXTE des paires CONTRADICTS (cf
    relations/contradiction_adjudicator.py). Idempotent : ne re-juge que les
    arêtes sans verdict (relancer après chaque detect_contradictions)."""
    from knowbase.relations.contradiction_adjudicator import ContradictionAdjudicator

    summary = ContradictionAdjudicator().run(tenant_id=tenant_id)
    return {
        "n_adjudicated": summary.n_total,
        "n_skipped_already": summary.n_skipped_already,
        "by_verdict": summary.by_verdict,
        "report_path": summary.report_path,
        "duration_s": round(summary.duration_s, 1),
    }


def _run_canonicalize(tenant_id: str, progress=None) -> dict:
    """
    Canonicalisation LLM-validated (remplace l'ancienne MergeArbiter).

    Enchaine :
    1. canonicalize_entities_cross_doc.py (alias + prefix + stem + LLM validation)
    2. canonicalize_embedding_clusters.py (embeddings + LLM validation)
    """
    import subprocess

    _p = progress or (lambda pct, detail="": None)
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    _p(5, "Comptage des entites canoniques existantes...")
    with driver.session() as session:
        before = session.run(
            "MATCH (ce:CanonicalEntity {tenant_id: $tid}) RETURN count(ce) as cnt",
            tid=tenant_id,
        ).single()["cnt"]

    _p(15, "Cross-doc canonicalization (alias + prefix + stem + LLM)...")
    r1 = subprocess.run(
        ["python", "scripts/canonicalize_entities_cross_doc.py",
         "--execute", "--tenant", tenant_id],
        capture_output=True, text=True, timeout=3600, cwd="/app",
    )
    if r1.returncode != 0:
        raise RuntimeError(
            f"cross_doc canonicalization failed: "
            f"{r1.stderr[-400:] if r1.stderr else r1.stdout[-400:]}"
        )

    _p(55, "Embedding clusters (cosine + LLM)...")
    r2 = subprocess.run(
        ["python", "scripts/canonicalize_embedding_clusters.py",
         "--execute", "--tenant", tenant_id,
         "--threshold", "0.92", "--max-cluster-size", "8"],
        capture_output=True, text=True, timeout=3600, cwd="/app",
    )
    if r2.returncode != 0:
        # Non-bloquant : si l'embedding cluster echoue, on a deja le cross-doc
        logger.warning(
            f"embedding clusters step failed (non-blocking): "
            f"{r2.stderr[-300:] if r2.stderr else r2.stdout[-300:]}"
        )

    _p(95, "Comptage final...")
    with driver.session() as session:
        after = session.run(
            "MATCH (ce:CanonicalEntity {tenant_id: $tid}) RETURN count(ce) as cnt",
            tid=tenant_id,
        ).single()["cnt"]

    _p(100, f"{after - before} nouveaux canoniques crees")
    return {
        "canonical_before": before,
        "canonical_after": after,
        "new_canonicals": after - before,
        "cross_doc_ok": r1.returncode == 0,
        "embedding_clusters_ok": r2.returncode == 0,
    }


def _run_purge_orphan_facets(tenant_id: str, progress=None) -> dict:
    """
    Purge les facets candidates sans claim et sans croissance multi-doc.

    Critere : lifecycle='candidate' ET source_doc_count <= 1 ET 0 claim lie.
    Ces facets sont du bruit d'extraction LLM (propositions uniques qui n'ont
    jamais trouve de doc ou claim supplementaire pour valider leur pertinence).
    Plutot que DELETE, on deprecated pour tracabilite.
    """
    _p = progress or (lambda pct, detail="": None)
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    _p(10, "Identification facets orphelines...")
    with driver.session() as session:
        result = session.run(
            """
            MATCH (f:Facet {tenant_id: $tid})
            WHERE f.lifecycle = 'candidate'
              AND coalesce(f.source_doc_count, 0) <= 1
              AND NOT (:Claim)-[:BELONGS_TO_FACET]->(f)
            SET f.lifecycle = 'deprecated',
                f.deprecated_at = datetime(),
                f.deprecation_reason = 'zero_usage_single_source'
            RETURN count(*) AS purged
            """,
            tid=tenant_id,
        ).single()
        purged = result["purged"] or 0

    _p(100, f"{purged} facets orphelines deprecated")
    return {"orphan_facets_deprecated": purged}


def _run_facet_consolidate(tenant_id: str, progress=None) -> dict:
    """
    Consolidation des racines de Facets via LLM validation.

    Fusionne les racines semantiquement equivalentes (ex: privacy + data_protection
    + gdpr → privacy), et cree les CanonicalFacetRoot nodes pour l'anti-drift
    futur (consulte par FacetRegistry lors des prochains imports).
    """
    import subprocess

    _p = progress or (lambda pct, detail="": None)
    _p(10, "Consolidation racines facets...")
    result = subprocess.run(
        ["python", "scripts/consolidate_facet_roots.py",
         "--execute", "--tenant", tenant_id, "--threshold", "0.90"],
        capture_output=True, text=True, timeout=1800, cwd="/app",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"facet consolidation failed: "
            f"{result.stderr[-400:] if result.stderr else result.stdout[-400:]}"
        )

    _p(100, "Consolidation terminee")
    stats = {"facets_renamed": 0, "canonical_roots_created": 0}
    for line in result.stdout.split("\n"):
        if "facets renommees" in line:
            try:
                # Format : "→ {N} facets renommees"
                num = int(line.split("→")[1].split("facets")[0].strip())
                stats["facets_renamed"] = num
            except (IndexError, ValueError):
                pass
        elif "CanonicalFacetRoot nodes" in line:
            try:
                num = int(line.split("→")[1].split("CanonicalFacetRoot")[0].strip())
                stats["canonical_roots_created"] = num
            except (IndexError, ValueError):
                pass
    return stats


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
    # A2.9 — CHAINS_TO est directionnelle (c1 → c2 : c1 chaîne vers c2) :
    # valid_from_relation = c1.valid_from (la chaîne prend effet à la date de validité du claim source)
    persisted = 0
    with driver.session() as session:
        for link in links:
            r = session.run(
                """
                MATCH (c1:Claim {claim_id: $c1id, tenant_id: $tid})
                MATCH (c2:Claim {claim_id: $c2id, tenant_id: $tid})
                MERGE (c1)-[r:CHAINS_TO]->(c2)
                ON CREATE SET
                    r.confidence = 1.0,
                    r.method = 'spo_join_cross_doc',
                    r.cross_doc = true,
                    r.source_doc_id = $sdid,
                    r.target_doc_id = $tdid,
                    r.join_key_name = $jkn,
                    r.marker_type = 'inferred',
                    r.detected_at = datetime(),
                    r.valid_from_relation = c1.valid_from,
                    r.invalidated_relation_at = coalesce(c1.invalidated_at, c2.invalidated_at)
                ON MATCH SET
                    r.invalidated_relation_at = coalesce(r.invalidated_relation_at, c1.invalidated_at, c2.invalidated_at)
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

    # A2.9 — Timestamps systématiques sur les relations cross-claim (cf ADR_RELATIONS_CLAIM_CLAIM §2.3)
    #   detected_at         : datetime() au create (équivalent ingested_at côté Claim)
    #   valid_from_relation : règle distincte symétrique (max) vs directionnelle (B.valid_from)
    #   invalidated_relation_at : NULL au create, cascade par SupersessionApplier si claim invalidé
    # CONTRADICTS = symétrique → max(c1.valid_from, c2.valid_from), NULL si l'un NULL
    # REFINES / QUALIFIES = directionnelles (c1 → c2 : c1 précise/conditionne c2) → c1.valid_from
    CYPHER_BY_TYPE = {
        "CONTRADICTS": """
            MATCH (c1:Claim {claim_id: $c1id, tenant_id: $tid})
            MATCH (c2:Claim {claim_id: $c2id, tenant_id: $tid})
            MERGE (c1)-[r:CONTRADICTS]->(c2)
            ON CREATE SET
                r.confidence = $conf,
                r.method = 'post_import_cross_doc',
                r.basis = $basis,
                r.marker_type = $marker_type,
                r.detected_at = datetime(),
                r.valid_from_relation = CASE
                    WHEN c1.valid_from IS NOT NULL AND c2.valid_from IS NOT NULL THEN
                        CASE WHEN c1.valid_from > c2.valid_from THEN c1.valid_from ELSE c2.valid_from END
                    ELSE NULL
                END,
                r.invalidated_relation_at = coalesce(c1.invalidated_at, c2.invalidated_at)
            ON MATCH SET
                r.confidence = CASE WHEN $conf > coalesce(r.confidence, 0.0) THEN $conf ELSE r.confidence END,
                r.invalidated_relation_at = coalesce(r.invalidated_relation_at, c1.invalidated_at, c2.invalidated_at)
        """,
        "REFINES": """
            MATCH (c1:Claim {claim_id: $c1id, tenant_id: $tid})
            MATCH (c2:Claim {claim_id: $c2id, tenant_id: $tid})
            MERGE (c1)-[r:REFINES]->(c2)
            ON CREATE SET
                r.confidence = $conf,
                r.method = 'post_import_cross_doc',
                r.basis = $basis,
                r.marker_type = $marker_type,
                r.detected_at = datetime(),
                r.valid_from_relation = c1.valid_from,
                r.invalidated_relation_at = coalesce(c1.invalidated_at, c2.invalidated_at)
            ON MATCH SET
                r.confidence = CASE WHEN $conf > coalesce(r.confidence, 0.0) THEN $conf ELSE r.confidence END,
                r.invalidated_relation_at = coalesce(r.invalidated_relation_at, c1.invalidated_at, c2.invalidated_at)
        """,
        "QUALIFIES": """
            MATCH (c1:Claim {claim_id: $c1id, tenant_id: $tid})
            MATCH (c2:Claim {claim_id: $c2id, tenant_id: $tid})
            MERGE (c1)-[r:QUALIFIES]->(c2)
            ON CREATE SET
                r.confidence = $conf,
                r.method = 'post_import_cross_doc',
                r.basis = $basis,
                r.marker_type = $marker_type,
                r.detected_at = datetime(),
                r.valid_from_relation = c1.valid_from,
                r.invalidated_relation_at = coalesce(c1.invalidated_at, c2.invalidated_at)
            ON MATCH SET
                r.confidence = CASE WHEN $conf > coalesce(r.confidence, 0.0) THEN $conf ELSE r.confidence END,
                r.invalidated_relation_at = coalesce(r.invalidated_relation_at, c1.invalidated_at, c2.invalidated_at)
        """,
    }

    # A2.8 — SupersessionApplier : pour chaque CONTRADICTS persistée, appliquer
    # la règle §9.4 (CAS 1-4) → :SUPERSEDES + invalidated_at OU :ConflictPending
    from knowbase.relations.supersession_applier import SupersessionApplier
    supersession_applier = SupersessionApplier(driver, tenant_id=tenant_id)
    supersession_counts = {
        "supersedes_created": 0,
        "conflict_pending_created": 0,
        "supersession_skipped": 0,
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
                evidence_a = rel.get("evidence_a", "") or rel.get("evidence", "")
                evidence_b = rel.get("evidence_b", "")
                reasoning = rel.get("reasoning", "") or basis
            else:
                rel_type = rel.relation_type.value
                c1id = rel.source_claim_id
                c2id = rel.target_claim_id
                conf = rel.confidence
                basis = rel.basis or ""
                evidence_a = getattr(rel, "evidence_a", "") or ""
                evidence_b = getattr(rel, "evidence_b", "") or ""
                reasoning = getattr(rel, "reasoning", "") or basis

            cypher = CYPHER_BY_TYPE.get(rel_type)
            if not cypher:
                continue
            # A2.9 — marker_type cohérent entre persistance Cypher + SupersessionApplier
            marker_type = "inferred" if conf >= 0.85 else "prudence"
            try:
                session.run(
                    cypher,
                    c1id=c1id, c2id=c2id, tid=tenant_id,
                    conf=conf, basis=basis,
                    marker_type=marker_type,
                )
                persisted += 1
            except Exception as e:
                logger.warning(f"[PostImport:Contradictions] Persist error: {e}")
                continue

            # A2.8 — Application règle §9.4 pour CONTRADICTS uniquement
            # (REFINES/QUALIFIES n'invalident pas par construction — cf ADR §2.1)
            if rel_type != "CONTRADICTS":
                continue

            try:
                decision = supersession_applier.apply(
                    claim_a_id=c1id,
                    claim_b_id=c2id,
                    relation_type="CONTRADICTS",
                    evidence_a=evidence_a,
                    evidence_b=evidence_b,
                    confidence=conf,
                    marker_type=marker_type,
                    detection_method="post_import_cross_doc",
                    detection_source="detect_contradictions",
                    reasoning=reasoning,
                )
                if decision.action == "supersedes":
                    supersession_counts["supersedes_created"] += 1
                elif decision.action == "conflict_pending":
                    supersession_counts["conflict_pending_created"] += 1
                else:
                    supersession_counts["supersession_skipped"] += 1
            except Exception as e:
                logger.warning(
                    f"[PostImport:Contradictions] Supersession apply failed for {c1id} vs {c2id}: {e}"
                )
                supersession_counts["supersession_skipped"] += 1

    # Compter les nouvelles relations
    with driver.session() as session:
        after = session.run(
            "MATCH ()-[r:CONTRADICTS|REFINES|QUALIFIES]->() "
            "RETURN type(r) as t, count(r) as c"
        )
        after_counts = {r["t"]: r["c"] for r in after}

    logger.info(
        f"[PostImport:Contradictions] Supersession A2.8 — "
        f"{supersession_counts['supersedes_created']} :SUPERSEDES créées, "
        f"{supersession_counts['conflict_pending_created']} :ConflictPending créés, "
        f"{supersession_counts['supersession_skipped']} skipped"
    )

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
        # A2.8 — métriques de supersession
        "supersedes_created": supersession_counts["supersedes_created"],
        "conflict_pending_created": supersession_counts["conflict_pending_created"],
        "supersession_skipped": supersession_counts["supersession_skipped"],
    }


# ============================================================================
# LLM direct comparison (Phase B)
# ============================================================================

# DEVIATION 2026-05-21 — prompt duplication, voir doc/ongoing/etudes/deviations_log.md
# Ce prompt fait la même tâche que `nli_adjudicator.py:NLI_PROMPT` mais en parallèle. À unifier
# en `claim_relation_classifier.py` partagé quand Phase A3 ou refacto suivante.
# Si tu modifies ce prompt, vérifie/synchronise `nli_adjudicator.NLI_PROMPT`.
_LLM_COMPARE_SYSTEM = """You compare pairs of factual claims from different documents.
For each pair, determine if they CONTRADICT or can CO-EXIST.

═══════════════════════════════════════════════════════════════
CRITICAL TEST: "Can both claims be TRUE SIMULTANEOUSLY in the real world?"
═══════════════════════════════════════════════════════════════
  • If YES → NOT a contradiction (label: REFINES, QUALIFIES, COMPATIBLE, or UNRELATED)
  • If NO  → CONTRADICTS (only when both cannot be true for the SAME scope/version/condition)

Apply this test rigorously. Surface text similarity is NOT a signal of contradiction.

═══════════════════════════════════════════════════════════════
EXAMPLES of NON-contradiction (CAN co-exist) — these are NEVER CONTRADICTS:
═══════════════════════════════════════════════════════════════

(1) Different versions/products in parallel — each version is a distinct system:
    A: "Product X v2021 supports feature A"
    B: "Product X v2023 supports feature B"
    → COMPATIBLE  (v2021 and v2023 are separate systems running in parallel)

(2) Different tools, same restriction — same rule applies to multiple objects:
    A: "Tool Alpha is limited to monitoring tasks"
    B: "Tool Beta is limited to monitoring tasks"
    → COMPATIBLE  (two tools with the same restriction, not a contradiction)

(3) List of options — multiple methods supported for the same goal:
    A: "Process P can use method M1 as input"
    B: "Process P can use method M2 as input"
    → COMPATIBLE  (P supports M1 OR M2, both are valid)

(4) Pricing/scaling by tier — different rates for different usage levels:
    A: "1 unit = 1 advanced use"
    B: "1 unit = 0.5 developer access"
    → COMPATIBLE  (tiered pricing, not contradictory rates)

(5) One claim is more specific (sub-case):
    A: "All systems support feature X"
    B: "System Y supports feature X with parameters A and B"
    → REFINES  (B is a specific instance of A)

(6) One adds a condition or exception:
    A: "Feature X is enabled"
    B: "Feature X is enabled only when condition Y is set"
    → QUALIFIES  (B conditions A)

(7) Same fact rephrased:
    A: "The maximum is 100"
    B: "Up to 100 is allowed"
    → COMPATIBLE  (restatement of the same fact)

═══════════════════════════════════════════════════════════════
EXAMPLES of REAL CONTRADICTION — both cannot be true:
═══════════════════════════════════════════════════════════════

(1) Same subject, opposite assertion (NO version/scope qualifier):
    A: "Module M uses architecture monolithic"
    B: "Module M uses architecture microservices"
    → CONTRADICTS  (same subject M, mutually exclusive architectures)

(2) Same measurement, different values (SAME conditions):
    A: "Process completes in 30 seconds (default config)"
    B: "Process completes in 60 seconds (default config)"
    → CONTRADICTS  (same conditions, incompatible values)

(3) Same entity, mutually exclusive lifecycle states:
    A: "Feature X is deprecated as of v2022"
    B: "Feature X is fully supported in v2023"
    → CONTRADICTS  (deprecated vs fully supported are exclusive states)

═══════════════════════════════════════════════════════════════
LABELS:
═══════════════════════════════════════════════════════════════
- CONTRADICTS  : Both cannot be true SIMULTANEOUSLY for the same scope/version/condition.
- REFINES      : One claim adds precision (sub-case, more specific instance).
- QUALIFIES    : One claim adds a condition, exception, or temporal/contextual nuance.
- COMPATIBLE   : Both can be true (parallel scopes, complementary facts, restatement).
- UNRELATED    : Different topics despite being clustered together.

═══════════════════════════════════════════════════════════════
GOLDEN RULE: When in doubt, choose COMPATIBLE.
False contradictions destroy knowledge integrity by removing valid claims from the KG.
A missed contradiction is recoverable; an erroneous one corrupts downstream reasoning.
═══════════════════════════════════════════════════════════════

Respond as JSON: {"results": [{"pair": 1, "label": "...", "reason": "brief explanation focused on the SIMULTANEOUS-TRUTH test"}, ...]}"""


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


# Version du prompt NLI C4/C6. Incrementer lors de changement de prompt pour
# permettre une re-adjudication selective (future fonctionnalite).
SCAN_PROMPT_VERSION = "v1"


def _persist_scanned_markers(
    driver,
    tenant_id: str,
    results: list,
    *,
    relation_type: str,
    model: str,
) -> int:
    """Persiste un marker :C4_SCANNED ou :C6_SCANNED pour chaque paire adjudiquee.

    Permet de tracer toutes les paires deja adjudiquees (y compris NONE) afin
    que les runs incrementaux (2K/3K/5K paires) ne les re-adjudiquent pas.

    Args:
        driver: Neo4j driver
        tenant_id: Tenant ID
        results: Liste AdjudicationResult | PivotAdjudicationResult
        relation_type: "C4_SCANNED" ou "C6_SCANNED"
        model: Nom du modele LLM utilise (pour traçabilite)

    Returns:
        Nombre de markers persistes
    """
    import time as _time
    if not results:
        return 0

    now = _time.time()
    persisted = 0
    # Batch par chunks pour eviter transactions trop grandes
    CHUNK = 500
    with driver.session() as session:
        for i in range(0, len(results), CHUNK):
            batch = results[i:i + CHUNK]
            payload = [
                {
                    "a_id": r.claim_a_id,
                    "b_id": r.claim_b_id,
                    "relation_found": r.relation,
                    "confidence": float(r.confidence or 0.0),
                    "above_threshold": bool(getattr(r, "above_threshold", False)),
                    "scanned_at": now,
                    "model": model,
                    "prompt_version": SCAN_PROMPT_VERSION,
                }
                for r in batch
            ]
            query = (
                "UNWIND $batch AS p "
                "MATCH (a:Claim {claim_id: p.a_id, tenant_id: $tid}) "
                "MATCH (b:Claim {claim_id: p.b_id, tenant_id: $tid}) "
                f"MERGE (a)-[s:{relation_type}]->(b) "
                "SET s.relation_found = p.relation_found, "
                "    s.confidence = p.confidence, "
                "    s.above_threshold = p.above_threshold, "
                "    s.scanned_at = p.scanned_at, "
                "    s.model = p.model, "
                "    s.prompt_version = p.prompt_version "
                "RETURN count(s) AS n"
            )
            r = session.run(query, batch=payload, tid=tenant_id).single()
            persisted += r["n"] if r else 0
    return persisted


def _run_explicit_lineage(tenant_id: str, progress=None) -> dict:
    """Récolte la lignée de document explicite (SUPERSEDES_DOC) depuis les claims.

    Déterministe, sans LLM. Voir
    src/knowbase/relations/explicit_lineage_detector.py.
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.relations.explicit_lineage_detector import ExplicitLineageDetector

    _p = progress or (lambda pct, detail="": None)
    driver = get_neo4j_client().driver

    _p(10, "Scan des claims de supersession de document...")
    det = ExplicitLineageDetector(driver, tenant_id=tenant_id)
    edges, rejects = det.scan()

    _p(60, f"{len(edges)} lignées détectées, matérialisation...")
    res = det.apply(edges)

    _p(100, f"{res['edges_written']} relations SUPERSEDES_DOC écrites")
    return {
        "edges_written": res["edges_written"],
        "chains_detected": len(edges),
        "candidates_rejected": len(rejects),
    }


def _run_lineage_resolution(tenant_id: str, progress=None) -> dict:
    """Résolution des contradictions par lignée documentaire (ADR niveaux 1-2).

    Voir src/knowbase/relations/lineage_resolution.py + ADR_RESOLUTION_CONTRADICTIONS.
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.relations.lineage_resolution import LineageResolver

    _p = progress or (lambda pct, detail="": None)
    _p(10, "Inférence lignée par convention de version + résolution…")
    resolver = LineageResolver(get_neo4j_client().driver, tenant_id=tenant_id)
    report = resolver.run(dry_run=False)
    _p(100, f"{report.pairs_resolved} paires résolues, "
            f"{report.container_withdrawn} claims 'withdrawn'")
    return report.summary()


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

    # Stage 2 : Adjudication NLI via llm_router (DeepInfra Qwen3-14B)
    adjudicator = NLIAdjudicator()  # utilise le default (100 workers, sweet spot DeepInfra)

    def on_adj(done, total):
        pct = 30 + int(50 * done / total)
        _p(pct, f"Adjudication: {done}/{total}")

    all_results = adjudicator.adjudicate_batch(pairs, on_progress=on_adj)
    valid_results = [r for r in all_results if r.above_threshold and r.evidence_valid]

    # Stage 3a : Trace ALL adjudicated pairs via :C4_SCANNED (runs incrementaux)
    _p(80, f"Stage 3a : Marquage de {len(all_results)} paires adjudiquees...")
    scanned_persisted = _persist_scanned_markers(
        driver, tenant_id, all_results, relation_type="C4_SCANNED", model="Qwen/Qwen3-14B"
    )

    # Stage 3b : Persistance des vraies relations
    if valid_results:
        _p(90, f"Stage 3b : Persistance de {len(valid_results)} relations valides...")
        persister = RelationPersisterC4(driver, tenant_id=tenant_id)
        counts_before = persister.get_relation_counts()
        persist_stats = persister.persist_batch(valid_results)
        counts_after = persister.get_relation_counts()
    else:
        counts_before = {}
        counts_after = {}
        persist_stats = type("Stats", (), {"created": 0, "updated": 0, "errors": 0})()

    _p(100, f"{persist_stats.created} relations valides + {scanned_persisted} marqueurs scanned")

    by_type = {}
    for r in valid_results:
        by_type[r.relation] = by_type.get(r.relation, 0) + 1

    return {
        "corpus_claims": pre_stats["total_claims"],
        "corpus_docs": pre_stats["total_docs"],
        "pairs_mined": len(pairs),
        "pairs_adjudicated": len(all_results),
        "pairs_scanned_persisted": scanned_persisted,
        "relations_found": len(valid_results),
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

    # Adjudication via llm_router (DeepInfra Qwen3-14B)
    adjudicator = PivotAdjudicatorC6()  # utilise le default (100 workers, sweet spot DeepInfra)

    def on_adj(done, total):
        pct = 30 + int(50 * done / total)
        _p(pct, f"Adjudication: {done}/{total}")

    all_results = adjudicator.adjudicate_batch(pairs, on_progress=on_adj)
    valid_results = [r for r in all_results if r.above_threshold and r.evidence_valid]

    # Stage 3a : Trace ALL adjudicated pairs via :C6_SCANNED
    _p(80, f"Stage 3a : Marquage de {len(all_results)} paires adjudiquees...")
    scanned_persisted = _persist_scanned_markers(
        driver, tenant_id, all_results, relation_type="C6_SCANNED", model="Qwen/Qwen3-14B"
    )

    # Stage 3b : Persistance des vraies relations
    if valid_results:
        _p(90, f"Stage 3b : Persistance de {len(valid_results)} relations C6 valides...")
        persister = RelationPersisterC4(driver, tenant_id=tenant_id)
        counts_before = persister.get_relation_counts()
        persist_stats = persister.persist_batch(valid_results)
        counts_after = persister.get_relation_counts()
    else:
        counts_before = {}
        counts_after = {}
        persist_stats = type("Stats", (), {"created": 0, "updated": 0, "errors": 0})()

    _p(100, f"{persist_stats.created} relations C6 + {scanned_persisted} marqueurs scanned")

    by_type = {}
    for r in valid_results:
        by_type[r.relation] = by_type.get(r.relation, 0) + 1

    return {
        "pairs_mined": len(pairs),
        "pairs_adjudicated": len(all_results),
        "pairs_scanned_persisted": scanned_persisted,
        "relations_found": len(valid_results),
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
    cancelled: bool = False,
    cancelled_before_step: Optional[str] = None,
    cancelled_at: Optional[float] = None,
) -> None:
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        state_key = f"osmose:post_import:state:{tenant_id}"

        # Preserver step_started_at tant que current_step ne change pas
        # (evite de perdre le timestamp entre progressions d'une meme etape)
        previous_started_at = None
        try:
            prev_raw = rc.client.get(state_key)
            if prev_raw:
                prev = json.loads(prev_raw)
                if prev.get("current_step") == current_step:
                    previous_started_at = prev.get("step_started_at")
        except Exception:
            previous_started_at = None

        if current_step:
            step_started_at = previous_started_at or time.time()
        else:
            step_started_at = None

        data = {
            "running": running,
            "current_step": current_step,
            "current_step_name": current_step_name,
            "step_progress": step_progress,
            "step_detail": step_detail,
            "step_started_at": step_started_at,
            "completed_steps": completed,
            "total_steps": len(all_steps),
            "progress": len(completed) / len(all_steps) if all_steps else 0,
            "results": results or [],
            "updated_at": time.time(),
            "cancelled": cancelled,
            "cancelled_before_step": cancelled_before_step,
            "cancelled_at": cancelled_at,
        }
        rc.client.set(state_key, json.dumps(data), ex=3600)
    except Exception:
        pass
