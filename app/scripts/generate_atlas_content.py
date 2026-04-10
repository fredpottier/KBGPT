"""
Generate Atlas Content — synthese narrative par LLM pour chaque NarrativeTopic.

Genere :
1. Introduction narrative de la homepage (a partir des roots + themes)
2. Articles complets pour chaque NarrativeTopic (sections = Perspectives)

Chaque article est une SYNTHESE NARRATIVE, pas une aggregation de chunks.
Le LLM (Sonnet par defaut) recoit les claims representatifs + les textes
des Perspectives et produit un texte structure avec citations.

Usage (dans Docker):
    python scripts/generate_atlas_content.py
    python scripts/generate_atlas_content.py --model claude-sonnet-4-20250514
    python scripts/generate_atlas_content.py --topic ntopic_002  # un seul topic
    python scripts/generate_atlas_content.py --homepage-only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, "/app/src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("atlas-content")

TENANT_ID = "default"
# Sonnet pour la redaction narrative (meilleur que Haiku pour le long-form)
DEFAULT_MODEL = "claude-sonnet-4-20250514"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class AtlasSection:
    """Section d'un article = une Perspective."""
    perspective_id: str
    title: str
    content: str = ""  # markdown genere par LLM
    claim_count: int = 0
    source_docs: list[str] = field(default_factory=list)


@dataclass
class AtlasArticle:
    """Article complet pour un NarrativeTopic."""
    topic_id: str
    title: str
    executive_summary: str = ""
    sections: list[AtlasSection] = field(default_factory=list)
    related_topics: list[dict] = field(default_factory=list)  # [{topic_id, label, role}]
    total_claims: int = 0
    total_docs: int = 0
    generated_at: str = ""


# ── Load topic data from Neo4j ────────────────────────────────────────────────

def load_topic_content(driver, topic_id: str, tenant_id: str) -> dict:
    """Charge les donnees d'un topic pour la generation."""
    with driver.session() as session:
        # Topic metadata
        topic = session.run("""
            MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
            RETURN nt.narrative_label AS label, nt.narrative_summary AS summary,
                   nt.perspective_labels AS persp_labels, nt.subject_names AS subjects,
                   nt.claim_count AS claims, nt.reading_order AS reading_order
        """, tid=topic_id, tenant=tenant_id).single()

        if not topic:
            return {}

        # Perspectives with representative texts
        perspectives = []
        result = session.run("""
            MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
                  -[:INCLUDES_PERSPECTIVE]->(p:Perspective)
            RETURN p.perspective_id AS pid, p.label AS label,
                   p.claim_count AS claims, p.representative_texts AS texts,
                   p.keywords AS keywords, p.description AS desc
            ORDER BY p.claim_count DESC
        """, tid=topic_id, tenant=tenant_id)
        for rec in result:
            perspectives.append({
                "pid": rec["pid"], "label": rec["label"],
                "claims": rec["claims"],
                "texts": rec["texts"] or [],
                "keywords": rec["keywords"] or [],
                "description": rec["desc"] or "",
            })

        # Source documents
        doc_ids = set()
        result = session.run("""
            MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
                  -[:INCLUDES_PERSPECTIVE]->(p:Perspective)
                  -[:INCLUDES_CLAIM]->(c:Claim)
            RETURN DISTINCT c.doc_id AS doc_id
        """, tid=topic_id, tenant=tenant_id)
        for rec in result:
            if rec["doc_id"]:
                doc_ids.add(rec["doc_id"])

        # Related topics (NARRATIVE_LINK)
        related = []
        result = session.run("""
            MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
                  -[r:NARRATIVE_LINK]-(other:NarrativeTopic)
            RETURN other.topic_id AS other_id, other.narrative_label AS label,
                   r.narrative_role AS role, r.weight AS weight
            ORDER BY r.weight DESC
            LIMIT 5
        """, tid=topic_id, tenant=tenant_id)
        for rec in result:
            related.append({
                "topic_id": rec["other_id"], "label": rec["label"],
                "role": rec["role"], "weight": rec["weight"],
            })

        return {
            "topic_id": topic_id,
            "label": topic["label"],
            "summary": topic["summary"],
            "subjects": topic["subjects"],
            "claims": topic["claims"],
            "perspectives": perspectives,
            "doc_ids": list(doc_ids),
            "related": related,
        }


# ── LLM generation ───────────────────────────────────────────────────────────

def get_llm_client(model: str):
    """Retourne un client Anthropic configure."""
    import anthropic
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


def generate_section(client, model: str, perspective: dict, topic_label: str) -> str:
    """Genere le contenu d'une section (1 Perspective) via LLM."""
    texts = perspective.get("texts", [])
    if not texts:
        return ""

    # Limiter a ~15 textes representatifs pour rester dans le budget tokens
    sample_texts = texts[:15]
    texts_block = "\n".join(f"- {t[:300]}" for t in sample_texts)

    prompt = f"""You are writing a section of a technical knowledge article.

Topic: {topic_label}
Section: {perspective['label']}
Description: {perspective.get('description', '')}

This section is based on {perspective['claims']} verified claims from the corpus.
Here are representative extracts:

{texts_block}

Write a clear, informative section (3-5 paragraphs) that:
1. Synthesizes the key information from these extracts into a coherent narrative
2. Covers the main points without being exhaustive — prioritize what matters most
3. Uses precise technical language appropriate to the domain
4. Is written in the same language as the extracts (if French, write in French; if English, write in English)
5. Does NOT add information not present in the extracts
6. Does NOT use headers or titles (the section title is already provided)
7. Flows naturally as prose, not bullet points

Return ONLY the section text, no preamble."""

    try:
        resp = client.messages.create(
            model=model, max_tokens=1000, temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.warning(f"  Section generation failed: {e}")
        return ""


def generate_executive_summary(client, model: str, topic_data: dict) -> str:
    """Genere le resume executif d'un article."""
    persp_labels = [p["label"] for p in topic_data["perspectives"]]

    prompt = f"""Write a concise executive summary (80-120 words) for this knowledge article.

Article title: {topic_data['label']}
Subjects: {topic_data['subjects']}
Sections covered: {json.dumps(persp_labels)}
Total verified claims: {topic_data['claims']}
Source documents: {len(topic_data['doc_ids'])}

The summary should:
1. State what this article covers and why it matters
2. Mention the key aspects (sections) briefly
3. Be written in the same language as the section titles
4. Be direct and informative — no filler

Return ONLY the summary text."""

    try:
        resp = client.messages.create(
            model=model, max_tokens=300, temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.warning(f"  Summary generation failed: {e}")
        return topic_data.get("summary", "")


def generate_homepage_intro(client, model: str, roots: list[dict], themes: list[dict], stats: dict) -> str:
    """Genere l'introduction narrative de la homepage Atlas."""
    roots_desc = "\n".join(f"- {r['name']} ({r['n_topics']} chapters, {r['claims']} claims)" for r in roots)
    themes_desc = "\n".join(f"- {t['label']} ({t['claims']} claims, crosses {t['n_topics']} chapters)" for t in themes)

    prompt = f"""Write an introduction (150-200 words) for a knowledge atlas homepage.

This atlas covers {stats['total_docs']} documents containing {stats['total_claims']} verified facts.

Product structure (reading by product):
{roots_desc}

Thematic structure (reading by theme):
{themes_desc}

The introduction should:
1. Welcome the reader and explain what this atlas contains
2. Briefly describe the two reading modes (by product, by theme)
3. Highlight that the content is synthesized from verified source documents
4. Be written in the same language as the roots/themes above
5. Be inviting and professional, not technical
6. NOT list all topics — just give the reader a sense of what to expect

Return ONLY the introduction text."""

    try:
        resp = client.messages.create(
            model=model, max_tokens=500, temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.warning(f"  Homepage intro generation failed: {e}")
        return ""


# ── Article builder ───────────────────────────────────────────────────────────

def build_article(driver, client, model: str, topic_id: str, tenant_id: str) -> AtlasArticle | None:
    """Construit un article complet pour un NarrativeTopic."""
    data = load_topic_content(driver, topic_id, tenant_id)
    if not data:
        logger.warning(f"  Topic {topic_id} not found")
        return None

    article = AtlasArticle(
        topic_id=topic_id,
        title=data["label"],
        total_claims=data["claims"],
        total_docs=len(data["doc_ids"]),
        related_topics=data["related"],
    )

    # Executive summary
    logger.info(f"  Generating summary...")
    article.executive_summary = generate_executive_summary(client, model, data)

    # Sections (1 per Perspective)
    for persp in data["perspectives"]:
        logger.info(f"  Generating section: {persp['label'][:50]}...")
        content = generate_section(client, model, persp, data["label"])
        section = AtlasSection(
            perspective_id=persp["pid"],
            title=persp["label"],
            content=content,
            claim_count=persp["claims"],
        )
        article.sections.append(section)

    from datetime import datetime, timezone
    article.generated_at = datetime.now(timezone.utc).isoformat()

    return article


# ── Persistence ───────────────────────────────────────────────────────────────

def persist_article(driver, article: AtlasArticle, tenant_id: str) -> None:
    """Persiste le contenu genere dans Neo4j."""
    with driver.session() as session:
        # Mettre a jour le NarrativeTopic avec le contenu genere
        session.run("""
            MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
            SET nt.executive_summary = $summary,
                nt.generated_at = $gen_at,
                nt.total_docs = $n_docs
        """,
            tid=article.topic_id, tenant=tenant_id,
            summary=article.executive_summary,
            gen_at=article.generated_at,
            n_docs=article.total_docs,
        )

        # Stocker le contenu de chaque section sur la Perspective
        for section in article.sections:
            session.run("""
                MATCH (p:Perspective {perspective_id: $pid, tenant_id: $tenant})
                SET p.atlas_content = $content,
                    p.atlas_generated_at = $gen_at
            """,
                pid=section.perspective_id, tenant=tenant_id,
                content=section.content,
                gen_at=article.generated_at,
            )


def persist_homepage(driver, intro: str, tenant_id: str) -> None:
    """Persiste l'introduction de la homepage."""
    with driver.session() as session:
        session.run("""
            MERGE (h:AtlasHomepage {tenant_id: $tenant})
            SET h.introduction = $intro,
                h.generated_at = datetime()
        """, tenant=tenant_id, intro=intro)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Atlas content via LLM")
    parser.add_argument("--tenant", default=TENANT_ID)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--topic", default=None, help="Generate only this topic (e.g. ntopic_002)")
    parser.add_argument("--homepage-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from neo4j import GraphDatabase
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    client = get_llm_client(args.model)
    start = time.time()

    logger.info("=" * 60)
    logger.info(f"ATLAS CONTENT GENERATOR — model={args.model}")
    logger.info("=" * 60)

    # Load Atlas structure
    with driver.session() as session:
        # Roots
        roots = []
        result = session.run("""
            MATCH (ar:AtlasRoot {tenant_id: $tenant})
            OPTIONAL MATCH (ar)-[:HAS_CHAPTER]->(nt:NarrativeTopic)
            RETURN ar.canonical_name AS name, ar.claim_count AS claims,
                   count(nt) AS n_topics
        """, tenant=args.tenant)
        for rec in result:
            roots.append({"name": rec["name"], "claims": rec["claims"], "n_topics": rec["n_topics"]})

        # Topics
        topic_ids = []
        result = session.run("""
            MATCH (nt:NarrativeTopic {tenant_id: $tenant})
            RETURN nt.topic_id AS tid, nt.narrative_label AS label,
                   nt.claim_count AS claims, nt.reading_order AS ord
            ORDER BY nt.reading_order
        """, tenant=args.tenant)
        for rec in result:
            topic_ids.append({"id": rec["tid"], "label": rec["label"],
                              "claims": rec["claims"], "order": rec["ord"]})

        # Stats
        total_claims = session.run(
            "MATCH (c:Claim {tenant_id: $tenant}) RETURN count(c) AS cnt",
            tenant=args.tenant,
        ).single()["cnt"]
        total_docs = session.run(
            "MATCH (dc:DocumentContext {tenant_id: $tenant}) RETURN count(dc) AS cnt",
            tenant=args.tenant,
        ).single()["cnt"]

    if not topic_ids and not roots:
        logger.warning("No Atlas structure found. Run build_narrative_topics.py first.")
        return

    stats = {"total_docs": total_docs, "total_claims": total_claims}

    # Homepage introduction
    if not args.topic:
        logger.info(f"\nGenerating homepage introduction...")
        # Load themes (quick clustering, skip if no embeddings)
        themes = []
        try:
            from detect_thematic_axes import load_perspective_embeddings, cluster_themes, label_axes_llm
            perspectives = load_perspective_embeddings(driver, args.tenant)
            axes = cluster_themes(perspectives, 8)
            label_axes_llm(axes, skip_llm=False)
            themes = [{"label": ax.label, "claims": ax.claim_count, "n_topics": ax.topic_coverage} for ax in axes]
        except Exception as e:
            logger.warning(f"  Theme detection failed: {e}")

        intro = generate_homepage_intro(client, args.model, roots, themes, stats)
        if intro:
            logger.info(f"\n--- HOMEPAGE INTRODUCTION ---")
            logger.info(intro)
            if not args.dry_run:
                persist_homepage(driver, intro, args.tenant)
                logger.info("  Persisted to Neo4j")

    if args.homepage_only:
        logger.info(f"\nDone (homepage only) in {time.time() - start:.1f}s")
        driver.close()
        return

    # Articles
    targets = topic_ids if not args.topic else [t for t in topic_ids if t["id"] == args.topic]
    if not targets:
        logger.warning(f"Topic {args.topic} not found")
        return

    logger.info(f"\nGenerating {len(targets)} articles...")
    for i, t in enumerate(targets):
        logger.info(f"\n[{i+1}/{len(targets)}] {t['label']}")
        article = build_article(driver, client, args.model, t["id"], args.tenant)
        if article:
            logger.info(
                f"  Generated: {len(article.sections)} sections, "
                f"{sum(len(s.content) for s in article.sections)} chars total"
            )
            if not args.dry_run:
                persist_article(driver, article, args.tenant)
                logger.info("  Persisted to Neo4j")
            else:
                # Preview first section
                if article.sections:
                    s = article.sections[0]
                    logger.info(f"  Preview ({s.title[:40]}):")
                    logger.info(f"  {s.content[:200]}...")

    elapsed = round(time.time() - start, 1)
    logger.info(f"\nDone in {elapsed}s")
    driver.close()


if __name__ == "__main__":
    main()
