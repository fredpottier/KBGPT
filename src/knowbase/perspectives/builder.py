# src/knowbase/perspectives/builder.py
"""
PerspectiveBuilder — Construction batch des Perspectives depuis le KG.

Algorithme :
1. Collecte des claims d'un sujet (via doc_id join)
2. Vecteurs composites (facet membership + embedding)
3. Clustering agglomeratif
4. Filtrage qualite
5. Labellisation LLM (Haiku)
6. Metriques
7. Embedding composite (25% label + 75% claims centroid)

Reutilise les patterns de facets/consolidator.py et facets/prototype_builder.py.
Ne cree pas son propre client LLM — utilise llm_router existant.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from .models import Perspective, PerspectiveConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Collecte
# ---------------------------------------------------------------------------

def collect_claims_for_subject(
    driver, tenant_id: str, subject_id: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Recupere les claims d'un sujet avec leurs facets et embeddings.

    Le chemin est : SubjectAnchor <-[:ABOUT_SUBJECT]- DocumentContext (doc_id)
                    Claim (doc_id) — jointure par propriete doc_id

    Returns:
        (claims, doc_ids) ou claims = [{claim_id, text, doc_id, facet_ids, facet_names, embedding, claim_type}]
    """
    with driver.session() as session:
        # Trouver les doc_ids du sujet (SubjectAnchor ou ComparableSubject)
        result = session.run("""
            OPTIONAL MATCH (sa:SubjectAnchor {subject_id: $sid})<-[:ABOUT_SUBJECT]-(dc1:DocumentContext)
            OPTIONAL MATCH (cs:ComparableSubject {subject_id: $sid})<-[:ABOUT_COMPARABLE]-(dc2:DocumentContext)
            WITH collect(DISTINCT dc1.doc_id) + collect(DISTINCT dc2.doc_id) AS all_doc_ids
            RETURN [x IN all_doc_ids WHERE x IS NOT NULL] AS doc_ids
        """, sid=subject_id)
        doc_ids = result.single()["doc_ids"]

        if not doc_ids:
            return [], []

        # Recuperer les claims avec facets
        result = session.run("""
            UNWIND $doc_ids AS did
            MATCH (c:Claim {tenant_id: $tid, doc_id: did})
            OPTIONAL MATCH (c)-[:BELONGS_TO_FACET]->(f:Facet)
            RETURN c.claim_id AS claim_id,
                   c.text AS text,
                   c.doc_id AS doc_id,
                   c.claim_type AS claim_type,
                   c.confidence AS confidence,
                   collect(DISTINCT f.facet_id) AS facet_ids,
                   collect(DISTINCT f.facet_name) AS facet_names
        """, doc_ids=doc_ids, tid=tenant_id)

        claims = []
        for r in result:
            claims.append({
                "claim_id": r["claim_id"],
                "text": r["text"] or "",
                "doc_id": r["doc_id"] or "",
                "claim_type": r["claim_type"] or "",
                "confidence": r["confidence"] or 0.5,
                "facet_ids": [f for f in r["facet_ids"] if f],
                "facet_names": [f for f in r["facet_names"] if f],
            })

        # Recuperer les embeddings
        result = session.run("""
            UNWIND $doc_ids AS did
            MATCH (c:Claim {tenant_id: $tid, doc_id: did})
            WHERE c.embedding IS NOT NULL
            RETURN c.claim_id AS claim_id, c.embedding AS embedding
        """, doc_ids=doc_ids, tid=tenant_id)

        embedding_map = {}
        for r in result:
            embedding_map[r["claim_id"]] = r["embedding"]

        for claim in claims:
            claim["embedding"] = embedding_map.get(claim["claim_id"])

        # Recuperer les tensions internes
        result = session.run("""
            UNWIND $doc_ids AS did
            MATCH (c1:Claim {tenant_id: $tid, doc_id: did})-[r:CONTRADICTS|REFINES|QUALIFIES]->(c2:Claim {tenant_id: $tid})
            WHERE c2.doc_id IN $doc_ids
            RETURN c1.claim_id AS from_id, c2.claim_id AS to_id, type(r) AS rel_type
        """, doc_ids=doc_ids, tid=tenant_id)

        tensions = [(r["from_id"], r["to_id"], r["rel_type"]) for r in result]
        logger.info(
            f"[PERSPECTIVE:COLLECT] subject={subject_id}: "
            f"{len(claims)} claims, {len(doc_ids)} docs, "
            f"{len(embedding_map)} embeddings, {len(tensions)} tensions"
        )

    return claims, doc_ids


# ---------------------------------------------------------------------------
# 2. Vecteurs composites
# ---------------------------------------------------------------------------

def build_composite_vectors(
    claims: List[Dict], config: PerspectiveConfig,
) -> Tuple[np.ndarray, List[str]]:
    """
    Construit des vecteurs composites pour le clustering.

    Combine facet membership (one-hot) et embedding semantique.
    """
    # Inventaire des facets
    all_facets = sorted(set(
        fid for c in claims for fid in c.get("facet_ids", [])
    ))
    facet_to_idx = {f: i for i, f in enumerate(all_facets)}
    n_facets = len(all_facets)

    # Claims avec au moins un embedding OU une facet
    valid_claims = []
    for c in claims:
        has_emb = c.get("embedding") is not None
        has_facet = bool(c.get("facet_ids"))
        if has_emb or has_facet:
            valid_claims.append(c)

    if not valid_claims:
        return np.array([]), []

    # Determiner la dimension d'embedding
    emb_dim = 0
    for c in valid_claims:
        if c.get("embedding"):
            emb_dim = len(c["embedding"])
            break

    vectors = []
    claim_ids = []
    for c in valid_claims:
        # Vecteur facet (one-hot)
        facet_vec = np.zeros(n_facets) if n_facets > 0 else np.array([])
        for fid in c.get("facet_ids", []):
            if fid in facet_to_idx:
                facet_vec[facet_to_idx[fid]] = 1.0

        # Vecteur embedding
        if c.get("embedding") and emb_dim > 0:
            emb_vec = np.array(c["embedding"])
        elif emb_dim > 0:
            emb_vec = np.zeros(emb_dim)
        else:
            emb_vec = np.array([])

        # Composite : normaliser puis ponderer
        if n_facets > 0 and np.linalg.norm(facet_vec) > 0:
            facet_vec = facet_vec / np.linalg.norm(facet_vec)
        if emb_dim > 0 and np.linalg.norm(emb_vec) > 0:
            emb_vec = emb_vec / np.linalg.norm(emb_vec)

        composite = np.concatenate([
            facet_vec * config.facet_weight,
            emb_vec * config.embedding_weight,
        ])
        vectors.append(composite)
        claim_ids.append(c["claim_id"])

    return np.array(vectors), claim_ids


# ---------------------------------------------------------------------------
# 3. Clustering
# ---------------------------------------------------------------------------

def cluster_claims(
    vectors: np.ndarray,
    claim_ids: List[str],
    config: PerspectiveConfig,
) -> Dict[int, List[str]]:
    """
    Clustering agglomeratif des claims.

    Returns:
        Dict cluster_label -> [claim_ids]
    """
    if len(vectors) < config.min_cluster_size:
        return {0: claim_ids}

    # Distance cosine
    distances = pdist(vectors, metric="cosine")
    # Remplacer les NaN (vecteurs nuls)
    distances = np.nan_to_num(distances, nan=1.0)

    Z = linkage(distances, method="average")

    # Determiner le nombre de clusters adaptatif
    n_claims = len(claim_ids)
    if n_claims < 30:
        target = config.target_clusters_min
    elif n_claims < 100:
        target = min(config.target_clusters_min + 2, config.target_clusters_max)
    else:
        target = config.target_clusters_max

    labels = fcluster(Z, t=target, criterion="maxclust")

    # Regrouper
    clusters: Dict[int, List[str]] = defaultdict(list)
    for cid, label in zip(claim_ids, labels):
        clusters[int(label)].append(cid)

    # Fusionner les petits clusters
    merged = {}
    small_claims = []
    for label, members in clusters.items():
        if len(members) >= config.min_cluster_size:
            merged[label] = members
        else:
            small_claims.extend(members)

    # Assigner les orphelins au cluster le plus proche
    if small_claims and merged:
        # Calculer les centroids des clusters valides
        id_to_idx = {cid: i for i, cid in enumerate(claim_ids)}
        for cid in small_claims:
            best_label = min(merged.keys(), key=lambda l: len(merged[l]))
            merged[best_label].append(cid)

    if not merged:
        merged = {0: claim_ids}

    logger.info(
        f"[PERSPECTIVE:CLUSTER] {len(claim_ids)} claims -> {len(merged)} clusters "
        f"(sizes: {[len(v) for v in merged.values()]})"
    )
    return merged


# ---------------------------------------------------------------------------
# 4. Labellisation LLM
# ---------------------------------------------------------------------------

LABEL_PROMPT = """Analyse ces claims extraits de documents techniques et identifie le THEME commun.

Claims representatifs :
{claims_text}

Facets associees : {facets_text}

Reponds en JSON strict :
{{"label": "theme en 3-5 mots", "description": "1 phrase descriptive", "negative_boundary": "ce que ce theme n'est PAS", "keywords": ["mot1", "mot2", "mot3", "mot4", "mot5"]}}

REGLES :
- Le label doit etre GENERIQUE (pas de nom de produit specifique)
- La description doit etre comprehensible hors contexte
- Les keywords doivent permettre le matching semantique
- Reponds UNIQUEMENT en JSON, pas de texte avant/apres"""


async def label_perspective_llm(
    claims_sample: List[str],
    facet_names: List[str],
) -> Dict[str, Any]:
    """
    Labellise un cluster de claims via LLM (Haiku).

    Utilise le llm_router existant (pas de client LLM propre).
    """
    from knowbase.common.llm_router import get_llm_router, TaskType

    claims_text = "\n".join(f"- {c[:200]}" for c in claims_sample[:7])
    facets_text = ", ".join(facet_names[:5]) if facet_names else "aucune"

    prompt = LABEL_PROMPT.format(claims_text=claims_text, facets_text=facets_text)

    try:
        router = get_llm_router()
        response = await router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=256,
        )

        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "label": data.get("label", "Unknown"),
                "description": data.get("description", ""),
                "negative_boundary": data.get("negative_boundary", ""),
                "keywords": data.get("keywords", []),
            }
    except Exception as e:
        logger.warning(f"[PERSPECTIVE:LABEL] LLM labelling failed: {e}")

    return {"label": "Unlabeled", "description": "", "negative_boundary": "", "keywords": []}


# ---------------------------------------------------------------------------
# 5. Metriques
# ---------------------------------------------------------------------------

def compute_perspective_metrics(
    claims: List[Dict],
    cluster_claim_ids: List[str],
    all_tensions: List[Tuple],
    total_subject_claims: int,
) -> Dict[str, Any]:
    """Calcule les metriques d'une Perspective."""
    cluster_set = set(cluster_claim_ids)
    cluster_claims = [c for c in claims if c["claim_id"] in cluster_set]

    doc_ids = set(c["doc_id"] for c in cluster_claims if c["doc_id"])
    tension_count = sum(
        1 for from_id, to_id, _ in all_tensions
        if from_id in cluster_set or to_id in cluster_set
    )

    # Facets dominantes
    facet_counter = Counter()
    for c in cluster_claims:
        for fn in c.get("facet_names", []):
            facet_counter[fn] += 1
    facet_ids = list(set(fid for c in cluster_claims for fid in c.get("facet_ids", [])))

    # Claims representatifs (les plus confiants)
    sorted_claims = sorted(cluster_claims, key=lambda c: c.get("confidence", 0.5), reverse=True)
    representative = sorted_claims[:8]

    return {
        "claim_count": len(cluster_claims),
        "doc_count": len(doc_ids),
        "tension_count": tension_count,
        "coverage_ratio": len(cluster_claims) / max(total_subject_claims, 1),
        "source_facet_ids": facet_ids,
        "representative_claim_ids": [c["claim_id"] for c in representative],
        "representative_texts": [c["text"][:200] for c in representative],
        "top_facet_names": [name for name, _ in facet_counter.most_common(3)],
    }


# ---------------------------------------------------------------------------
# 6. Embedding composite
# ---------------------------------------------------------------------------

def compute_perspective_embedding(
    label: str,
    keywords: List[str],
    representative_texts: List[str],
    claims: List[Dict],
    cluster_claim_ids: List[str],
) -> Optional[List[float]]:
    """
    Calcule l'embedding composite : 25% label + 75% claims centroid.

    Utilise le sentence_transformer existant (E5-large).
    """
    try:
        from knowbase.common.clients import get_sentence_transformer
        model = get_sentence_transformer()

        # Label embedding
        label_text = f"passage: {label}. {' '.join(keywords[:5])}"
        label_vec = model.encode([label_text])[0]

        # Claims centroid (claims avec embedding dans le KG)
        cluster_set = set(cluster_claim_ids)
        claim_embeddings = []
        for c in claims:
            if c["claim_id"] in cluster_set and c.get("embedding"):
                claim_embeddings.append(np.array(c["embedding"]))

        if claim_embeddings:
            centroid = np.mean(claim_embeddings, axis=0)
        else:
            # Fallback : encoder les textes representatifs
            texts = [f"passage: {t}" for t in representative_texts[:5]]
            if texts:
                vecs = model.encode(texts)
                centroid = np.mean(vecs, axis=0)
            else:
                centroid = label_vec

        # Composite : 25% label + 75% centroid
        composite = 0.25 * np.array(label_vec) + 0.75 * np.array(centroid)
        norm = np.linalg.norm(composite)
        if norm > 0:
            composite = composite / norm

        return composite.tolist()
    except Exception as e:
        logger.warning(f"[PERSPECTIVE:EMBEDDING] Failed: {e}")
        return None


# ---------------------------------------------------------------------------
# 7. Pipeline complet
# ---------------------------------------------------------------------------

async def build_perspectives_for_subject(
    driver,
    tenant_id: str,
    subject_id: str,
    subject_name: str,
    config: PerspectiveConfig = PerspectiveConfig(),
    skip_llm: bool = False,
) -> Tuple[List[Perspective], Dict[str, List[str]]]:
    """
    Construit les Perspectives pour un sujet.

    Args:
        driver: Neo4j driver
        tenant_id: Tenant ID
        subject_id: Subject ID
        subject_name: Nom du sujet
        config: Configuration du builder
        skip_llm: Si True, ne pas labelliser (pour debug clustering)

    Returns:
        (perspectives, claim_assignments) ou claim_assignments = {perspective_id: [claim_ids]}
    """
    # 1. Collecte
    claims, doc_ids = collect_claims_for_subject(driver, tenant_id, subject_id)
    if len(claims) < config.min_subject_claims:
        logger.info(f"[PERSPECTIVE:BUILD] subject={subject_name}: {len(claims)} claims < seuil {config.min_subject_claims}, skip")
        return [], {}

    # Tensions internes
    with driver.session() as session:
        result = session.run("""
            UNWIND $doc_ids AS did
            MATCH (c1:Claim {tenant_id: $tid, doc_id: did})-[r:CONTRADICTS|REFINES|QUALIFIES]->(c2:Claim {tenant_id: $tid})
            WHERE c2.doc_id IN $doc_ids
            RETURN c1.claim_id AS from_id, c2.claim_id AS to_id, type(r) AS rel_type
        """, doc_ids=doc_ids, tid=tenant_id)
        tensions = [(r["from_id"], r["to_id"], r["rel_type"]) for r in result]

    # 2. Vecteurs composites
    vectors, valid_claim_ids = build_composite_vectors(claims, config)
    if len(vectors) == 0:
        logger.warning(f"[PERSPECTIVE:BUILD] subject={subject_name}: aucun vecteur composite, skip")
        return [], {}

    # 3. Clustering
    clusters = cluster_claims(vectors, valid_claim_ids, config)

    # 4. Construire les Perspectives
    perspectives = []
    claim_assignments = {}

    for cluster_label, cluster_claim_ids in clusters.items():
        # Metriques
        metrics = compute_perspective_metrics(claims, cluster_claim_ids, tensions, len(claims))

        # Labellisation
        if skip_llm:
            label_data = {
                "label": f"Cluster {cluster_label} ({metrics['top_facet_names'][0] if metrics['top_facet_names'] else 'mixed'})",
                "description": "",
                "negative_boundary": "",
                "keywords": metrics["top_facet_names"],
            }
        else:
            label_data = await label_perspective_llm(
                metrics["representative_texts"],
                metrics["top_facet_names"],
            )

        # Creer la Perspective
        p = Perspective.create_new(
            tenant_id=tenant_id,
            subject_id=subject_id,
            subject_name=subject_name,
            label=label_data["label"],
            description=label_data["description"],
            negative_boundary=label_data["negative_boundary"],
            keywords=label_data["keywords"],
        )
        p.claim_count = metrics["claim_count"]
        p.doc_count = metrics["doc_count"]
        p.tension_count = metrics["tension_count"]
        p.coverage_ratio = metrics["coverage_ratio"]
        p.source_facet_ids = metrics["source_facet_ids"]
        p.representative_claim_ids = metrics["representative_claim_ids"]
        p.representative_texts = metrics["representative_texts"]

        # Importance score
        import math
        p.importance_score = (
            math.log(1 + p.claim_count)
            + 1.5 * math.log(1 + p.doc_count)
            + 0.5 * p.tension_count
        )

        # Embedding (optionnel — peut echouer si pas de sentence_transformer)
        if not skip_llm:
            p.embedding = compute_perspective_embedding(
                p.label, p.keywords, p.representative_texts,
                claims, cluster_claim_ids,
            )

        perspectives.append(p)
        claim_assignments[p.perspective_id] = cluster_claim_ids

    logger.info(
        f"[PERSPECTIVE:BUILD] subject={subject_name}: "
        f"{len(perspectives)} perspectives construites "
        f"(claims: {[p.claim_count for p in perspectives]})"
    )
    return perspectives, claim_assignments
