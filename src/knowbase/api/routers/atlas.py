"""
Atlas API — sert le contenu de l'Atlas narratif.

Endpoints :
- GET /api/atlas/homepage   → introduction + structure (roots + themes)
- GET /api/atlas/topics     → liste des topics avec metadata
- GET /api/atlas/topic/{id} → article complet (sections + liens)
- GET /api/atlas/themes     → axes thematiques transversaux
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/atlas", tags=["atlas"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class AtlasSection(BaseModel):
    perspective_id: str
    title: str
    content: str
    claim_count: int = 0


class AtlasTopic(BaseModel):
    topic_id: str
    title: str
    executive_summary: str = ""
    subjects: List[str] = []
    claim_count: int = 0
    perspective_count: int = 0
    reading_order: int = 0
    atlas_root: str = ""


class AtlasArticle(BaseModel):
    topic_id: str
    title: str
    executive_summary: str = ""
    sections: List[AtlasSection] = []
    related_topics: List[Dict[str, Any]] = []
    total_claims: int = 0
    total_docs: int = 0
    generated_at: str = ""


class AtlasRoot(BaseModel):
    root_id: str
    name: str
    description: str = ""
    topics: List[AtlasTopic] = []
    claim_count: int = 0


class AtlasDomain(BaseModel):
    """Niveau hiérarchique au-dessus des AtlasRoots (Domain → Root → Topic)."""
    domain_id: str
    name: str
    description: str = ""
    claim_count: int = 0
    roots: List[AtlasRoot] = []


class AtlasTheme(BaseModel):
    theme_id: str = ""
    label: str
    description: str = ""
    claim_count: int = 0
    topic_count: int = 0
    topic_ids: List[str] = []
    topic_labels: List[str] = []


class AtlasHomepage(BaseModel):
    introduction: str = ""
    domains: List[AtlasDomain] = []
    roots: List[AtlasRoot] = []  # Conservé pour rétrocompat (vue plate)
    themes: List[AtlasTheme] = []
    total_docs: int = 0
    total_claims: int = 0
    total_topics: int = 0


class AtlasThemePerspective(BaseModel):
    perspective_id: str
    label: str
    claim_count: int = 0
    parent_topic_id: str = ""
    parent_topic_label: str = ""


class AtlasThemeDetail(BaseModel):
    theme_id: str
    label: str
    description: str = ""
    claim_count: int = 0
    topic_count: int = 0
    related_topics: List[AtlasTopic] = []
    perspectives: List[AtlasThemePerspective] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_driver():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    return get_neo4j_client().driver


def _get_tenant():
    return "default"


# ── P5.2 — POC Atlas narratif from Perspectives ──────────────────────────────


class PerspectiveTopic(BaseModel):
    """POC P5.2 : représente une Perspective V2 comme topic narratif Atlas."""

    perspective_id: str
    label: str
    description: str = ""
    subjects: List[str] = []
    facets: List[str] = []
    keywords: List[str] = []
    claim_count: int = 0
    doc_count: int = 0
    importance_score: float = 0.0


@router.get("/perspective_topics", response_model=List[PerspectiveTopic])
async def list_perspective_topics(limit: int = 100):
    """POC P5.2 — Atlas narratif basé sur les Perspectives V2 existantes.

    Au lieu de générer des nodes AtlasHomepage/AtlasRoot/NarrativeTopic via un
    pipeline complet (1-2 sem), on expose les Perspectives V2 (60 nodes Neo4j)
    comme "topics narratifs" du POC Atlas. Tri par importance_score décroissant.

    Limite : pas de structure hiérarchique (roots/themes), pas de contenu prose
    rédigé. À enrichir avec un pipeline génération en sessions dédiées.
    """
    driver = _get_driver()
    tenant = _get_tenant()
    cypher = """
    MATCH (p:Perspective)
    WHERE p.tenant_id = $tenant
    RETURN p.perspective_id AS perspective_id,
           coalesce(p.label, '') AS label,
           coalesce(p.description, '') AS description,
           coalesce(p.linked_subject_names, []) AS subjects,
           coalesce(p.dominant_facet_names, []) AS facets,
           coalesce(p.keywords, []) AS keywords,
           coalesce(p.claim_count, 0) AS claim_count,
           coalesce(p.doc_count, 0) AS doc_count,
           coalesce(p.importance_score, 0.0) AS importance_score
    ORDER BY p.importance_score DESC
    LIMIT $limit
    """
    with driver.session() as session:
        rows = session.run(cypher, tenant=tenant, limit=limit).data()
    return [
        PerspectiveTopic(
            perspective_id=row["perspective_id"],
            label=row["label"],
            description=row["description"],
            subjects=(row["subjects"] or [])[:10],
            facets=(row["facets"] or [])[:5],
            keywords=(row["keywords"] or [])[:10],
            claim_count=int(row["claim_count"]),
            doc_count=int(row["doc_count"]),
            importance_score=float(row["importance_score"]),
        )
        for row in rows
    ]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/homepage", response_model=AtlasHomepage)
async def get_homepage():
    """Homepage Atlas : introduction + structure par produit + themes."""
    driver = _get_driver()
    tenant = _get_tenant()

    homepage = AtlasHomepage()

    with driver.session() as session:
        # Introduction
        result = session.run(
            "MATCH (h:AtlasHomepage {tenant_id: $tenant}) RETURN h.introduction AS intro",
            tenant=tenant,
        )
        rec = result.single()
        if rec and rec["intro"]:
            homepage.introduction = rec["intro"]

        # Roots + their topics
        result = session.run("""
            MATCH (ar:AtlasRoot {tenant_id: $tenant})
            OPTIONAL MATCH (ar)-[hc:HAS_CHAPTER]->(nt:NarrativeTopic)
            RETURN ar.root_id AS rid, ar.canonical_name AS name,
                   coalesce(ar.description, '') AS description,
                   ar.claim_count AS claims,
                   collect({
                       topic_id: nt.topic_id, title: nt.narrative_label,
                       summary: nt.executive_summary, claims: nt.claim_count,
                       persp_count: nt.perspective_count, subjects: nt.subject_names,
                       reading_order: hc.reading_order
                   }) AS topics
            ORDER BY ar.claim_count DESC
        """, tenant=tenant)
        for rec in result:
            root_topics = []
            for t in rec["topics"]:
                if t.get("topic_id"):
                    root_topics.append(AtlasTopic(
                        topic_id=t["topic_id"], title=t["title"] or "",
                        executive_summary=t.get("summary") or "",
                        subjects=t.get("subjects") or [],
                        claim_count=t.get("claims") or 0,
                        perspective_count=t.get("persp_count") or 0,
                        reading_order=t.get("reading_order") or 0,
                        atlas_root=rec["name"],
                    ))
            root_topics.sort(key=lambda t: t.reading_order)
            homepage.roots.append(AtlasRoot(
                root_id=rec["rid"], name=rec["name"],
                description=rec.get("description") or "",
                topics=root_topics, claim_count=rec["claims"] or 0,
            ))

        # Domains — niveau hiérarchique au-dessus des Roots (Domain → Root → Topic).
        # Si aucun AtlasDomain n'est persisté, homepage.domains reste vide et le
        # frontend retombe sur la vue plate homepage.roots.
        roots_by_id = {r.root_id: r for r in homepage.roots}
        domain_rows = session.run("""
            MATCH (d:AtlasDomain {tenant_id: $tenant})
            OPTIONAL MATCH (d)-[:CONTAINS_ROOT]->(ar:AtlasRoot)
            WITH d, collect(ar.root_id) AS root_ids
            RETURN d.domain_id AS did, d.name AS name,
                   coalesce(d.description, '') AS description,
                   coalesce(d.claim_count, 0) AS claims,
                   root_ids
            ORDER BY d.claim_count DESC
        """, tenant=tenant)
        for rec in domain_rows:
            dom_roots = [roots_by_id[rid] for rid in (rec["root_ids"] or []) if rid in roots_by_id]
            homepage.domains.append(AtlasDomain(
                domain_id=rec["did"] or "",
                name=rec["name"] or "",
                description=rec["description"] or "",
                claim_count=rec["claims"] or 0,
                roots=dom_roots,
            ))

        # Stats
        homepage.total_topics = sum(len(r.topics) for r in homepage.roots)
        homepage.total_claims = session.run(
            "MATCH (c:Claim {tenant_id: $tenant}) RETURN count(c) AS cnt",
            tenant=tenant,
        ).single()["cnt"]
        homepage.total_docs = session.run(
            "MATCH (dc:DocumentContext {tenant_id: $tenant}) RETURN count(dc) AS cnt",
            tenant=tenant,
        ).single()["cnt"]

    # Themes — lis les AtlasTheme persistes (genere par generate_atlas_content.py --enrich-metadata)
    with driver.session() as session:
        result = session.run("""
            MATCH (t:AtlasTheme {tenant_id: $tenant})
            RETURN t.theme_id AS tid, t.label AS label,
                   coalesce(t.description, '') AS description,
                   coalesce(t.claim_count, 0) AS claims,
                   coalesce(t.topic_coverage, 0) AS topic_count,
                   coalesce(t.topic_ids, []) AS topic_ids,
                   coalesce(t.perspective_labels, []) AS persp_labels
            ORDER BY t.claim_count DESC
        """, tenant=tenant)
        for rec in result:
            homepage.themes.append(AtlasTheme(
                theme_id=rec["tid"] or "",
                label=rec["label"] or "",
                description=rec["description"] or "",
                claim_count=rec["claims"] or 0,
                topic_count=rec["topic_count"] or 0,
                topic_ids=list(rec["topic_ids"] or []),
                topic_labels=list(rec["persp_labels"] or [])[:5],
            ))

    # Fallback : si aucun AtlasTheme persiste, fait un quick clustering avec labels concatenes
    if not homepage.themes:
        try:
            import sys
            sys.path.insert(0, "/app")
            from scripts.detect_thematic_axes import load_perspective_embeddings, cluster_themes, label_axes_llm

            perspectives = load_perspective_embeddings(driver, tenant)
            axes = cluster_themes(perspectives, min(8, max(2, len(perspectives) // 3)))
            label_axes_llm(axes, skip_llm=True)

            for ax in axes:
                homepage.themes.append(AtlasTheme(
                    theme_id=ax.axis_id, label=ax.label,
                    claim_count=ax.claim_count,
                    topic_labels=ax.perspective_labels[:5],
                ))
        except Exception as e:
            logger.debug(f"[ATLAS] Theme fallback failed: {e}")

    return homepage


@router.get("/topics", response_model=List[AtlasTopic])
async def get_topics():
    """Liste tous les NarrativeTopics."""
    driver = _get_driver()
    tenant = _get_tenant()

    topics = []
    with driver.session() as session:
        result = session.run("""
            MATCH (nt:NarrativeTopic {tenant_id: $tenant})
            OPTIONAL MATCH (ar:AtlasRoot)-[:HAS_CHAPTER]->(nt)
            RETURN nt.topic_id AS tid, nt.narrative_label AS title,
                   nt.executive_summary AS summary, nt.subject_names AS subjects,
                   nt.claim_count AS claims, nt.perspective_count AS n_persp,
                   nt.reading_order AS ord, ar.canonical_name AS root_name
            ORDER BY nt.reading_order
        """, tenant=tenant)
        for rec in result:
            topics.append(AtlasTopic(
                topic_id=rec["tid"], title=rec["title"] or "",
                executive_summary=rec["summary"] or "",
                subjects=rec["subjects"] or [],
                claim_count=rec["claims"] or 0,
                perspective_count=rec["n_persp"] or 0,
                reading_order=rec["ord"] or 0,
                atlas_root=rec["root_name"] or "",
            ))

    return topics


@router.get("/topic/{topic_id}", response_model=AtlasArticle)
async def get_article(topic_id: str):
    """Article complet d'un NarrativeTopic (sections + liens)."""
    driver = _get_driver()
    tenant = _get_tenant()

    with driver.session() as session:
        # Topic metadata
        topic = session.run("""
            MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
            RETURN nt.narrative_label AS title, nt.executive_summary AS summary,
                   nt.claim_count AS claims, nt.total_docs AS docs,
                   nt.generated_at AS gen_at
        """, tid=topic_id, tenant=tenant).single()

        if not topic:
            return AtlasArticle(topic_id=topic_id, title="Not found")

        article = AtlasArticle(
            topic_id=topic_id,
            title=topic["title"] or "",
            executive_summary=topic["summary"] or "",
            total_claims=topic["claims"] or 0,
            total_docs=topic["docs"] or 0,
            generated_at=topic["gen_at"] or "",
        )

        # Sections (Perspectives with atlas_content)
        result = session.run("""
            MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
                  -[:INCLUDES_PERSPECTIVE]->(p:Perspective)
            RETURN p.perspective_id AS pid, p.label AS title,
                   p.atlas_content AS content, p.claim_count AS claims
            ORDER BY p.claim_count DESC
        """, tid=topic_id, tenant=tenant)
        for rec in result:
            article.sections.append(AtlasSection(
                perspective_id=rec["pid"],
                title=rec["title"] or "",
                content=rec["content"] or "",
                claim_count=rec["claims"] or 0,
            ))

        # Related topics
        result = session.run("""
            MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
                  -[r:NARRATIVE_LINK]-(other:NarrativeTopic)
            RETURN other.topic_id AS tid, other.narrative_label AS title,
                   r.narrative_role AS role, r.weight AS weight
            ORDER BY r.weight DESC
            LIMIT 5
        """, tid=topic_id, tenant=tenant)
        for rec in result:
            article.related_topics.append({
                "topic_id": rec["tid"], "title": rec["title"],
                "role": rec["role"], "weight": rec["weight"],
            })

    return article


@router.get("/theme/{theme_id}", response_model=AtlasThemeDetail)
async def get_theme_detail(theme_id: str):
    """Detail d'un AtlasTheme : description, NarrativeTopics relies, Perspectives membres."""
    driver = _get_driver()
    tenant = _get_tenant()

    with driver.session() as session:
        # Theme metadata
        rec = session.run("""
            MATCH (t:AtlasTheme {theme_id: $tid, tenant_id: $tenant})
            RETURN t.label AS label,
                   coalesce(t.description, '') AS description,
                   coalesce(t.claim_count, 0) AS claims,
                   coalesce(t.topic_coverage, 0) AS topic_count,
                   coalesce(t.topic_ids, []) AS topic_ids
        """, tid=theme_id, tenant=tenant).single()

        if not rec:
            return AtlasThemeDetail(theme_id=theme_id, label="Theme introuvable")

        detail = AtlasThemeDetail(
            theme_id=theme_id,
            label=rec["label"] or "",
            description=rec["description"] or "",
            claim_count=rec["claims"] or 0,
            topic_count=rec["topic_count"] or 0,
        )

        # NarrativeTopics qui contiennent au moins une Perspective de ce thème
        topic_rows = session.run("""
            MATCH (t:AtlasTheme {theme_id: $tid, tenant_id: $tenant})-[:GROUPS_PERSPECTIVE]->(p:Perspective)
                  <-[:INCLUDES_PERSPECTIVE]-(nt:NarrativeTopic {tenant_id: $tenant})
            OPTIONAL MATCH (ar:AtlasRoot)-[hc:HAS_CHAPTER]->(nt)
            WITH nt, ar, hc, count(DISTINCT p) AS shared_persp_count
            RETURN nt.topic_id AS topic_id,
                   nt.narrative_label AS title,
                   coalesce(nt.executive_summary, '') AS summary,
                   coalesce(nt.subject_names, []) AS subjects,
                   coalesce(nt.claim_count, 0) AS claims,
                   coalesce(nt.perspective_count, 0) AS persp_count,
                   coalesce(hc.reading_order, 0) AS reading_order,
                   coalesce(ar.canonical_name, '') AS root_name,
                   shared_persp_count
            ORDER BY shared_persp_count DESC, claims DESC
        """, tid=theme_id, tenant=tenant)
        for r in topic_rows:
            detail.related_topics.append(AtlasTopic(
                topic_id=r["topic_id"],
                title=r["title"] or "",
                executive_summary=r["summary"] or "",
                subjects=list(r["subjects"] or []),
                claim_count=r["claims"] or 0,
                perspective_count=r["persp_count"] or 0,
                reading_order=r["reading_order"] or 0,
                atlas_root=r["root_name"] or "",
            ))

        # Perspectives membres
        persp_rows = session.run("""
            MATCH (t:AtlasTheme {theme_id: $tid, tenant_id: $tenant})-[:GROUPS_PERSPECTIVE]->(p:Perspective)
            OPTIONAL MATCH (nt:NarrativeTopic {tenant_id: $tenant})-[:INCLUDES_PERSPECTIVE]->(p)
            RETURN p.perspective_id AS pid,
                   coalesce(p.label, '') AS label,
                   coalesce(p.claim_count, 0) AS claims,
                   coalesce(nt.topic_id, '') AS parent_topic_id,
                   coalesce(nt.narrative_label, '') AS parent_topic_label
            ORDER BY p.claim_count DESC
        """, tid=theme_id, tenant=tenant)
        for r in persp_rows:
            detail.perspectives.append(AtlasThemePerspective(
                perspective_id=r["pid"],
                label=r["label"] or "",
                claim_count=r["claims"] or 0,
                parent_topic_id=r["parent_topic_id"] or "",
                parent_topic_label=r["parent_topic_label"] or "",
            ))

    return detail
