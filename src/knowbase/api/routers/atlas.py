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
    topics: List[AtlasTopic] = []
    claim_count: int = 0


class AtlasTheme(BaseModel):
    label: str
    claim_count: int = 0
    topic_ids: List[str] = []
    topic_labels: List[str] = []


class AtlasHomepage(BaseModel):
    introduction: str = ""
    roots: List[AtlasRoot] = []
    themes: List[AtlasTheme] = []
    total_docs: int = 0
    total_claims: int = 0
    total_topics: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_driver():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    return get_neo4j_client().driver


def _get_tenant():
    return "default"


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
            RETURN ar.root_id AS rid, ar.canonical_name AS name, ar.claim_count AS claims,
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
                topics=root_topics, claim_count=rec["claims"] or 0,
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

    # Themes (from Perspective embeddings — cached or computed)
    try:
        # Quick theme detection if available
        from knowbase.perspectives.orchestrator import _get_neo4j_driver
        import sys
        sys.path.insert(0, "/app")
        from scripts.detect_thematic_axes import load_perspective_embeddings, cluster_themes, label_axes_llm

        perspectives = load_perspective_embeddings(driver, tenant)
        axes = cluster_themes(perspectives, min(8, len(perspectives) // 3))
        label_axes_llm(axes, skip_llm=True)  # fast fallback labels

        for ax in axes:
            homepage.themes.append(AtlasTheme(
                label=ax.label, claim_count=ax.claim_count,
                topic_ids=[], topic_labels=ax.perspective_labels[:5],
            ))
    except Exception as e:
        logger.debug(f"[ATLAS] Theme detection failed: {e}")

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
