"""
S3.E — Mini-runtime Relations Explorer (V3.3).

Endpoints admin minimalistes pour explorer les LOGICAL_RELATION typées V3.3
sans attendre le runtime complet R1+R2.

- GET /api/admin/relations/stats : distribution des 12 types + counts globaux
- GET /api/admin/relations/by_type/{type} : top N relations par type avec drill-down
- GET /api/admin/relations/conflicts : preview CONFLICT_RISK (true contradictions only)
- GET /api/admin/relations/pair/{a_id}/{b_id} : détail d'une paire spécifique

Format kg_trust brut affiché : confidence × strength_weight (sans Trust Evaluator complet).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import GraphDatabase
from pydantic import BaseModel, Field

from knowbase.api.dependencies import get_tenant_id

logger = logging.getLogger("[OSMOSE] relations_explorer")

router = APIRouter(prefix="/admin/relations", tags=["relations_explorer"])


# ============================================================================
# Pydantic models
# ============================================================================

class RelationTypeStat(BaseModel):
    """Stat par type de relation."""

    type: str
    count: int
    contradictions: int = 0
    avg_confidence: float = 0.0
    sample_strong: int = 0
    sample_weak: int = 0
    sample_uncertain: int = 0


class RelationsStatsResponse(BaseModel):
    """Stats globales sur les LOGICAL_RELATION V3.3."""

    total: int
    by_type: list[RelationTypeStat]
    legacy_remaining: int = Field(description="Edges legacy CONTRADICTS/REFINES/QUALIFIES marquées legacy=true")
    true_contradictions: int = Field(description="Type=CONFLICT + is_contradiction=true + confidence ≥ 0.85")


class RelationDetail(BaseModel):
    """Détail d'une relation pour drill-down."""

    a_claim_id: str
    a_text: str
    a_doc_id: str
    a_publication_date: Optional[str] = None
    a_validity_start: Optional[str] = None
    b_claim_id: str
    b_text: str
    b_doc_id: str
    b_publication_date: Optional[str] = None
    b_validity_start: Optional[str] = None
    type: str
    strength: str
    confidence: float
    is_contradiction: bool
    contradiction_reason: Optional[str] = None
    scope_alignment: Optional[str] = None
    temporal_relation: Optional[str] = None
    reasoning: str
    extracted_at: Optional[str] = None
    kg_trust: float = Field(description="Score brut : confidence × strength_weight")


class RelationsByTypeResponse(BaseModel):
    """Liste de relations pour un type donné."""

    type: str
    total: int
    relations: list[RelationDetail]


# ============================================================================
# Helpers
# ============================================================================

STRENGTH_WEIGHTS = {"STRONG": 1.0, "WEAK": 0.6, "UNCERTAIN": 0.3}


def _compute_kg_trust(confidence: Optional[float], strength: Optional[str]) -> float:
    """Calcul brut kg_trust = confidence × strength_weight."""
    conf = float(confidence) if confidence is not None else 0.0
    weight = STRENGTH_WEIGHTS.get(strength, 0.5)
    return round(conf * weight, 3)


def _get_neo4j_driver():
    import os
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/stats", response_model=RelationsStatsResponse)
async def get_stats(tenant_id: str = Depends(get_tenant_id)) -> RelationsStatsResponse:
    """
    Distribution globale des LOGICAL_RELATION V3.3.

    Retourne le count par type + total + nombre de vraies contradictions
    (CONFLICT avec is_contradiction=true et confidence ≥ 0.85).
    """
    driver = _get_neo4j_driver()
    try:
        with driver.session() as s:
            # Distribution par type
            rows = s.run("""
                MATCH (a:Claim {tenant_id: $t})-[r:LOGICAL_RELATION]->(b:Claim {tenant_id: $t})
                WHERE coalesce(r.legacy, false) = false
                RETURN r.type AS type,
                       count(r) AS count,
                       sum(CASE WHEN r.is_contradiction = true THEN 1 ELSE 0 END) AS contradictions,
                       avg(r.confidence) AS avg_conf,
                       sum(CASE WHEN r.strength = 'STRONG' THEN 1 ELSE 0 END) AS strong,
                       sum(CASE WHEN r.strength = 'WEAK' THEN 1 ELSE 0 END) AS weak,
                       sum(CASE WHEN r.strength = 'UNCERTAIN' THEN 1 ELSE 0 END) AS uncertain
                ORDER BY count DESC
            """, t=tenant_id).data()

            by_type = [
                RelationTypeStat(
                    type=r["type"],
                    count=r["count"],
                    contradictions=r["contradictions"] or 0,
                    avg_confidence=round(float(r["avg_conf"] or 0), 3),
                    sample_strong=r["strong"] or 0,
                    sample_weak=r["weak"] or 0,
                    sample_uncertain=r["uncertain"] or 0,
                )
                for r in rows
            ]

            total = sum(t.count for t in by_type)

            # Vraies contradictions
            true_contra = s.run("""
                MATCH ()-[r:LOGICAL_RELATION {type: 'CONFLICT'}]->()
                WHERE coalesce(r.legacy, false) = false
                  AND r.is_contradiction = true
                  AND r.confidence >= 0.85
                RETURN count(r) AS n
            """).single()["n"]

            # Legacy remaining
            legacy = s.run("""
                MATCH ()-[r:CONTRADICTS|REFINES|QUALIFIES]->()
                WHERE r.legacy = true
                RETURN count(r) AS n
            """).single()["n"]

            return RelationsStatsResponse(
                total=total,
                by_type=by_type,
                legacy_remaining=legacy,
                true_contradictions=true_contra,
            )
    finally:
        driver.close()


@router.get("/by_type/{relation_type}", response_model=RelationsByTypeResponse)
async def get_by_type(
    relation_type: str,
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=20, ge=1, le=200),
    confidence_min: float = Query(default=0.0, ge=0.0, le=1.0),
    contradictions_only: bool = Query(default=False, description="Filter is_contradiction=true only"),
) -> RelationsByTypeResponse:
    """
    Drill-down sur les relations d'un type donné, triées par confidence DESC.

    Args:
        relation_type: SUBSET, SUPERSET, EQUIVALENT, OVERLAP, DISJOINT, CONFLICT,
                       EXCEPTION, DEFINITION_OF, SUPERSEDES, EVOLVES_FROM, REAFFIRMS, UNRELATED
        limit: nombre max de résultats
        confidence_min: filtre confidence minimum
        contradictions_only: ne retourner que les is_contradiction=true
    """
    driver = _get_neo4j_driver()
    try:
        with driver.session() as s:
            extra_filter = ""
            if contradictions_only:
                extra_filter = " AND r.is_contradiction = true"

            rows = s.run(f"""
                MATCH (a:Claim {{tenant_id: $t}})-[r:LOGICAL_RELATION]->(b:Claim {{tenant_id: $t}})
                WHERE r.type = $type
                  AND coalesce(r.legacy, false) = false
                  AND r.confidence >= $conf_min
                  {extra_filter}
                RETURN
                    a.claim_id AS a_id, a.text AS a_text, a.doc_id AS a_doc,
                    a.publication_date AS a_pub, a.validity_start AS a_vstart,
                    b.claim_id AS b_id, b.text AS b_text, b.doc_id AS b_doc,
                    b.publication_date AS b_pub, b.validity_start AS b_vstart,
                    r.type AS type, r.strength AS strength, r.confidence AS confidence,
                    r.is_contradiction AS is_contradiction,
                    r.contradiction_reason AS contradiction_reason,
                    r.scope_alignment AS scope_alignment,
                    r.temporal_relation AS temporal_relation,
                    r.reasoning AS reasoning,
                    r.extracted_at AS extracted_at
                ORDER BY r.confidence DESC, r.strength DESC
                LIMIT $lim
            """, t=tenant_id, type=relation_type, conf_min=confidence_min, lim=limit).data()

            # Total count séparément
            total = s.run(f"""
                MATCH ()-[r:LOGICAL_RELATION]->()
                WHERE r.type = $type
                  AND coalesce(r.legacy, false) = false
                  AND r.confidence >= $conf_min
                  {extra_filter}
                RETURN count(r) AS n
            """, type=relation_type, conf_min=confidence_min).single()["n"]

            relations = [
                RelationDetail(
                    a_claim_id=r["a_id"],
                    a_text=r["a_text"] or "",
                    a_doc_id=r["a_doc"],
                    a_publication_date=r["a_pub"],
                    a_validity_start=r["a_vstart"],
                    b_claim_id=r["b_id"],
                    b_text=r["b_text"] or "",
                    b_doc_id=r["b_doc"],
                    b_publication_date=r["b_pub"],
                    b_validity_start=r["b_vstart"],
                    type=r["type"],
                    strength=r["strength"] or "STRONG",
                    confidence=float(r["confidence"] or 0),
                    is_contradiction=r["is_contradiction"] or False,
                    contradiction_reason=r["contradiction_reason"],
                    scope_alignment=r["scope_alignment"],
                    temporal_relation=r["temporal_relation"],
                    reasoning=r["reasoning"] or "",
                    extracted_at=r["extracted_at"],
                    kg_trust=_compute_kg_trust(r["confidence"], r["strength"]),
                )
                for r in rows
            ]

            return RelationsByTypeResponse(type=relation_type, total=total, relations=relations)
    finally:
        driver.close()


@router.get("/conflicts", response_model=RelationsByTypeResponse)
async def get_conflicts(
    tenant_id: str = Depends(get_tenant_id),
    confidence_min: float = Query(default=0.85, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=500),
) -> RelationsByTypeResponse:
    """
    Mini-CONFLICT_RISK preview — vraies contradictions uniquement.

    Filtre : type=CONFLICT + is_contradiction=true + confidence ≥ confidence_min.
    """
    return await get_by_type(
        relation_type="CONFLICT",
        tenant_id=tenant_id,
        limit=limit,
        confidence_min=confidence_min,
        contradictions_only=True,
    )


@router.get("/pair/{a_claim_id}/{b_claim_id}", response_model=RelationDetail)
async def get_pair_detail(
    a_claim_id: str,
    b_claim_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> RelationDetail:
    """Détail d'une paire spécifique (utile pour debugging + golden set annotation)."""
    driver = _get_neo4j_driver()
    try:
        with driver.session() as s:
            row = s.run("""
                MATCH (a:Claim {claim_id: $aid, tenant_id: $t})-[r:LOGICAL_RELATION]-(b:Claim {claim_id: $bid, tenant_id: $t})
                WHERE coalesce(r.legacy, false) = false
                RETURN
                    a.claim_id AS a_id, a.text AS a_text, a.doc_id AS a_doc,
                    a.publication_date AS a_pub, a.validity_start AS a_vstart,
                    b.claim_id AS b_id, b.text AS b_text, b.doc_id AS b_doc,
                    b.publication_date AS b_pub, b.validity_start AS b_vstart,
                    r.type AS type, r.strength AS strength, r.confidence AS confidence,
                    r.is_contradiction AS is_contradiction,
                    r.contradiction_reason AS contradiction_reason,
                    r.scope_alignment AS scope_alignment,
                    r.temporal_relation AS temporal_relation,
                    r.reasoning AS reasoning,
                    r.extracted_at AS extracted_at
                LIMIT 1
            """, aid=a_claim_id, bid=b_claim_id, t=tenant_id).single()

            if not row:
                raise HTTPException(status_code=404, detail=f"No LOGICAL_RELATION between {a_claim_id} and {b_claim_id}")

            return RelationDetail(
                a_claim_id=row["a_id"],
                a_text=row["a_text"] or "",
                a_doc_id=row["a_doc"],
                a_publication_date=row["a_pub"],
                a_validity_start=row["a_vstart"],
                b_claim_id=row["b_id"],
                b_text=row["b_text"] or "",
                b_doc_id=row["b_doc"],
                b_publication_date=row["b_pub"],
                b_validity_start=row["b_vstart"],
                type=row["type"],
                strength=row["strength"] or "STRONG",
                confidence=float(row["confidence"] or 0),
                is_contradiction=row["is_contradiction"] or False,
                contradiction_reason=row["contradiction_reason"],
                scope_alignment=row["scope_alignment"],
                temporal_relation=row["temporal_relation"],
                reasoning=row["reasoning"] or "",
                extracted_at=row["extracted_at"],
                kg_trust=_compute_kg_trust(row["confidence"], row["strength"]),
            )
    finally:
        driver.close()


__all__ = ["router"]
