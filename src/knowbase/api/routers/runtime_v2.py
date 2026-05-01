"""
Router API Runtime V2 — Pipeline anchor-driven.

Endpoint POST /api/runtime_v2/answer
Endpoint GET  /api/runtime_v2/health
"""
from __future__ import annotations

import logging
import os
from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, HTTPException
from neo4j import GraphDatabase
from pydantic import BaseModel, Field

from knowbase.common.clients.shared_clients import (
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.config.settings import get_settings
from knowbase.runtime_v2 import RuntimeV2Pipeline
from knowbase.runtime_v2.models import PipelineResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runtime_v2", tags=["runtime_v2"])


class AnswerRequest(BaseModel):
    question: str = Field(..., min_length=2, description="Question utilisateur en langage naturel")
    audit_mode: bool = Field(False, description="Mode Audit (compliance officer) — remonte les contradictions")
    as_of: Optional[date_cls] = Field(
        None,
        description="Date pour Current Resolver (default = today). Permet la résolution temporelle au passé.",
    )
    top_k_claims: int = Field(10, ge=1, le=50)


_pipeline_instance: Optional[RuntimeV2Pipeline] = None


def _resolve_vllm_url() -> tuple[str, str]:
    """Résout l'URL vLLM en priorisant Redis burst state, puis env, puis default.

    Pattern cohérent avec le burst attach process qui maintient l'IP courante
    dans osmose:burst:state (cf. memory_recent project_incident_redis).
    """
    # 1. Redis burst state (le plus à jour)
    try:
        import redis as _redis
        r = _redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, password=os.getenv("REDIS_PASSWORD") or None, decode_responses=True)
        raw = r.get("osmose:burst:state")
        if raw:
            import json as _json
            state = _json.loads(raw)
            if state.get("active") and state.get("vllm_url"):
                return state["vllm_url"], state.get("vllm_model", "Qwen/Qwen2.5-14B-Instruct-AWQ")
    except Exception as exc:
        logger.warning("Could not read Redis burst state: %s", exc)

    # 2. Env var
    vllm_url = os.getenv("VLLM_URL")
    if vllm_url:
        return vllm_url, os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

    # 3. Default (probablement obsolète)
    return "http://18.199.218.46:8000", "Qwen/Qwen2.5-14B-Instruct-AWQ"


def _get_pipeline(force_reload: bool = False) -> RuntimeV2Pipeline:
    """Lazy singleton du pipeline (les clients sont coûteux à initialiser)."""
    global _pipeline_instance
    if _pipeline_instance is not None and not force_reload:
        return _pipeline_instance

    settings = get_settings()
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    tenant_id = os.getenv("TENANT_ID", "default")

    vllm_url, vllm_model = _resolve_vllm_url()
    logger.info("Pipeline V2 init with vLLM URL: %s (model=%s)", vllm_url, vllm_model)

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    qdrant = get_qdrant_client()
    embedder = get_sentence_transformer(
        settings.embeddings_model, cache_folder=str(settings.hf_home)
    )

    _pipeline_instance = RuntimeV2Pipeline(
        driver=driver,
        qdrant_client=qdrant,
        embedder=embedder,
        vllm_url=vllm_url,
        tenant_id=tenant_id,
        vllm_model=vllm_model,
    )
    return _pipeline_instance


@router.post("/answer", response_model=PipelineResponse)
def answer(request: AnswerRequest) -> PipelineResponse:
    """Execute le pipeline V2 anchor-driven sur une question.

    Réponse structurée selon `decision` :
    - ANSWERED_AUTHORITATIVE / ANSWERED_SCOPED : claims dans le scope
    - ANSWERED_EVOLUTION : evolution_points (timeline)
    - ESCALATE_AMBIGUOUS / ESCALATE_NO_DOCS : escalation_message + alternatives
    - AUDIT_REPORT : conflicts intra-anchor (audit_mode=True)
    """
    import json as _json
    import time as _time
    import uuid as _uuid
    from datetime import datetime as _dt

    request_id = _uuid.uuid4().hex[:12]
    t_start = _time.time()
    try:
        pipeline = _get_pipeline()
        response = pipeline.answer(
            question=request.question,
            audit_mode=request.audit_mode,
            as_of=request.as_of,
            top_k_claims=request.top_k_claims,
        )
        # P5 polish — log structuré JSON pour Loki/Grafana (ADR_RUNTIME_V2_OPERATIONAL)
        try:
            entry = {
                "ts": _dt.utcnow().isoformat() + "Z",
                "request_id": request_id,
                "event": "runtime_v2.answer",
                "audit_mode": request.audit_mode,
                "question_len": len(request.question),
                "decision": response.decision.value,
                "anchor_type": response.anchor.anchor_type.value,
                "n_authoritative_docs": len(response.authoritative_doc_ids or []),
                "n_claims": len(response.claims or []),
                "n_conflicts": len(response.conflicts or []),
                "n_unresolved_conflicts": sum(
                    1 for c in (response.conflicts or [])
                    if not c.is_resolved_by_lifecycle
                ),
                "n_evolution_points": len(response.evolution_points or []),
                "trust_score": response.trust_score,
                "latency_ms": round((_time.time() - t_start) * 1000, 1),
                "has_synthesis": bool(response.synthesized_answer),
            }
            logger.info(f"RUNTIME_V2_METRIC {_json.dumps(entry, default=str)}")
        except Exception as log_exc:
            logger.warning(f"Failed to emit structured log: {log_exc}")
        return response
    except Exception as exc:
        # Log structuré pour échec aussi
        try:
            entry = {
                "ts": _dt.utcnow().isoformat() + "Z",
                "request_id": request_id,
                "event": "runtime_v2.answer.error",
                "error": str(exc),
                "latency_ms": round((_time.time() - t_start) * 1000, 1),
            }
            logger.error(f"RUNTIME_V2_METRIC {_json.dumps(entry, default=str)}")
        except Exception:
            pass
        logger.error("Pipeline V2 failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pipeline V2 error: {exc}")


@router.get("/health")
def health() -> dict:
    """Vérifie que le pipeline est initialisable."""
    try:
        _get_pipeline()
        return {"status": "ok", "pipeline": "RuntimeV2Pipeline"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@router.get("/lifecycle_graph")
def lifecycle_graph(focus_doc_id: Optional[str] = None, depth: int = 1) -> dict:
    """Graph view lifecycle — retourne nodes (docs) + edges (LIFECYCLE_RELATION).

    Si focus_doc_id fourni : graphe ego-centré (radius=depth).
    Sinon : graphe global (toutes LIFECYCLE_RELATION du tenant).
    """
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    tenant_id = os.getenv("TENANT_ID", "default")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session() as session:
            if focus_doc_id:
                # Ego-graph : voisinage à distance <= depth
                cypher = """
                MATCH path = (focus:DocumentContext {doc_id: $focus, tenant_id: $tid})
                              -[r:LIFECYCLE_RELATION*1..%d]-(other:DocumentContext)
                WITH focus, relationships(path) AS rels, other
                UNWIND rels AS r
                WITH DISTINCT startNode(r) AS src, r, endNode(r) AS tgt
                RETURN
                  src.doc_id AS src_id,
                  coalesce(src.primary_subject, '') AS src_subject,
                  tgt.doc_id AS tgt_id,
                  coalesce(tgt.primary_subject, '') AS tgt_subject,
                  r.type AS rel_type,
                  coalesce(r.confidence, 0.0) AS confidence
                """ % max(1, min(depth, 3))
                rows = session.run(cypher, focus=focus_doc_id, tid=tenant_id).data()
            else:
                rows = session.run(
                    """
                    MATCH (src:DocumentContext)-[r:LIFECYCLE_RELATION]->(tgt:DocumentContext)
                    WHERE src.tenant_id = $tid AND tgt.tenant_id = $tid
                    RETURN src.doc_id AS src_id, coalesce(src.primary_subject, '') AS src_subject,
                           tgt.doc_id AS tgt_id, coalesce(tgt.primary_subject, '') AS tgt_subject,
                           r.type AS rel_type, coalesce(r.confidence, 0.0) AS confidence
                    LIMIT 100
                    """,
                    tid=tenant_id,
                ).data()

        # Construct nodes + edges
        nodes_map = {}
        edges = []
        for row in rows:
            for nid, sub in [(row["src_id"], row["src_subject"]), (row["tgt_id"], row["tgt_subject"])]:
                if nid not in nodes_map:
                    nodes_map[nid] = {
                        "id": nid,
                        "label": (sub or nid)[:60],
                        "is_focus": nid == focus_doc_id,
                    }
            edges.append({
                "from": row["src_id"],
                "to": row["tgt_id"],
                "type": row["rel_type"],
                "confidence": row["confidence"],
            })
        return {
            "focus_doc_id": focus_doc_id,
            "nodes": list(nodes_map.values()),
            "edges": edges,
            "n_nodes": len(nodes_map),
            "n_edges": len(edges),
        }
    finally:
        driver.close()


@router.get("/claim_detail/{claim_id}")
def claim_detail(claim_id: str) -> dict:
    """Drill-down P5 polish — détail d'un claim + ses LOGICAL_RELATION Claim→Claim.

    Retourne :
    - text + doc_id + passage_text + publication_date + applicability
    - logical_outgoing : 9 types Logical (CONFLICT/SUBSET/EQUIVALENT/EXCEPTION/...) sortantes
    - logical_incoming : entrantes (autres claims qui pointent vers celui-ci)
    - facets_belongs_to : Facets liées via BELONGS_TO_FACET
    """
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    tenant_id = os.getenv("TENANT_ID", "default")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session() as session:
            # Metadata claim
            row = session.run(
                """
                MATCH (c:Claim {claim_id: $cid, tenant_id: $tid})
                RETURN c.claim_id AS claim_id,
                       c.doc_id AS doc_id,
                       c.text AS text,
                       coalesce(c.passage_text, '') AS passage_text,
                       c.publication_date AS publication_date,
                       coalesce(c.applicability_axis_release_id, '') AS release_id,
                       coalesce(c.applicability_axis_temporal_value, '') AS temporal,
                       c.lifecycle_status AS lifecycle_status,
                       c.confidence AS confidence
                """,
                cid=claim_id,
                tid=tenant_id,
            ).single()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

            # Logical relations sortantes (9 types V2)
            outgoing = session.run(
                """
                MATCH (c:Claim {claim_id: $cid, tenant_id: $tid})
                      -[r:LOGICAL_RELATION]->(other:Claim)
                WHERE coalesce(r.legacy, false) = false
                RETURN other.claim_id AS target_claim_id,
                       other.doc_id AS target_doc_id,
                       (coalesce(other.text, ''))[..200] AS target_text_preview,
                       r.type AS relation_type,
                       coalesce(r.confidence, 0.0) AS confidence,
                       r.reasoning AS reasoning
                ORDER BY confidence DESC
                LIMIT 20
                """,
                cid=claim_id,
                tid=tenant_id,
            ).data()

            # Logical relations entrantes
            incoming = session.run(
                """
                MATCH (other:Claim)
                      -[r:LOGICAL_RELATION]->(c:Claim {claim_id: $cid, tenant_id: $tid})
                WHERE coalesce(r.legacy, false) = false
                RETURN other.claim_id AS source_claim_id,
                       other.doc_id AS source_doc_id,
                       (coalesce(other.text, ''))[..200] AS source_text_preview,
                       r.type AS relation_type,
                       coalesce(r.confidence, 0.0) AS confidence,
                       r.reasoning AS reasoning
                ORDER BY confidence DESC
                LIMIT 20
                """,
                cid=claim_id,
                tid=tenant_id,
            ).data()

            # Facets
            facets = session.run(
                """
                MATCH (c:Claim {claim_id: $cid, tenant_id: $tid})
                      -[bf:BELONGS_TO_FACET]->(f:Facet)
                RETURN f.facet_name AS name,
                       coalesce(bf.confidence, 0.0) AS confidence,
                       coalesce(bf.promotion_level, '') AS level
                ORDER BY confidence DESC
                LIMIT 10
                """,
                cid=claim_id,
                tid=tenant_id,
            ).data()

        return {
            "claim_id": row["claim_id"],
            "doc_id": row["doc_id"],
            "text": row["text"],
            "passage_text": row["passage_text"],
            "publication_date": row["publication_date"],
            "release_id": row.get("release_id"),
            "temporal": row.get("temporal"),
            "lifecycle_status": row.get("lifecycle_status"),
            "confidence": row.get("confidence"),
            "logical_outgoing": outgoing,
            "logical_incoming": incoming,
            "facets": facets,
        }
    finally:
        driver.close()


@router.get("/doc_detail/{doc_id}")
def doc_detail(doc_id: str) -> dict:
    """Drill-down P2.4 — infos détaillées d'un doc + ses LIFECYCLE_RELATION.

    Retourne :
    - metadata du DocumentContext (publication_date, applicability_frame, etc.)
    - lifecycle_outgoing : relations Doc→Doc sortantes (ce doc en supersede d'autres)
    - lifecycle_incoming : relations Doc→Doc entrantes (autres docs qui referencement celui-ci)
    - n_claims : count des claims du doc
    - n_conflicts : count des CONFLICT impliquant un claim de ce doc
    """
    settings = get_settings()
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    tenant_id = os.getenv("TENANT_ID", "default")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        with driver.session() as session:
            # Metadata du doc
            meta_row = session.run(
                """
                MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
                RETURN dc.doc_id AS doc_id,
                       dc.primary_subject AS primary_subject,
                       dc.publication_date AS publication_date,
                       dc.lifecycle_status AS lifecycle_status,
                       dc.language AS language,
                       dc.applicability_frame_v2_json AS af2_json
                """,
                doc_id=doc_id,
                tenant_id=tenant_id,
            ).single()

            if meta_row is None:
                raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

            # Lifecycle relations sortantes
            outgoing = session.run(
                """
                MATCH (src:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
                      -[r:LIFECYCLE_RELATION]->(tgt:DocumentContext)
                RETURN tgt.doc_id AS target,
                       r.type AS type,
                       r.confidence AS confidence,
                       r.evidence_quote AS evidence_quote
                ORDER BY r.confidence DESC
                """,
                doc_id=doc_id,
                tenant_id=tenant_id,
            ).data()

            # Lifecycle relations entrantes
            incoming = session.run(
                """
                MATCH (src:DocumentContext)
                      -[r:LIFECYCLE_RELATION]->(tgt:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
                RETURN src.doc_id AS source,
                       r.type AS type,
                       r.confidence AS confidence,
                       r.evidence_quote AS evidence_quote
                ORDER BY r.confidence DESC
                """,
                doc_id=doc_id,
                tenant_id=tenant_id,
            ).data()

            # Counts
            counts = session.run(
                """
                MATCH (c:Claim {doc_id: $doc_id, tenant_id: $tenant_id})
                WITH count(c) AS n_claims
                MATCH (a:Claim {doc_id: $doc_id, tenant_id: $tenant_id})
                      -[r:LOGICAL_RELATION {type: 'CONFLICT'}]-(:Claim)
                WHERE coalesce(r.legacy, false) = false
                RETURN n_claims, count(DISTINCT r) AS n_conflicts
                """,
                doc_id=doc_id,
                tenant_id=tenant_id,
            ).single()

        return {
            "doc_id": meta_row["doc_id"],
            "primary_subject": meta_row["primary_subject"],
            "publication_date": meta_row["publication_date"],
            "lifecycle_status": meta_row["lifecycle_status"],
            "language": meta_row["language"],
            "applicability_frame_v2_json": meta_row["af2_json"],
            "lifecycle_outgoing": outgoing,
            "lifecycle_incoming": incoming,
            "n_claims": counts["n_claims"] if counts else 0,
            "n_conflicts": counts["n_conflicts"] if counts else 0,
        }
    finally:
        driver.close()
