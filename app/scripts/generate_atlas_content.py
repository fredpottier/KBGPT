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
    """Retourne le llm_router (compatibilité avec l'ancien API Anthropic)."""
    from knowbase.common.llm_router import get_llm_router
    return get_llm_router()


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

Redige une section claire et informative (3-5 paragraphes) qui :
1. Synthetise les informations cles de ces extraits en un recit coherent
2. Couvre les points principaux sans etre exhaustif — priorise ce qui compte le plus
3. Utilise un langage technique precis adapte au domaine
4. Est redigee en FRANCAIS (meme si les extraits sont en anglais, la synthese doit etre en francais)
5. N'ajoute AUCUNE information absente des extraits
6. N'utilise PAS de titres ni de headers (le titre de la section est deja fourni)
7. S'ecoule naturellement en prose, pas en puces

Retourne UNIQUEMENT le texte de la section, sans preambule."""

    try:
        from knowbase.common.llm_router import TaskType
        return client.complete(
            task_type=TaskType.LONG_TEXT_SUMMARY,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000,
        ).strip()
    except Exception as e:
        logger.warning(f"  Section generation failed: {e}")
        return ""


def generate_executive_summary(client, model: str, topic_data: dict) -> str:
    """Genere le resume executif d'un article."""
    persp_labels = [p["label"] for p in topic_data["perspectives"]]

    prompt = f"""Redige un resume executif concis (80-120 mots, EN FRANCAIS) pour cet article.

Titre de l'article : {topic_data['label']}
Sujets : {topic_data['subjects']}
Sections couvertes : {json.dumps(persp_labels)}
Nombre de faits verifies : {topic_data['claims']}
Documents source : {len(topic_data['doc_ids'])}

Le resume doit :
1. Indiquer ce que couvre cet article et pourquoi c'est important
2. Mentionner brievement les aspects cles (sections)
3. Etre redige en FRANCAIS
4. Etre direct et informatif — pas de remplissage

Retourne UNIQUEMENT le texte du resume."""

    try:
        from knowbase.common.llm_router import TaskType
        return client.complete(
            task_type=TaskType.LONG_TEXT_SUMMARY,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        ).strip()
    except Exception as e:
        logger.warning(f"  Summary generation failed: {e}")
        return topic_data.get("summary", "")


def generate_homepage_intro(client, model: str, roots: list[dict], themes: list[dict], stats: dict) -> str:
    """Genere l'introduction narrative de la homepage Atlas."""
    roots_desc = "\n".join(f"- {r['name']} ({r['n_topics']} chapitres, {r['claims']} faits)" for r in roots)
    themes_desc = "\n".join(f"- {t['label']} ({t['claims']} faits, traverse {t['n_topics']} chapitres)" for t in themes)

    prompt = f"""Redige une introduction pedagogique (180-260 mots, EN FRANCAIS) pour la page d'accueil d'un atlas documentaire.

Cet atlas couvre {stats['total_docs']} documents avec {stats['total_claims']} faits verifies.

Structure par dossier (regroupements par texte/source dominant) :
{roots_desc}

Structure par theme (axes transversaux qui traversent plusieurs dossiers) :
{themes_desc}

L'introduction doit servir DEUX profils de lecteurs :
- Le profane qui ne connait pas le domaine et veut comprendre
- L'expert qui connait deja et veut une vue d'ensemble structuree

Structure obligatoire (4 paragraphes courts, separes par des sauts de ligne) :

1. **Cadrage du corpus** (3-5 phrases) : commencer par "Cet Atlas documente..." et identifier les 2-3 grands univers/domaines reels presents dans le corpus, en analysant les noms des dossiers listes ci-dessus. NE PAS parler des "modes de lecture" ici. Decrire ce que sont les VRAIS sujets traites avec un exemple concret. Si les dossiers correspondent a des textes officiels precis (ex: "Regulation EU 2021/821", "CS-25 Amendment 24"), expliquer brievement ce que sont ces textes (qui les emet, sur quoi ils portent).

2. **Si vous decouvrez ces domaines** (1-2 phrases) : suggerer un parcours d'apprentissage en citant 1-2 dossiers ou chapitres reels par lesquels commencer.

3. **Si vous connaissez deja** (1-2 phrases) : suggerer d'utiliser la grille comme index pour aller directement au chapitre pertinent, ou la vue thematique pour les recherches transverses.

4. **Volumetrie** (1 phrase) : "{stats['total_docs']} textes analyses, {stats['total_claims']} faits extraits et verifies."

Contraintes de style :
- Ton sobre, factuel, accessible. Pas de "boussole", pas de "votre exploration", pas de "appréhender sans effort". Pas de tournure marketing.
- Citer les noms reels des dossiers ou themes pour ancrer le lecteur dans le concret.
- Registre professionnel francais. Phrases courtes.

Retourne UNIQUEMENT le texte de l'introduction, sans titre, avec les 4 paragraphes separes par des doubles sauts de ligne."""

    try:
        from knowbase.common.llm_router import TaskType
        return client.complete(
            task_type=TaskType.LONG_TEXT_SUMMARY,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        ).strip()
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


# ── Metadata enrichment (descriptions Roots + labels manquants) ───────────────

def generate_root_description(client, root_name: str, topic_summaries: list[str]) -> str:
    """Genere 2-3 phrases sur ce que regroupe un AtlasRoot."""
    summaries_block = "\n\n".join(f"- {s[:300]}" for s in topic_summaries[:4])
    prompt = f"""Le dossier "{root_name}" regroupe {len(topic_summaries)} chapitres dans un atlas documentaire.

Voici les resumes des chapitres qu'il contient :
{summaries_block}

Redige une description (60-110 mots, EN FRANCAIS) qui :
1. Identifie ce qu'est ce dossier (texte officiel, domaine, ou regroupement) — si le nom du dossier est un texte officiel, expliquer brievement ce que c'est (qui l'emet, sur quoi il porte)
2. Decrit les principaux enjeux ou sujets traites a travers les chapitres
3. Indique a qui ce dossier est principalement utile (profession, role, contexte)

Contraintes :
- Ton sobre, factuel, accessible.
- Pas de tournure marketing, pas de "ce dossier vous offre".
- Pas de redondance avec le titre du dossier.

Retourne UNIQUEMENT le texte de la description, sans titre."""
    try:
        from knowbase.common.llm_router import TaskType
        return client.complete(
            task_type=TaskType.LONG_TEXT_SUMMARY,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=300,
        ).strip()
    except Exception as e:
        logger.warning(f"  Root description generation failed: {e}")
        return ""


def generate_topic_label(client, topic_summary: str) -> str:
    """Genere un titre court (5-9 mots) pour un NarrativeTopic depuis son exec_summary."""
    prompt = f"""Voici le resume d'un chapitre d'atlas documentaire :

{topic_summary[:600]}

Genere un TITRE COURT (5-9 mots, EN FRANCAIS) qui capture l'essentiel de ce chapitre.
Le titre doit etre descriptif et concret, pas generique.
Pas de guillemets, pas de ponctuation finale.
Retourne UNIQUEMENT le titre."""
    try:
        from knowbase.common.llm_router import TaskType
        raw = client.complete(
            task_type=TaskType.LONG_TEXT_SUMMARY,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=60,
        ).strip()
        # Nettoyage : strip guillemets/quotes, ponctuation finale, retours ligne multiples
        return raw.strip().strip('"\'').rstrip('.,;:').strip()
    except Exception as e:
        logger.warning(f"  Topic label generation failed: {e}")
        return ""


def generate_theme_label_and_description(client, perspective_labels: list[str], claim_count: int, topic_coverage: int) -> tuple[str, str]:
    """Genere (label, description) pour un theme transversal via LLM (DeepSeek-V4-Pro)."""
    labels_block = "\n".join(f"- {l}" for l in perspective_labels[:15])
    prompt = f"""Voici {len(perspective_labels)} perspectives narratives qui forment un meme theme transversal dans un atlas documentaire (totalisant {claim_count} faits, traversant {topic_coverage} chapitres).

Perspectives membres :
{labels_block}

Genere :
1. un LABEL (4-8 mots, EN FRANCAIS) qui capture le fil rouge de ces perspectives. Doit etre descriptif et concret. NE PAS faire une concatenation de mots-cles type "A & B & C".
2. une DESCRIPTION (60-100 mots, EN FRANCAIS) qui explique :
   - de quoi parle ce theme transversal
   - en quoi il traverse plusieurs dossiers/documents differents (sa transversalite)
   - pour qui c'est utile (profession, role)

Ton sobre, factuel, accessible. Pas de marketing. Pas de redondance avec le label.

Format de reponse JSON strict :
{{"label": "...", "description": "..."}}

Retourne UNIQUEMENT le JSON, sans markdown ni preambule."""
    try:
        from knowbase.common.llm_router import TaskType
        raw = client.complete(
            task_type=TaskType.LONG_TEXT_SUMMARY,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=400,
        ).strip()
        # Nettoyer si markdown
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1].lstrip("json").strip()
        data = json.loads(raw)
        return (str(data.get("label", "")).strip(), str(data.get("description", "")).strip())
    except Exception as e:
        logger.warning(f"  Theme label/description generation failed: {e}")
        return ("", "")


def enrich_atlas_themes(driver, client, tenant_id: str, n_themes="auto", dry_run: bool = False) -> None:
    """Calcule via clustering + persiste les AtlasTheme avec label LLM et description.

    n_themes: int (K fixe) OR "auto" (silhouette scan).
    """
    try:
        from detect_thematic_axes import load_perspective_embeddings, cluster_themes
    except ImportError:
        logger.warning("Cannot import detect_thematic_axes — skipping theme enrichment")
        return

    perspectives = load_perspective_embeddings(driver, tenant_id)
    if not perspectives:
        logger.warning("No perspectives with embeddings — skipping themes")
        return

    # n_themes="auto" → silhouette scan determine le K optimal pour le corpus
    axes = cluster_themes(perspectives, n_themes)

    # Compute topic_coverage (nb of NarrativeTopics that touch each axis)
    with driver.session() as session:
        rows = session.run("""
            MATCH (nt:NarrativeTopic {tenant_id: $tenant})-[:INCLUDES_PERSPECTIVE]->(p:Perspective)
            RETURN nt.topic_id AS tid, collect(p.perspective_id) AS pids
        """, tenant=tenant_id).data()
    topic_pids = {r["tid"]: set(r["pids"]) for r in rows}

    for ax in axes:
        ax_persp_set = set(ax.perspective_ids)
        ax.topic_ids = [tid for tid, pids in topic_pids.items() if pids & ax_persp_set]
        ax.topic_coverage = len(ax.topic_ids)

    logger.info(f"\nThemes to label + describe: {len(axes)}")

    # Wipe existing themes (idempotent)
    if not dry_run:
        with driver.session() as session:
            session.run("MATCH (t:AtlasTheme {tenant_id: $tenant}) DETACH DELETE t", tenant=tenant_id)

    for ax in axes:
        label, description = generate_theme_label_and_description(
            client, ax.perspective_labels, ax.claim_count, ax.topic_coverage,
        )
        if not label:
            label = f"Thème {ax.axis_id}"
        ax.label = label
        logger.info(f"  {ax.axis_id} ({ax.claim_count} faits, {ax.topic_coverage} chapitres):")
        logger.info(f"    label: {label}")
        if description:
            logger.info(f"    desc:  {description[:140]}...")

        if not dry_run:
            with driver.session() as session:
                session.run("""
                    MERGE (t:AtlasTheme {theme_id: $tid, tenant_id: $tenant})
                    SET t.label = $label,
                        t.description = $desc,
                        t.claim_count = $claims,
                        t.perspective_ids = $persp_ids,
                        t.perspective_labels = $persp_labels,
                        t.topic_ids = $topic_ids,
                        t.topic_coverage = $topic_count,
                        t.generated_at = datetime()
                    WITH t
                    UNWIND $persp_ids AS pid
                    MATCH (p:Perspective {perspective_id: pid, tenant_id: $tenant})
                    MERGE (t)-[:GROUPS_PERSPECTIVE]->(p)
                """, tid=ax.axis_id, tenant=tenant_id,
                     label=label, desc=description,
                     claims=ax.claim_count,
                     persp_ids=ax.perspective_ids,
                     persp_labels=ax.perspective_labels[:30],
                     topic_ids=ax.topic_ids,
                     topic_count=ax.topic_coverage)


def enrich_atlas_metadata(driver, client, tenant_id: str, dry_run: bool = False) -> None:
    """Enrichit AtlasRoots avec descriptions + complete les NarrativeTopic.narrative_label manquants."""
    # 1. Combler les narrative_label manquants
    with driver.session() as session:
        rows_topics = session.run("""
            MATCH (nt:NarrativeTopic {tenant_id: $tenant})
            WHERE coalesce(nt.narrative_label, '') = '' AND nt.executive_summary IS NOT NULL
            RETURN nt.topic_id AS tid, nt.executive_summary AS summary
            ORDER BY nt.topic_id
        """, tenant=tenant_id).data()

    logger.info(f"\nTopic labels to fill: {len(rows_topics)}")
    for row in rows_topics:
        label = generate_topic_label(client, row["summary"])
        if not label:
            continue
        logger.info(f"  {row['tid']}: \"{label}\"")
        if not dry_run:
            with driver.session() as session:
                session.run("""
                    MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
                    SET nt.narrative_label = $label
                """, tid=row["tid"], tenant=tenant_id, label=label)

    # 2. Generer description sur chaque AtlasRoot
    with driver.session() as session:
        rows_roots = session.run("""
            MATCH (ar:AtlasRoot {tenant_id: $tenant})
            OPTIONAL MATCH (ar)-[:HAS_CHAPTER]->(nt:NarrativeTopic)
            WITH ar, collect(nt.executive_summary) AS summaries
            RETURN ar.root_id AS rid, ar.canonical_name AS name, summaries
            ORDER BY ar.claim_count DESC
        """, tenant=tenant_id).data()

    logger.info(f"\nRoot descriptions to generate: {len(rows_roots)}")
    for row in rows_roots:
        summaries = [s for s in (row["summaries"] or []) if s]
        if not summaries:
            continue
        desc = generate_root_description(client, row["name"], summaries)
        if not desc:
            continue
        logger.info(f"  {row['name']}:")
        for line in desc.split("\n"):
            logger.info(f"    {line}")
        if not dry_run:
            with driver.session() as session:
                session.run("""
                    MATCH (ar:AtlasRoot {root_id: $rid, tenant_id: $tenant})
                    SET ar.description = $desc
                """, rid=row["rid"], tenant=tenant_id, desc=desc)

    # 3. Generer + persister les AtlasTheme (label LLM + description)
    enrich_atlas_themes(driver, client, tenant_id, dry_run=dry_run)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Atlas content via LLM")
    parser.add_argument("--tenant", default=TENANT_ID)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--topic", default=None, help="Generate only this topic (e.g. ntopic_002)")
    parser.add_argument("--homepage-only", action="store_true")
    parser.add_argument("--enrich-metadata", action="store_true",
                        help="Enrich AtlasRoot.description + fill missing NarrativeTopic.narrative_label")
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

    # --- Enrich metadata only (descriptions Roots + labels manquants) ---
    if args.enrich_metadata:
        enrich_atlas_metadata(driver, client, args.tenant, dry_run=args.dry_run)
        logger.info(f"\nDone (enrich metadata) in {time.time() - start:.1f}s")
        driver.close()
        return

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
