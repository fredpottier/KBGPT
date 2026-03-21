"""
Router Corpus Intelligence — Heatmap + Bubble Chart + Audit + Contradictions.

Endpoints lecture seule exploitant le KG existant pour des vues analytiques.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from knowbase.api.dependencies import get_tenant_id

logger = logging.getLogger("[OSMOSE] corpus_intelligence")

router = APIRouter(prefix="/corpus-intelligence", tags=["Corpus Intelligence"])


# ── Heatmap : entites x documents ──────────────────────────────────────


@router.get("/heatmap")
async def get_heatmap(
    top_entities: int = Query(default=20, ge=5, le=50),
    top_docs: int = Query(default=15, ge=5, le=30),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Matrice entites x documents avec densite de claims."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    client = get_neo4j_client()

    # Charger la stoplist du domain pack actif
    entity_stoplist = _load_entity_stoplist(tenant_id)

    with client.driver.session() as session:
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
            WHERE e._hygiene_status IS NULL
              AND NOT e.entity_type IN ['actor', 'other']
              AND size(e.name) >= 4 AND size(e.name) <= 60
            WITH e, c.doc_id AS doc, count(c) AS cnt
            WITH e, sum(cnt) AS total, collect({doc: doc, cnt: cnt}) AS docs
            ORDER BY total DESC LIMIT $top_entities
            OPTIONAL MATCH (e)-[:SAME_CANON_AS]->(ce:CanonicalEntity)
            WITH coalesce(ce.canonical_entity_id, e.entity_id) AS group_key,
                 e, total, docs
            ORDER BY total DESC
            WITH group_key, head(collect({entity: e, total: total, docs: docs})) AS best
            WITH best.entity AS e, best.total AS total, best.docs AS docs
            ORDER BY total DESC
            UNWIND docs AS d
            RETURN e.name AS entity, d.doc AS doc_id, d.cnt AS claims, total
            ORDER BY total DESC, d.cnt DESC
            """,
            tid=tenant_id,
            top_entities=top_entities * 2,  # marge pour filtrage Python
        )

        # Construire la matrice
        entity_order = []
        entity_set = set()
        doc_counts: Dict[str, int] = {}
        raw_data: List[Dict[str, Any]] = []

        for r in result:
            name = r["entity"]
            if name.lower() in entity_stoplist:
                continue
            if len(name.split()) > 4:
                continue

            if name not in entity_set:
                if len(entity_order) >= top_entities:
                    continue
                entity_order.append(name)
                entity_set.add(name)

            doc_id = r["doc_id"]
            doc_counts[doc_id] = doc_counts.get(doc_id, 0) + r["claims"]
            raw_data.append({
                "entity": name,
                "doc_id": doc_id,
                "claims": r["claims"],
            })

    # Top documents par total de claims
    sorted_docs = sorted(doc_counts.items(), key=lambda x: x[1], reverse=True)
    doc_order = [d[0] for d in sorted_docs[:top_docs]]
    doc_set = set(doc_order)

    # Construire la matrice (entite_idx, doc_idx) → claims
    matrix = []
    for entry in raw_data:
        if entry["entity"] in entity_set and entry["doc_id"] in doc_set:
            matrix.append({
                "entity": entry["entity"],
                "doc_id": entry["doc_id"],
                "claims": entry["claims"],
            })

    # Labels courts pour les documents
    doc_labels = {}
    for doc_id in doc_order:
        label = doc_id
        # Extraire un nom court depuis le doc_id
        if "_" in label:
            parts = label.split("_")
            # Retirer le hash final
            if len(parts[-1]) >= 8 and all(c in "0123456789abcdef" for c in parts[-1]):
                parts = parts[:-1]
            # Retirer le prefixe PMC ou TF
            if parts[0].startswith("PMC"):
                parts[0] = parts[0][3:]  # garder le numero
            label = " ".join(parts[:6]).replace("_", " ").title()
            if len(label) > 50:
                label = label[:47] + "..."
        doc_labels[doc_id] = label

    return {
        "entities": entity_order,
        "documents": [{"doc_id": d, "label": doc_labels.get(d, d)} for d in doc_order],
        "matrix": matrix,
        "max_value": max((m["claims"] for m in matrix), default=0),
    }


# ── Bubble Chart : couverture vs contradictions vs importance ──────────


@router.get("/bubble")
async def get_bubble(
    min_claims: int = Query(default=10, ge=1),
    limit: int = Query(default=30, ge=10, le=100),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Bubble chart : chaque concept = couverture (X) vs contradictions (Y) vs importance (taille)."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    client = get_neo4j_client()
    entity_stoplist = _load_entity_stoplist(tenant_id)

    with client.driver.session() as session:
        result = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})
            WHERE e._hygiene_status IS NULL
              AND NOT e.entity_type IN ['actor', 'other']
              AND size(e.name) >= 4 AND size(e.name) <= 60
            OPTIONAL MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e)
            WITH e, count(DISTINCT c) AS claims, count(DISTINCT c.doc_id) AS docs
            WHERE claims >= $min_claims
            OPTIONAL MATCH (e)-[:SAME_CANON_AS]->(ce:CanonicalEntity)
            WITH coalesce(ce.canonical_entity_id, e.entity_id) AS group_key,
                 e, claims, docs
            ORDER BY claims DESC
            WITH group_key, head(collect(e)) AS best_entity,
                 sum(claims) AS total_claims, max(docs) AS max_docs
            OPTIONAL MATCH (c1:Claim)-[:ABOUT]->(best_entity),
                          (c1)-[r:CONTRADICTS]-(c2:Claim)
            WITH best_entity, total_claims, max_docs,
                 count(DISTINCT r) / 2 AS contradictions
            OPTIONAL MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})
                          -[:ABOUT]->(best_entity)
            RETURN best_entity.name AS name,
                   total_claims AS claims,
                   max_docs AS docs,
                   contradictions,
                   wa.slug IS NOT NULL AS has_article,
                   wa.slug AS slug
            ORDER BY total_claims DESC
            LIMIT $limit_val
            """,
            tid=tenant_id,
            min_claims=min_claims,
            limit_val=limit * 2,  # marge pour filtrage
        )

        bubbles = []
        for r in result:
            name = r["name"]
            if name.lower() in entity_stoplist:
                continue
            if len(name.split()) > 4:
                continue
            if len(bubbles) >= limit:
                break

            bubbles.append({
                "name": name,
                "claims": r["claims"],
                "docs": r["docs"],
                "contradictions": r["contradictions"],
                "has_article": bool(r["has_article"]),
                "slug": r["slug"],
            })

    return {"bubbles": bubbles}


# ── Corpus Audit Report ────────────────────────────────────────────────


@router.get("/audit")
async def get_corpus_audit(
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Rapport d'audit du corpus : sante, contradictions, gaps, recommandations."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.wiki.persistence import WikiArticlePersister

    client = get_neo4j_client()
    persister = WikiArticlePersister(client.driver)

    # Stats de base
    home_data = persister.get_home_data(tenant_id)
    stats = home_data["corpus_stats"]
    blind_spots = home_data.get("blind_spots", [])

    with client.driver.session() as session:
        # Top contradictions avec texte complet
        contra_result = session.run(
            """
            MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS]-(c2:Claim)
            WHERE c1.claim_id < c2.claim_id
            OPTIONAL MATCH (c1)-[:ABOUT]->(e1:Entity)
            OPTIONAL MATCH (c2)-[:ABOUT]->(e2:Entity)
            WITH c1, c2, r,
                 collect(DISTINCT e1.name)[..3] AS entities1,
                 collect(DISTINCT e2.name)[..3] AS entities2
            RETURN c1.text AS text1, c1.doc_id AS doc1, c1.verbatim_quote AS verbatim1,
                   c2.text AS text2, c2.doc_id AS doc2, c2.verbatim_quote AS verbatim2,
                   r.tension_nature AS nature, r.tension_level AS level,
                   entities1, entities2
            ORDER BY CASE r.tension_level
                WHEN 'hard' THEN 0 WHEN 'soft' THEN 1 ELSE 2 END,
                r.tension_nature
            LIMIT 10
            """,
            tid=tenant_id,
        )
        top_contradictions = [
            {
                "claim1": {"text": r["text1"], "doc_id": r["doc1"], "verbatim": r["verbatim1"]},
                "claim2": {"text": r["text2"], "doc_id": r["doc2"], "verbatim": r["verbatim2"]},
                "tension_nature": r["nature"] or "unknown",
                "tension_level": r["level"] or "unknown",
                "entities": list(set((r["entities1"] or []) + (r["entities2"] or []))),
            }
            for r in contra_result
        ]

        # Concepts avec le plus de contradictions
        hotspot_result = session.run(
            """
            MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS]-(c2:Claim),
                  (c1)-[:ABOUT]->(e:Entity)
            WHERE e._hygiene_status IS NULL
            WITH e.name AS name, count(DISTINCT r) AS contra_count
            WHERE contra_count >= 2
            RETURN name, contra_count
            ORDER BY contra_count DESC LIMIT 8
            """,
            tid=tenant_id,
        )
        contradiction_hotspots = [
            {"name": r["name"], "contradictions": r["contra_count"]}
            for r in hotspot_result
        ]

        # Distribution des types de contradictions + totaux
        type_result = session.run(
            """
            MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS]-(c2:Claim)
            WHERE c1.claim_id < c2.claim_id
            RETURN coalesce(r.tension_nature, 'unclassified') AS nature,
                   coalesce(r.tension_level, 'unknown') AS level,
                   count(*) AS cnt
            ORDER BY cnt DESC
            """,
            tid=tenant_id,
        )
        contradiction_types = []
        nature_counts: dict = {}
        total_contradictions = 0
        total_hard = 0
        for r in type_result:
            nature_counts[r["nature"]] = nature_counts.get(r["nature"], 0) + r["cnt"]
            total_contradictions += r["cnt"]
            if r["level"] == "hard":
                total_hard += r["cnt"]
        for nature, cnt in sorted(nature_counts.items(), key=lambda x: x[1], reverse=True):
            contradiction_types.append({"type": nature, "count": cnt})

        # Concepts sans article (filtré par stoplist domain pack)
        tier1_gaps = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})
            WHERE e._hygiene_status IS NULL
              AND NOT e.entity_type IN ['actor', 'other']
              AND size(e.name) >= 4 AND size(e.name) <= 60
            OPTIONAL MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e)
            WITH e, count(DISTINCT c) AS claims, count(DISTINCT c.doc_id) AS docs
            WHERE claims >= 20 AND docs >= 3
            AND NOT EXISTS {
                MATCH (wa:WikiArticle {tenant_id: $tid})-[:ABOUT]->(e)
            }
            RETURN e.name AS name, claims, docs
            ORDER BY claims DESC LIMIT 15
            """,
            tid=tenant_id,
        )
        entity_stoplist = _load_entity_stoplist(tenant_id)
        articles_to_write = []
        for r in tier1_gaps:
            name = r["name"]
            if name.lower() in entity_stoplist:
                continue
            if len(name.split()) > 4:
                continue
            articles_to_write.append(
                {"name": name, "claims": r["claims"], "docs": r["docs"]}
            )
            if len(articles_to_write) >= 5:
                break

        # Compter claims avec verbatim (traçabilité)
        verbatim_result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WITH count(c) AS total,
                 sum(CASE WHEN c.verbatim_quote IS NOT NULL AND c.verbatim_quote <> '' THEN 1 ELSE 0 END) AS with_verbatim
            RETURN total, with_verbatim
            """,
            tid=tenant_id,
        ).single()
        total_claims = verbatim_result["total"] or 1
        claims_with_verbatim = verbatim_result["with_verbatim"] or 0

        # Moyenne docs par entité (diversité des sources)
        diversity_result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
            WHERE e._hygiene_status IS NULL
            WITH e, count(DISTINCT c.doc_id) AS doc_count
            RETURN avg(doc_count) AS avg_docs_per_entity
            """,
            tid=tenant_id,
        ).single()
        avg_docs_per_entity = diversity_result["avg_docs_per_entity"] or 0

    # Score de qualité du KG (0-100)
    # 4 critères objectifs et explicables

    # 1. Traçabilité : % de claims avec verbatim quote (max 30 pts)
    traceability_pct = (claims_with_verbatim / total_claims * 100) if total_claims > 0 else 0
    traceability_score = min(round(traceability_pct * 0.3), 30)

    # 2. Diversité des sources : avg docs par concept (max 25 pts)
    # 1 doc/concept = 5pts, 3+ docs/concept = 25pts
    diversity_score = min(round(avg_docs_per_entity * 8), 25)

    # 3. Cohérence : score POSITIF basé sur le taux de cohérence (max 20 pts)
    # Plus le taux de contradictions dures est bas, plus le score est élevé
    hard_count = total_hard
    hard_rate = (hard_count / total_claims * 100) if total_claims > 0 else 0
    coherence_rate = 100 - hard_rate  # % de claims non contradictoires
    # 100% cohérence → 20pts, 98% → 16pts, 95% → 10pts, <90% → 0pts
    if coherence_rate >= 99.5:
        coherence_score = 20
    elif coherence_rate >= 98:
        coherence_score = round(16 + (coherence_rate - 98) * 2.67)  # 98→16, 99.5→20
    elif coherence_rate >= 95:
        coherence_score = round(10 + (coherence_rate - 95) * 2)  # 95→10, 98→16
    else:
        coherence_score = max(0, round(coherence_rate - 90) * 2)  # 90→0, 95→10

    # 4. Richesse : nombre d'entités identifiées par document (max 25 pts)
    entities_per_doc = stats["total_entities"] / max(stats["total_documents"], 1)
    richness_score = min(round(entities_per_doc * 0.5), 25)

    health_score = max(0, min(100, round(
        traceability_score + diversity_score + richness_score + coherence_score
    )))

    score_details = [
        {"label": "Tracabilite", "description": f"{traceability_pct:.0f}% des claims ont une citation verbatim", "score": traceability_score, "max": 30},
        {"label": "Diversite des sources", "description": f"{avg_docs_per_entity:.1f} documents par concept en moyenne", "score": diversity_score, "max": 25},
        {"label": "Richesse", "description": f"{entities_per_doc:.0f} concepts identifies par document", "score": richness_score, "max": 25},
        {"label": "Coherence", "description": f"{coherence_rate:.1f}% de coherence ({hard_count} contradiction(s) dure(s) sur {total_claims} claims)", "score": coherence_score, "max": 20},
    ]

    return {
        "health_score": health_score,
        "score_details": score_details,
        "stats": stats,
        "total_contradictions": total_contradictions,
        "total_hard_contradictions": total_hard,
        "top_contradictions": top_contradictions,
        "contradiction_hotspots": contradiction_hotspots,
        "contradiction_types": contradiction_types,
        "blind_spots": blind_spots,
        "articles_to_write": articles_to_write,
    }


# ── Contradiction Explorer ─────────────────────────────────────────────


@router.get("/contradictions")
async def get_contradictions(
    nature: Optional[str] = Query(default=None),
    level: Optional[str] = Query(default=None),
    entity: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Liste paginee des contradictions avec filtres."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    client = get_neo4j_client()

    # Construire les filtres dynamiques
    filters = ["c1.claim_id < c2.claim_id"]
    params: Dict[str, Any] = {"tid": tenant_id, "limit": limit, "offset": offset}

    if nature:
        filters.append("r.tension_nature = $nature")
        params["nature"] = nature
    if level:
        filters.append("r.tension_level = $level")
        params["level"] = level

    entity_filter = ""
    if entity:
        entity_filter = """
        WITH c1, c2, r
        MATCH (c1)-[:ABOUT]->(e:Entity)
        WHERE toLower(e.name) CONTAINS toLower($entity_search)
        """
        params["entity_search"] = entity

    where_clause = " AND ".join(filters)

    with client.driver.session() as session:
        # Total count
        count_query = f"""
        MATCH (c1:Claim {{tenant_id: $tid}})-[r:CONTRADICTS]-(c2:Claim)
        WHERE {where_clause}
        {entity_filter}
        RETURN count(*) AS total
        """
        total = session.run(count_query, **params).single()["total"]

        # Données paginées
        data_query = f"""
        MATCH (c1:Claim {{tenant_id: $tid}})-[r:CONTRADICTS]-(c2:Claim)
        WHERE {where_clause}
        {entity_filter}
        OPTIONAL MATCH (c1)-[:ABOUT]->(e1:Entity)
        OPTIONAL MATCH (c2)-[:ABOUT]->(e2:Entity)
        WITH c1, c2, r,
             collect(DISTINCT e1.name)[..5] AS entities1,
             collect(DISTINCT e2.name)[..5] AS entities2
        RETURN c1.claim_id AS id1, c1.text AS text1, c1.doc_id AS doc1,
               c1.verbatim_quote AS verbatim1, c1.claim_type AS type1,
               c1.page_no AS page1,
               c2.claim_id AS id2, c2.text AS text2, c2.doc_id AS doc2,
               c2.verbatim_quote AS verbatim2, c2.claim_type AS type2,
               c2.page_no AS page2,
               r.tension_nature AS nature, r.tension_level AS level,
               entities1, entities2
        ORDER BY CASE r.tension_level
            WHEN 'hard' THEN 0 WHEN 'soft' THEN 1 ELSE 2 END
        SKIP $offset LIMIT $limit
        """
        result = session.run(data_query, **params)

        contradictions = []
        for r in result:
            all_entities = list(set((r["entities1"] or []) + (r["entities2"] or [])))
            contradictions.append({
                "claim1": {
                    "id": r["id1"],
                    "text": r["text1"],
                    "doc_id": r["doc1"],
                    "verbatim": r["verbatim1"],
                    "claim_type": r["type1"] or "FACTUAL",
                    "page": r["page1"],
                },
                "claim2": {
                    "id": r["id2"],
                    "text": r["text2"],
                    "doc_id": r["doc2"],
                    "verbatim": r["verbatim2"],
                    "claim_type": r["type2"] or "FACTUAL",
                    "page": r["page2"],
                },
                "tension_nature": r["nature"] or "unclassified",
                "tension_level": r["level"] or "unknown",
                "entities": all_entities,
            })

        # Stats par type
        stats_result = session.run(
            """
            MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS]-(c2:Claim)
            WHERE c1.claim_id < c2.claim_id
            RETURN coalesce(r.tension_nature, 'unclassified') AS nature,
                   coalesce(r.tension_level, 'unknown') AS level,
                   count(*) AS cnt
            """,
            tid=tenant_id,
        )
        stats_by_nature = {}
        stats_by_level = {}
        for r in stats_result:
            stats_by_nature[r["nature"]] = stats_by_nature.get(r["nature"], 0) + r["cnt"]
            stats_by_level[r["level"]] = stats_by_level.get(r["level"], 0) + r["cnt"]

    return {
        "contradictions": contradictions,
        "total": total,
        "limit": limit,
        "offset": offset,
        "stats": {
            "by_nature": stats_by_nature,
            "by_level": stats_by_level,
            "total": total,
        },
    }


# ── Helper ─────────────────────────────────────────────────────────────


def _load_entity_stoplist(tenant_id: str) -> set:
    """Charge la stoplist depuis les domain packs actifs."""
    stoplist: set = set()
    try:
        from knowbase.domain_packs.registry import get_pack_registry

        registry = get_pack_registry()
        for pack in registry.get_active_packs(tenant_id):
            pack_stoplist = pack.get_entity_stoplist()
            stoplist.update(s.lower() for s in pack_stoplist if isinstance(s, str))
    except Exception:
        pass
    return stoplist
