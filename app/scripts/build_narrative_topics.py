"""
Build NarrativeTopics — Community detection sur le graphe biparti Perspective x Subject.

Detecte les communautes denses de Perspectives partageant des SubjectAnchors
communs. Chaque communaute = un NarrativeTopic candidat pour l'Atlas.

Usage (dans Docker):
    python scripts/build_narrative_topics.py
    python scripts/build_narrative_topics.py --resolution 1.5
    python scripts/build_narrative_topics.py --dry-run
    python scripts/build_narrative_topics.py --min-perspectives 2 --min-claims 100

Architecture :
    1. Extraire le graphe biparti Perspective -[TOUCHES_SUBJECT]-> SubjectAnchor
    2. Filtrer les subjects trop generiques (> GENERIC_THRESHOLD des perspectives)
    3. Community detection Louvain sur le graphe filtre
    4. Filtrer les communautes trop petites (< min_perspectives ou < min_claims)
    5. Generer un label narratif par LLM (optionnel)
    6. Persister les NarrativeTopic nodes + relations dans Neo4j
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
logger = logging.getLogger("narrative-topics")


# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_RESOLUTION = 1.5
GENERIC_THRESHOLD = 0.80  # subjects lies a >80% des perspectives = trop generiques
MIN_PERSPECTIVES = 2
MIN_CLAIMS = 50
TENANT_ID = "default"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class NarrativeTopic:
    topic_id: str
    perspectives: list[str]  # perspective_ids
    subjects: list[str]  # subject_ids
    perspective_labels: list[str]
    subject_names: list[str]
    claim_count: int
    doc_count: int = 0
    narrative_label: str = ""  # genere par LLM
    narrative_summary: str = ""


# ── Graph extraction ──────────────────────────────────────────────────────────

def extract_bipartite_graph(driver, tenant_id: str) -> tuple[dict, dict, list[dict]]:
    """Extraire le graphe biparti Perspective -[TOUCHES_SUBJECT]-> SubjectAnchor."""
    with driver.session() as session:
        result = session.run("""
            MATCH (p:Perspective {tenant_id: $tid})-[r:TOUCHES_SUBJECT]->(sa:SubjectAnchor)
            WHERE sa.canonical_name IS NOT NULL
            RETURN p.perspective_id AS p_id, p.label AS p_label, p.claim_count AS claims,
                   sa.subject_id AS s_id, sa.canonical_name AS s_name, r.weight AS weight
        """, tid=tenant_id)

        edges = []
        perspectives = {}
        subjects = {}
        for rec in result:
            edges.append({
                "p_id": rec["p_id"], "s_id": rec["s_id"],
                "weight": rec["weight"] or 1.0,
            })
            if rec["p_id"] not in perspectives:
                perspectives[rec["p_id"]] = {"label": rec["p_label"], "claims": rec["claims"]}
            if rec["s_id"] not in subjects:
                subjects[rec["s_id"]] = {"name": rec["s_name"], "n_persp": 0}

        # Compter les perspectives par subject
        for e in edges:
            subjects[e["s_id"]]["n_persp"] += 1

    logger.info(
        f"Graphe biparti: {len(perspectives)} perspectives x {len(subjects)} subjects "
        f"= {len(edges)} edges"
    )
    return perspectives, subjects, edges


def filter_generic_subjects(
    subjects: dict, n_perspectives: int, threshold: float = GENERIC_THRESHOLD
) -> tuple[dict, dict]:
    """Filtrer les subjects lies a trop de perspectives (pas discriminants)."""
    kept = {}
    removed = {}
    for sid, info in subjects.items():
        ratio = info["n_persp"] / n_perspectives if n_perspectives > 0 else 0
        if ratio > threshold:
            removed[sid] = info
            logger.info(f"  EXCLU: {info['name']} ({info['n_persp']}/{n_perspectives} = {ratio:.0%})")
        else:
            kept[sid] = info

    logger.info(f"Subjects: {len(subjects)} -> {len(kept)} (filtre > {threshold:.0%})")
    return kept, removed


# ── Community detection ───────────────────────────────────────────────────────

def detect_communities(
    perspectives: dict,
    subjects: dict,
    edges: list[dict],
    resolution: float = DEFAULT_RESOLUTION,
) -> list[NarrativeTopic]:
    """Louvain community detection sur le graphe biparti filtre."""
    import networkx as nx
    from networkx.algorithms.community import louvain_communities

    G = nx.Graph()
    for pid, info in perspectives.items():
        G.add_node(pid, bipartite="perspective", label=info["label"], claims=info["claims"])
    for sid, info in subjects.items():
        G.add_node(sid, bipartite="subject", label=info["name"])
    for e in edges:
        if e["s_id"] in subjects:
            G.add_edge(e["p_id"], e["s_id"], weight=e["weight"])

    communities = louvain_communities(G, weight="weight", resolution=resolution, seed=42)

    topics = []
    for i, comm in enumerate(sorted(communities, key=len, reverse=True)):
        persp_ids = [n for n in comm if G.nodes[n].get("bipartite") == "perspective"]
        subj_ids = [n for n in comm if G.nodes[n].get("bipartite") == "subject"]

        if not persp_ids:
            continue

        total_claims = sum(G.nodes[n].get("claims", 0) for n in persp_ids)

        topics.append(NarrativeTopic(
            topic_id=f"ntopic_{i:03d}",
            perspectives=persp_ids,
            subjects=subj_ids,
            perspective_labels=sorted([perspectives[p]["label"] for p in persp_ids]),
            subject_names=sorted([subjects[s]["name"] for s in subj_ids if s in subjects]),
            claim_count=total_claims,
        ))

    topics.sort(key=lambda t: t.claim_count, reverse=True)

    # Re-index apres tri
    for i, t in enumerate(topics):
        t.topic_id = f"ntopic_{i:03d}"

    logger.info(f"Communities: {len(communities)} -> {len(topics)} NarrativeTopics")
    return topics


def filter_topics(
    topics: list[NarrativeTopic],
    min_perspectives: int = MIN_PERSPECTIVES,
    min_claims: int = MIN_CLAIMS,
) -> list[NarrativeTopic]:
    """Filtrer les topics trop petits."""
    kept = [t for t in topics if len(t.perspectives) >= min_perspectives and t.claim_count >= min_claims]
    removed = len(topics) - len(kept)
    if removed:
        logger.info(f"Filtrage: {len(topics)} -> {len(kept)} topics (exclu {removed} trop petits)")
    return kept


# ── LLM labelling ────────────────────────────────────────────────────────────

def label_topics_llm(topics: list[NarrativeTopic], skip_llm: bool = False) -> None:
    """Generer un label narratif et un resume pour chaque topic via LLM."""
    if skip_llm:
        for t in topics:
            subjects_str = ", ".join(t.subject_names) if t.subject_names else "transversal"
            t.narrative_label = f"{subjects_str}: {t.perspective_labels[0][:40]}..."
        return

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    except Exception:
        logger.warning("Anthropic unavailable, using fallback labels")
        label_topics_llm(topics, skip_llm=True)
        return

    model = os.environ.get("OSMOSIS_DECOMPOSER_MODEL", "claude-haiku-4-5-20251001")

    for t in topics:
        prompt = f"""Generate a short narrative title (max 8 words) and a one-sentence summary for this knowledge topic.

The topic groups these thematic perspectives:
{json.dumps(t.perspective_labels, indent=2)}

Anchored to these subjects: {t.subject_names if t.subject_names else ['(cross-cutting, no specific product)']}

It covers {t.claim_count} factual claims from the corpus.

Return ONLY a JSON object:
{{"title": "...", "summary": "..."}}"""

        try:
            resp = client.messages.create(
                model=model, max_tokens=100, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            import re
            m = re.search(r"\{[\s\S]*\}", resp.content[0].text)
            if m:
                data = json.loads(m.group())
                t.narrative_label = data.get("title", "")
                t.narrative_summary = data.get("summary", "")
                logger.info(f"  {t.topic_id}: {t.narrative_label}")
        except Exception as e:
            logger.warning(f"  {t.topic_id}: LLM labelling failed: {e}")
            subjects_str = ", ".join(t.subject_names) if t.subject_names else "transversal"
            t.narrative_label = f"{subjects_str}: {t.perspective_labels[0][:40]}"


# ── Persistence ───────────────────────────────────────────────────────────────

def persist_topics(driver, topics: list[NarrativeTopic], tenant_id: str) -> dict:
    """Persister les NarrativeTopics dans Neo4j."""
    stats = {"created": 0, "perspective_links": 0, "subject_links": 0}

    with driver.session() as session:
        # Cleanup anciens topics
        deleted = session.run(
            "MATCH (nt:NarrativeTopic {tenant_id: $tid}) DETACH DELETE nt RETURN count(nt) AS cnt",
            tid=tenant_id,
        ).single()["cnt"]
        if deleted:
            logger.info(f"Deleted {deleted} previous NarrativeTopics")

        for t in topics:
            # Creer le node
            session.run("""
                CREATE (nt:NarrativeTopic {
                    topic_id: $tid,
                    tenant_id: $tenant,
                    narrative_label: $label,
                    narrative_summary: $summary,
                    claim_count: $claims,
                    perspective_count: $n_persp,
                    subject_count: $n_subj,
                    perspective_labels: $persp_labels,
                    subject_names: $subj_names,
                    created_at: datetime()
                })
            """,
                tid=t.topic_id, tenant=tenant_id,
                label=t.narrative_label, summary=t.narrative_summary,
                claims=t.claim_count, n_persp=len(t.perspectives), n_subj=len(t.subjects),
                persp_labels=t.perspective_labels, subj_names=t.subject_names,
            )
            stats["created"] += 1

            # Lier aux Perspectives
            for pid in t.perspectives:
                session.run("""
                    MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
                    MATCH (p:Perspective {perspective_id: $pid, tenant_id: $tenant})
                    CREATE (nt)-[:INCLUDES_PERSPECTIVE]->(p)
                """, tid=t.topic_id, tenant=tenant_id, pid=pid)
                stats["perspective_links"] += 1

            # Lier aux SubjectAnchors
            for sid in t.subjects:
                session.run("""
                    MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
                    MATCH (sa:SubjectAnchor {subject_id: $sid})
                    CREATE (nt)-[:ANCHORED_TO]->(sa)
                """, tid=t.topic_id, tenant=tenant_id, sid=sid)
                stats["subject_links"] += 1

    return stats


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build NarrativeTopics via community detection")
    parser.add_argument("--tenant", default=TENANT_ID)
    parser.add_argument("--resolution", type=float, default=DEFAULT_RESOLUTION,
                        help=f"Louvain resolution (default {DEFAULT_RESOLUTION})")
    parser.add_argument("--generic-threshold", type=float, default=GENERIC_THRESHOLD,
                        help=f"Max subject-perspective ratio (default {GENERIC_THRESHOLD})")
    parser.add_argument("--min-perspectives", type=int, default=MIN_PERSPECTIVES)
    parser.add_argument("--min-claims", type=int, default=MIN_CLAIMS)
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM labelling")
    parser.add_argument("--dry-run", action="store_true", help="Don't persist to Neo4j")
    args = parser.parse_args()

    from neo4j import GraphDatabase
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    start = time.time()
    logger.info("=" * 60)
    logger.info(f"NARRATIVE TOPICS BUILDER — {'DRY RUN' if args.dry_run else 'PRODUCTION'}")
    logger.info(f"Resolution: {args.resolution}, Generic threshold: {args.generic_threshold}")
    logger.info("=" * 60)

    # 1. Extract
    perspectives, subjects, edges = extract_bipartite_graph(driver, args.tenant)
    if not perspectives:
        logger.warning("No perspectives found — aborting")
        return

    # 2. Filter generic subjects
    filtered_subjects, removed = filter_generic_subjects(
        subjects, len(perspectives), args.generic_threshold
    )
    filtered_edges = [e for e in edges if e["s_id"] in filtered_subjects]

    # 3. Community detection
    topics = detect_communities(perspectives, filtered_subjects, filtered_edges, args.resolution)

    # 4. Filter small topics
    topics = filter_topics(topics, args.min_perspectives, args.min_claims)

    if not topics:
        logger.warning("No NarrativeTopics after filtering — aborting")
        return

    # 5. LLM labelling
    logger.info(f"\nLabelling {len(topics)} topics...")
    label_topics_llm(topics, skip_llm=args.skip_llm)

    # 6. Display
    logger.info(f"\n{'='*60}")
    logger.info(f"NARRATIVE TOPICS: {len(topics)}")
    logger.info(f"{'='*60}")
    for t in topics:
        logger.info(
            f"\n{t.topic_id}: {t.narrative_label}"
            f"\n  {len(t.perspectives)}P x {len(t.subjects)}S = {t.claim_count} claims"
            f"\n  Subjects: {t.subject_names}"
            f"\n  Perspectives: {t.perspective_labels[:3]}{'...' if len(t.perspective_labels) > 3 else ''}"
        )
        if t.narrative_summary:
            logger.info(f"  Summary: {t.narrative_summary}")

    # 7. Persist
    if not args.dry_run:
        logger.info(f"\nPersisting {len(topics)} topics to Neo4j...")
        stats = persist_topics(driver, topics, args.tenant)
        logger.info(f"Persisted: {stats}")
    else:
        logger.info("\n[DRY RUN] Skipping persistence")

    elapsed = round(time.time() - start, 1)
    logger.info(f"\nDone in {elapsed}s")
    driver.close()


if __name__ == "__main__":
    main()
