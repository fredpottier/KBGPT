# src/knowbase/perspectives/scorer.py
"""
Scoring et selection des Perspectives V2 (theme-scoped) au runtime.

Differences avec la V1 :
- Plus de filtre par subject_id : on charge TOUTES les Perspectives du tenant
- Le subject identifie devient un BONUS (Perspectives qui touchent ce sujet
  via TOUCHES_SUBJECT sont boostees), pas un filtre dur
- La selection se fait purement sur le scoring semantique + signaux structurels

Cette approche permet de repondre a des questions cross-subject qui touchent
plusieurs ComparableSubjects (ex: "comparaison sécurité S/4HANA vs CPE").
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Tuple

import numpy as np

from .models import Perspective, ScoredPerspective

logger = logging.getLogger(__name__)


# Hard gate semantique
SEMANTIC_HARD_GATE = 0.15
TENSION_EXCEPTION_THRESHOLD = 2


# ---------------------------------------------------------------------------
# 1. Resolution des subject_ids (signal de boost, pas filtre)
# ---------------------------------------------------------------------------

def resolve_subject_ids_from_claims(
    kg_claim_results: List[Dict],
    tenant_id: str,
) -> Tuple[List[str], str]:
    """
    Identifie les subject_ids touches par les claims KG d'une question.

    Ces subject_ids servent de SIGNAL de boost pour le scoring,
    pas de filtre dur. Une question peut tres bien avoir une reponse
    valide via des Perspectives qui touchent d'autres sujets.
    """
    if not kg_claim_results:
        return [], "fallback"

    doc_ids = set()
    for claim in kg_claim_results:
        doc_id = claim.get("doc_id") or claim.get("source_file", "")
        if doc_id:
            doc_ids.add(doc_id)

    if not doc_ids:
        return [], "fallback"

    try:
        from neo4j import GraphDatabase
        uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            result = session.run("""
                UNWIND $doc_ids AS did
                MATCH (dc:DocumentContext {doc_id: did})-[:ABOUT_SUBJECT]->(sa:SubjectAnchor)
                WITH sa.subject_id AS sid, sa.canonical_name AS name, count(DISTINCT did) AS doc_match
                RETURN sid, name, doc_match
                ORDER BY doc_match DESC
                LIMIT 5
            """, doc_ids=list(doc_ids))
            candidates = [dict(r) for r in result]
        driver.close()
    except Exception as e:
        logger.warning(f"[PERSPECTIVE:RESOLVE] Neo4j query failed: {e}")
        return [], "fallback"

    if not candidates:
        return [], "fallback"

    subject_ids = [c["sid"] for c in candidates[:3]]
    mode = "single" if len(subject_ids) == 1 else ("multi" if len(subject_ids) > 1 else "fallback")

    logger.info(
        f"[PERSPECTIVE:RESOLVE] mode={mode}, subjects={[c['name'] for c in candidates[:3]]}"
    )
    return subject_ids, mode


# ---------------------------------------------------------------------------
# 2. Chargement des Perspectives (toutes, sans filtre subject)
# ---------------------------------------------------------------------------

def load_all_perspectives(tenant_id: str) -> List[Perspective]:
    """
    Charge TOUTES les Perspectives d'un tenant.

    Plus de filtre par subject_id : la couche V2 est theme-scoped,
    le filtrage par sujet se fait via le boost de scoring si pertinent.
    """
    try:
        from neo4j import GraphDatabase
        uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            result = session.run("""
                MATCH (p:Perspective {tenant_id: $tid})
                RETURN p
            """, tid=tenant_id)
            perspectives = []
            for record in result:
                node = record["p"]
                props = dict(node)
                perspectives.append(Perspective.from_neo4j_record(props))
        driver.close()
        logger.info(f"[PERSPECTIVE:LOAD] {len(perspectives)} perspectives loaded for tenant={tenant_id}")
        return perspectives

    except Exception as e:
        logger.warning(f"[PERSPECTIVE:LOAD] Failed: {e}")
        return []


# ---------------------------------------------------------------------------
# 3. Scoring multi-signaux
# ---------------------------------------------------------------------------

def score_perspectives(
    question_embedding: List[float],
    question: str,
    perspectives: List[Perspective],
    boost_subject_ids: List[str] = None,
) -> List[ScoredPerspective]:
    """
    Score chaque Perspective contre la question.

    Signaux :
    - Cosine similarity entre embedding Perspective et question (E5-large multilingue)
    - Tension bonus (+0.15 si tension_count > 0)
    - Diversity bonus (+0.10 si doc_count >= 3)
    - Importance weight (importance_score normalise * 0.10)
    - Subject overlap bonus (+0.20 si la Perspective touche un sujet identifie)

    Le subject overlap est un BOOST, pas un filtre. Une Perspective sans
    overlap reste eligible si son score semantique est suffisant.
    """
    q_vec = np.array(question_embedding) if question_embedding else None
    boost_set = set(boost_subject_ids or [])

    scored = []
    for p in perspectives:
        # Semantic score (cross-lingue par construction)
        semantic = 0.0
        if q_vec is not None and p.embedding:
            p_vec = np.array(p.embedding)
            dot = np.dot(q_vec, p_vec)
            norms = np.linalg.norm(q_vec) * np.linalg.norm(p_vec)
            semantic = float(dot / norms) if norms > 0 else 0.0

        # Bonuses structurels
        tension_bonus = 0.15 if p.tension_count > 0 else 0.0
        diversity_bonus = 0.10 if p.doc_count >= 3 else 0.0

        # Importance (log-normalise)
        import math
        importance_norm = min(p.importance_score / 10.0, 1.0)  # cap a 10
        importance_bonus = importance_norm * 0.10

        # Subject overlap : boost si la Perspective touche au moins un sujet identifie
        subject_bonus = 0.0
        if boost_set and p.linked_subject_ids:
            overlap = boost_set.intersection(set(p.linked_subject_ids))
            if overlap:
                subject_bonus = 0.20

        total = semantic + tension_bonus + diversity_bonus + importance_bonus + subject_bonus

        scored.append(ScoredPerspective(
            perspective=p,
            relevance_score=total,
            semantic_score=semantic,
            subject_overlap_bonus=subject_bonus,
        ))

    return sorted(scored, key=lambda s: -s.relevance_score)


# ---------------------------------------------------------------------------
# 4. Selection
# ---------------------------------------------------------------------------

def select_perspectives(
    scored: List[ScoredPerspective],
    min_count: int = 3,
    max_count: int = 5,
) -> List[ScoredPerspective]:
    """
    Selectionne les Perspectives les plus pertinentes.

    Hard gate : semantic_score < 0.15 -> rejet (sauf tension forte ou subject overlap).
    """
    selected = []

    for sp in scored:
        if sp.semantic_score < SEMANTIC_HARD_GATE:
            # Exception 1 : tension forte
            if sp.perspective.tension_count >= TENSION_EXCEPTION_THRESHOLD:
                pass
            # Exception 2 : subject overlap (Perspective specifiquement liee au sujet de la question)
            elif sp.subject_overlap_bonus > 0:
                pass
            else:
                continue

        selected.append(sp)
        if len(selected) >= max_count:
            break

    # Si pas assez, relacher le gate
    if len(selected) < min_count:
        for sp in scored:
            if sp not in selected:
                selected.append(sp)
                if len(selected) >= min_count:
                    break

    return selected[:max_count]
