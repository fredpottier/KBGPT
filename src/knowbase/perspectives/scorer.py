# src/knowbase/perspectives/scorer.py
"""
Scoring et selection des Perspectives au runtime.

Responsabilites :
1. Resoudre les subject_ids a partir des claims KG
2. Charger les Perspectives depuis Neo4j
3. Scorer chaque Perspective contre la question (multi-signaux)
4. Selectionner les top 3-5
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from .models import Perspective, ScoredPerspective

logger = logging.getLogger(__name__)

# Hard gate semantique : une Perspective avec semantic_score < HARD_GATE
# ne peut pas etre selectionnee, sauf si tension_count >= TENSION_EXCEPTION
SEMANTIC_HARD_GATE = 0.15
TENSION_EXCEPTION_THRESHOLD = 2


# ---------------------------------------------------------------------------
# 1. Resolution des subject_ids
# ---------------------------------------------------------------------------

def resolve_subject_ids_from_claims(
    kg_claim_results: List[Dict],
    tenant_id: str,
) -> Tuple[List[str], str]:
    """
    Extrait les subject_ids depuis les claims KG.

    Regles :
    - Max 3 sujets retenus
    - Score minimal : sujet lie a >= 3 claims
    - Tie-break : par nombre de claims decroissant
    - Fallback si 0 sujet ou ambiguite forte

    Returns:
        (subject_ids, resolution_mode) ou resolution_mode = "single" | "multi" | "fallback"
    """
    if not kg_claim_results:
        return [], "fallback"

    # Collecter les doc_ids des claims
    doc_ids = set()
    for claim in kg_claim_results:
        doc_id = claim.get("doc_id") or claim.get("source_file", "")
        if doc_id:
            doc_ids.add(doc_id)

    if not doc_ids:
        return [], "fallback"

    # Requete Neo4j pour trouver les SubjectAnchors lies a ces doc_ids
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
                WHERE doc_match >= 1
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

    # Filtrer : au moins 3 claims (approxime par doc_match >= 1 pour l'instant)
    # et verifier que des Perspectives existent
    subject_ids = [c["sid"] for c in candidates[:3]]

    if len(subject_ids) == 1:
        mode = "single"
    elif len(subject_ids) > 1:
        mode = "multi"
    else:
        mode = "fallback"

    logger.info(
        f"[PERSPECTIVE:RESOLVE] mode={mode}, subjects={[c['name'] for c in candidates[:3]]}"
    )
    return subject_ids, mode


# ---------------------------------------------------------------------------
# 2. Chargement des Perspectives
# ---------------------------------------------------------------------------

def load_perspectives(
    subject_ids: List[str],
    tenant_id: str,
) -> List[Perspective]:
    """Charge les Perspectives depuis Neo4j pour les sujets donnes."""
    if not subject_ids:
        return []

    try:
        from neo4j import GraphDatabase
        uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            result = session.run("""
                UNWIND $sids AS sid
                MATCH (p:Perspective {tenant_id: $tid, subject_id: sid})
                RETURN p
            """, sids=subject_ids, tid=tenant_id)

            perspectives = []
            for record in result:
                node = record["p"]
                props = dict(node)
                perspectives.append(Perspective.from_neo4j_record(props))

        driver.close()
        logger.info(f"[PERSPECTIVE:LOAD] {len(perspectives)} perspectives chargees pour {len(subject_ids)} sujets")
        return perspectives

    except Exception as e:
        logger.warning(f"[PERSPECTIVE:LOAD] Failed: {e}")
        return []


# ---------------------------------------------------------------------------
# 3. Scoring multi-signaux
# ---------------------------------------------------------------------------

def _extract_key_terms(question: str) -> List[str]:
    """Extrait les termes cles d'une question pour le keyword matching."""
    # Acronymes (2-6 lettres majuscules)
    acronyms = re.findall(r'\b[A-Z]{2,6}\b', question)
    # Termes techniques (mots > 4 chars, pas des stop words)
    stop = {"dans", "pour", "avec", "quel", "quels", "quelle", "quelles",
            "comment", "pourquoi", "entre", "depuis", "cette", "sont", "fait",
            "from", "with", "what", "which", "about", "that", "this", "have"}
    words = re.findall(r'\b\w{4,}\b', question.lower())
    terms = [w for w in words if w not in stop]
    return list(set(acronyms + terms))


def score_perspectives(
    question_embedding: List[float],
    question: str,
    perspectives: List[Perspective],
) -> List[ScoredPerspective]:
    """
    Score chaque Perspective contre la question (multi-signaux).

    Signaux :
    - Cosine similarity (embedding Perspective vs question)
    - Tension bonus (+0.15 si tension_count > 0)
    - Evolution bonus (+0.10 si evolution data)
    - Diversity bonus (+0.10 si doc_count >= 3)
    - Coverage weight (coverage_ratio * 0.20)
    - Keyword overlap bonus (+0.10 par terme, max +0.30)
    """
    question_terms = _extract_key_terms(question)
    q_vec = np.array(question_embedding) if question_embedding else None

    scored = []
    for p in perspectives:
        # Semantic score
        semantic = 0.0
        if q_vec is not None and p.embedding:
            p_vec = np.array(p.embedding)
            dot = np.dot(q_vec, p_vec)
            norms = np.linalg.norm(q_vec) * np.linalg.norm(p_vec)
            semantic = float(dot / norms) if norms > 0 else 0.0

        # Bonuses
        tension_bonus = 0.15 if p.tension_count > 0 else 0.0
        evolution_bonus = 0.10 if (p.added_claim_count > 0 or p.changed_claim_count > 0) else 0.0
        diversity_bonus = 0.10 if p.doc_count >= 3 else 0.0
        coverage_weight = p.coverage_ratio * 0.20

        # Keyword overlap
        keyword_matches = 0
        for term in question_terms:
            term_lower = term.lower()
            if any(term_lower in rt.lower() for rt in p.representative_texts):
                keyword_matches += 1
            elif term_lower in p.label.lower():
                keyword_matches += 1
            elif any(term_lower in kw.lower() for kw in p.keywords):
                keyword_matches += 1
        keyword_bonus = 0.10 * min(keyword_matches, 3)

        total = semantic + tension_bonus + evolution_bonus + diversity_bonus + coverage_weight + keyword_bonus

        scored.append(ScoredPerspective(
            perspective=p,
            relevance_score=total,
            semantic_score=semantic,
            keyword_overlap=keyword_matches,
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

    Hard gate : semantic_score < 0.15 → rejet (sauf tension forte).
    Toujours garder celles avec tensions meme si score faible.
    """
    selected = []

    for sp in scored:
        # Hard gate semantique
        if sp.semantic_score < SEMANTIC_HARD_GATE:
            if sp.perspective.tension_count >= TENSION_EXCEPTION_THRESHOLD:
                pass  # Exception : garder malgre score faible
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
