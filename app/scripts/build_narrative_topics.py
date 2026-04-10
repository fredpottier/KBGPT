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
class AtlasRoot:
    """Level 0 — Sujet federateur (ComparableSubject ou SubjectAnchor generique)."""
    root_id: str
    canonical_name: str
    topic_ids: list[str] = field(default_factory=list)
    claim_count: int = 0
    affinity: float = 0.0  # % des perspectives couvertes


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
    reading_order: int = 0  # position dans le parcours de lecture
    atlas_root_id: str = ""  # level 0 parent


@dataclass
class TopicLink:
    """Lien narratif entre deux NarrativeTopics."""
    from_topic: str
    to_topic: str
    relation_type: str  # chains_to, refines, complements, qualifies, contradicts
    weight: int  # nombre de relations cross-doc
    narrative_role: str = ""  # "leads_to", "details", "complements", "nuances", "tensions"


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


# ── Atlas hierarchy (level 0) ─────────────────────────────────────────────────


def build_atlas_roots(
    topics: list[NarrativeTopic],
    generic_subjects: dict,
    all_edges: list[dict],
    n_perspectives: int,
) -> list[AtlasRoot]:
    """Construit les level 0 de l'Atlas a partir des sujets generiques filtres.

    Chaque sujet generique (> GENERIC_THRESHOLD des perspectives) devient un
    AtlasRoot candidat. Les topics sont rattaches au root le plus specifique
    dont ils partagent la majorite des perspectives.

    Strategie de selection des roots :
    - Exclure les sujets trop vagues ("SAP" tout court)
    - Garder les sujets qui discriminent au moins un topic (pas 100% sur tous)
    - Fusionner les quasi-doublons (S/4HANA vs S/4HANA 2023 Feature Scope)
    """
    if not generic_subjects:
        return []

    # Calculer l'affinite topic x sujet generique
    affinities: dict[str, dict[str, float]] = {}  # {root_sid: {topic_id: ratio}}
    for sid, info in generic_subjects.items():
        affinities[sid] = {}
        for t in topics:
            count = sum(1 for e in all_edges if e["p_id"] in set(t.perspectives) and e["s_id"] == sid)
            ratio = count / len(t.perspectives) if t.perspectives else 0
            affinities[sid][t.topic_id] = ratio

    # Strategie de selection des roots :
    # 1. Exclure les sujets 100% uniformes (SAP, SAP S/4HANA) — pas de signal
    # 2. Exclure les sujets purement techniques (ABAP, Feature Scope) — pas narratifs
    # 3. Garder le sujet-produit le plus specifique qui couvre > 50% des topics
    #
    # Heuristique domain-agnostic : un bon root est un NOM DE PRODUIT (contient
    # des majuscules, souvent multi-mots) pas un terme technique generique.
    # On ne hardcode aucun nom — on filtre par structure.

    candidate_roots = []
    for sid, info in generic_subjects.items():
        ratios = list(affinities[sid].values())
        min_ratio = min(ratios) if ratios else 1.0
        n_topics_covered = sum(1 for r in ratios if r > 0.5)

        # Exclure 100% uniforme (pas de discrimination)
        if min_ratio >= 0.95:
            logger.debug(f"  Root skip (uniform): {info['name']}")
            continue

        # NOTE: pas de filtre sur la forme du nom (mono-mot, etc.)
        # Un sujet mono-mot peut etre un bon root dans un autre domaine
        # (ex: "Oncology", "Diabetes", "GDPR"). Seul le critere structurel
        # (discrimination) compte.

        candidate_roots.append({
            "sid": sid, "name": info["name"],
            "coverage": info["n_persp"] / n_perspectives,
            "n_topics": n_topics_covered,
            "min_ratio": min_ratio,
        })

    # Trier par specificite (coverage asc = plus discriminant d'abord)
    # A specificite egale, celui qui couvre le plus de topics
    candidate_roots.sort(key=lambda r: (r["coverage"], -r["n_topics"]))

    # Garder le meilleur root (ou le plus general en fallback)
    if not candidate_roots:
        fallback = max(generic_subjects.items(), key=lambda x: x[1]["n_persp"])
        logger.info(f"  No product root found, using: {fallback[1]['name']}")
        candidate_roots = [{"sid": fallback[0], "name": fallback[1]["name"],
                            "coverage": fallback[1]["n_persp"] / n_perspectives,
                            "n_topics": len(topics), "min_ratio": 0.8}]

    # Dedupliquer : garder le root le plus specifique, puis ajouter un second
    # root seulement s'il couvre au moins MIN_NEW_TOPICS topics non deja couverts
    MIN_NEW_TOPICS = 3  # un root doit apporter au moins 3 topics nouveaux
    selected_roots = []
    covered_topics: set[str] = set()
    for root in candidate_roots:
        root_topics = {tid for tid, r in affinities[root["sid"]].items() if r > 0.5}
        new_topics = root_topics - covered_topics
        if len(new_topics) >= MIN_NEW_TOPICS or not selected_roots:
            selected_roots.append(root)
            covered_topics.update(root_topics)
        else:
            logger.debug(f"  Root skip (only {len(new_topics)} new topics): {root['name']}")

    # Construire les AtlasRoot
    roots = []
    for root_info in selected_roots:
        sid = root_info["sid"]
        root = AtlasRoot(
            root_id=f"atlas_{sid[-8:]}",
            canonical_name=root_info["name"],
            affinity=root_info["coverage"],
        )

        # Rattacher les topics (affinite > 50%)
        for t in topics:
            ratio = affinities[sid].get(t.topic_id, 0)
            if ratio > 0.5:
                root.topic_ids.append(t.topic_id)
                root.claim_count += t.claim_count
                t.atlas_root_id = root.root_id

        roots.append(root)

    # Topics orphelins (pas rattaches a un root) → creer un root "Transversal"
    orphans = [t for t in topics if not t.atlas_root_id]
    if orphans:
        transversal = AtlasRoot(
            root_id="atlas_transversal",
            canonical_name="Themes transversaux",
            topic_ids=[t.topic_id for t in orphans],
            claim_count=sum(t.claim_count for t in orphans),
        )
        for t in orphans:
            t.atlas_root_id = transversal.root_id
        roots.append(transversal)

    logger.info(f"Atlas roots: {len(roots)}")
    for r in roots:
        logger.info(f"  {r.canonical_name}: {len(r.topic_ids)} topics, {r.claim_count} claims ({r.affinity:.0%})")

    return roots


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


# ── Inter-topic links ─────────────────────────────────────────────────────────

# Mapping type de relation KG → role narratif
RELATION_TO_NARRATIVE_ROLE = {
    "CHAINS_TO": "leads_to",       # ce topic mene a celui-la (sequence)
    "REFINES": "details",          # ce topic precise celui-la (zoom)
    "COMPLEMENTS": "complements",  # ces topics se completent
    "QUALIFIES": "nuances",        # ce topic nuance celui-la (conditions)
    "CONTRADICTS": "tensions",     # ces topics se contredisent
    "EVOLVES_TO": "leads_to",      # evolution temporelle
    "SPECIALIZES": "details",      # specialisation
}


def detect_inter_topic_links(
    driver, topics: list[NarrativeTopic], tenant_id: str
) -> list[TopicLink]:
    """Detecte les liens entre topics via les relations cross-doc entre claims."""
    from collections import defaultdict

    # Mapper perspective_id -> topic_id
    persp_to_topic = {}
    for t in topics:
        for pid in t.perspectives:
            persp_to_topic[pid] = t.topic_id

    rel_types = ["CHAINS_TO", "REFINES", "CONTRADICTS", "QUALIFIES", "COMPLEMENTS", "EVOLVES_TO", "SPECIALIZES"]
    cross_counts: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    with driver.session() as session:
        for rel_type in rel_types:
            result = session.run(f"""
                MATCH (p1:Perspective {{tenant_id: $tid}})-[:INCLUDES_CLAIM]->(c1:Claim)
                      -[:{rel_type}]->
                      (c2:Claim)<-[:INCLUDES_CLAIM]-(p2:Perspective {{tenant_id: $tid}})
                WHERE p1 <> p2
                RETURN p1.perspective_id AS pid1, p2.perspective_id AS pid2, count(*) AS cnt
            """, tid=tenant_id)
            for rec in result:
                t1 = persp_to_topic.get(rec["pid1"])
                t2 = persp_to_topic.get(rec["pid2"])
                if t1 and t2 and t1 != t2:
                    key = (min(t1, t2), max(t1, t2))
                    cross_counts[key][rel_type] += rec["cnt"]

    # Construire les TopicLinks
    links = []
    for (tid1, tid2), rels in cross_counts.items():
        # Le role narratif dominant = celui avec le plus de relations
        dominant_rel = max(rels, key=rels.get)
        narrative_role = RELATION_TO_NARRATIVE_ROLE.get(dominant_rel, "related")
        total_weight = sum(rels.values())

        links.append(TopicLink(
            from_topic=tid1,
            to_topic=tid2,
            relation_type=dominant_rel,
            weight=total_weight,
            narrative_role=narrative_role,
        ))

    links.sort(key=lambda l: l.weight, reverse=True)
    logger.info(f"Inter-topic links: {len(links)} (from {len(cross_counts)} topic pairs)")
    return links


def compute_reading_order(topics: list[NarrativeTopic], links: list[TopicLink]) -> None:
    """Calcule un ordre de lecture base sur le graphe inter-topics.

    Strategie : topological sort approximatif sur les liens "leads_to" (CHAINS_TO).
    Les topics sources (peu de liens entrants) sont lus en premier.
    Les topics puits (beaucoup de liens entrants) sont lus en dernier.
    Fallback par nombre de claims decroissant si pas de structure claire.
    """
    import networkx as nx

    # Construire un digraphe pondere par les leads_to
    DG = nx.DiGraph()
    topic_ids = {t.topic_id for t in topics}
    for t in topics:
        DG.add_node(t.topic_id, claims=t.claim_count)

    for link in links:
        if link.narrative_role == "leads_to" and link.from_topic in topic_ids and link.to_topic in topic_ids:
            DG.add_edge(link.from_topic, link.to_topic, weight=link.weight)

    # Trier par in-degree (sources d'abord) puis par claims decroissant
    scored = []
    for t in topics:
        in_deg = DG.in_degree(t.topic_id) if t.topic_id in DG else 0
        out_deg = DG.out_degree(t.topic_id) if t.topic_id in DG else 0
        # Score : sources (out > in) d'abord, hubs (out ~ in) ensuite, puits (in > out) a la fin
        # A claims egal, les plus gros topics passent avant
        source_score = out_deg - in_deg
        scored.append((t, -source_score, -t.claim_count))

    scored.sort(key=lambda x: (x[1], x[2]))

    for order, (t, _, _) in enumerate(scored):
        t.reading_order = order
        logger.debug(f"  Reading order {order}: {t.topic_id} ({t.narrative_label[:40]})")

    logger.info(f"Reading order computed for {len(topics)} topics")


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

def persist_topics(
    driver,
    topics: list[NarrativeTopic],
    links: list[TopicLink],
    roots: list[AtlasRoot],
    tenant_id: str,
) -> dict:
    """Persister les AtlasRoots + NarrativeTopics + liens dans Neo4j."""
    stats = {"roots": 0, "created": 0, "perspective_links": 0, "subject_links": 0, "inter_topic_links": 0}

    with driver.session() as session:
        # Cleanup
        deleted_nt = session.run(
            "MATCH (nt:NarrativeTopic {tenant_id: $tid}) DETACH DELETE nt RETURN count(nt) AS cnt",
            tid=tenant_id,
        ).single()["cnt"]
        deleted_ar = session.run(
            "MATCH (ar:AtlasRoot {tenant_id: $tid}) DETACH DELETE ar RETURN count(ar) AS cnt",
            tid=tenant_id,
        ).single()["cnt"]
        if deleted_nt or deleted_ar:
            logger.info(f"Deleted {deleted_nt} NarrativeTopics + {deleted_ar} AtlasRoots")

        # AtlasRoots (level 0)
        for root in roots:
            session.run("""
                CREATE (ar:AtlasRoot {
                    root_id: $rid,
                    tenant_id: $tenant,
                    canonical_name: $name,
                    topic_count: $n_topics,
                    claim_count: $claims,
                    affinity: $affinity,
                    created_at: datetime()
                })
            """,
                rid=root.root_id, tenant=tenant_id,
                name=root.canonical_name,
                n_topics=len(root.topic_ids), claims=root.claim_count,
                affinity=root.affinity,
            )
            stats["roots"] += 1

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
                    reading_order: $order,
                    created_at: datetime()
                })
            """,
                tid=t.topic_id, tenant=tenant_id,
                label=t.narrative_label, summary=t.narrative_summary,
                claims=t.claim_count, n_persp=len(t.perspectives), n_subj=len(t.subjects),
                persp_labels=t.perspective_labels, subj_names=t.subject_names,
                order=t.reading_order,
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

            # Lier au AtlasRoot (level 0 → level 1)
            if t.atlas_root_id:
                session.run("""
                    MATCH (ar:AtlasRoot {root_id: $rid, tenant_id: $tenant})
                    MATCH (nt:NarrativeTopic {topic_id: $tid, tenant_id: $tenant})
                    CREATE (ar)-[:HAS_CHAPTER {reading_order: $order}]->(nt)
                """, rid=t.atlas_root_id, tid=t.topic_id, tenant=tenant_id, order=t.reading_order)

        # Liens inter-topics (NARRATIVE_LINK)
        for link in links:
            session.run("""
                MATCH (nt1:NarrativeTopic {topic_id: $from_tid, tenant_id: $tenant})
                MATCH (nt2:NarrativeTopic {topic_id: $to_tid, tenant_id: $tenant})
                CREATE (nt1)-[:NARRATIVE_LINK {
                    relation_type: $rel_type,
                    narrative_role: $role,
                    weight: $weight
                }]->(nt2)
            """,
                from_tid=link.from_topic, to_tid=link.to_topic, tenant=tenant_id,
                rel_type=link.relation_type, role=link.narrative_role, weight=link.weight,
            )
            stats["inter_topic_links"] += 1

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

    # 5. Atlas hierarchy (level 0)
    logger.info(f"\nBuilding Atlas hierarchy...")
    roots = build_atlas_roots(topics, removed, edges, len(perspectives))

    # 6. Inter-topic links
    logger.info(f"\nDetecting inter-topic links...")
    links = detect_inter_topic_links(driver, topics, args.tenant)

    # 7. Reading order
    compute_reading_order(topics, links)

    # 8. LLM labelling
    logger.info(f"\nLabelling {len(topics)} topics...")
    label_topics_llm(topics, skip_llm=args.skip_llm)

    # 9. Display
    logger.info(f"\n{'='*60}")
    logger.info(f"ATLAS STRUCTURE")
    logger.info(f"{'='*60}")

    for root in roots:
        root_topics = sorted(
            [t for t in topics if t.atlas_root_id == root.root_id],
            key=lambda t: t.reading_order,
        )
        logger.info(f"\n{root.canonical_name} ({root.claim_count} claims)")
        for t in root_topics:
            logger.info(
                f"  [{t.reading_order:>2}] {t.narrative_label}"
                f"\n       {len(t.perspectives)}P x {len(t.subjects)}S = {t.claim_count} claims"
                f"\n       Subjects: {t.subject_names}"
            )
            if t.narrative_summary:
                logger.info(f"       {t.narrative_summary[:100]}")

    if links:
        logger.info(f"\n{'='*60}")
        logger.info(f"INTER-TOPIC LINKS: {len(links)}")
        logger.info(f"{'='*60}")
        for link in links[:15]:
            from_label = next((t.narrative_label for t in topics if t.topic_id == link.from_topic), "?")[:30]
            to_label = next((t.narrative_label for t in topics if t.topic_id == link.to_topic), "?")[:30]
            logger.info(
                f"  {from_label} --[{link.narrative_role}:{link.weight}]--> {to_label}"
            )

    # 10. Persist
    if not args.dry_run:
        logger.info(f"\nPersisting {len(roots)} roots + {len(topics)} topics + {len(links)} links...")
        stats = persist_topics(driver, topics, links, roots, args.tenant)
        logger.info(f"Persisted: {stats}")
    else:
        logger.info("\n[DRY RUN] Skipping persistence")

    elapsed = round(time.time() - start, 1)
    logger.info(f"\nDone in {elapsed}s")
    driver.close()


if __name__ == "__main__":
    main()
