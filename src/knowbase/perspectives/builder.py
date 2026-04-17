# src/knowbase/perspectives/builder.py
"""
PerspectiveBuilder V2 — Construction theme-scoped des Perspectives.

Algorithme :
1. Charger TOUS les claims du tenant (avec embeddings, doc_id, facets)
2. Reduction UMAP (1024 -> 15 dim) sur les embeddings
3. Clustering HDBSCAN par densite
4. Pour chaque cluster valide :
   - Filtrer qualite (>= min_doc_count)
   - Calculer linked_subject_ids via doc_id -> DocumentContext -> Subject
   - Labellisation LLM (Haiku)
   - Embedding composite (label + claims centroid)
   - Metriques (claim_count, doc_count, tension_count)
5. Persister les Perspectives + relations dans Neo4j

Aucun hardcoding lexical, aucune liste de mots, aucun pattern domaine.
Multilingue par construction (E5-large embeddings).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .models import Perspective, PerspectiveConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Chargement des claims
# ---------------------------------------------------------------------------

def load_all_claims_with_embeddings(
    driver, tenant_id: str,
) -> List[Dict[str, Any]]:
    """Charge tous les claims du tenant avec embeddings, doc_id et facets."""
    logger.info(f"[PERSPECTIVE:BUILD] Loading all claims for tenant={tenant_id}...")
    with driver.session() as session:
        result = session.run("""
            MATCH (c:Claim {tenant_id: $tid})
            WHERE c.embedding IS NOT NULL
            OPTIONAL MATCH (c)-[:BELONGS_TO_FACET]->(f:Facet)
            RETURN c.claim_id AS claim_id,
                   c.text AS text,
                   c.doc_id AS doc_id,
                   c.confidence AS confidence,
                   c.embedding AS embedding,
                   collect(DISTINCT f.facet_name) AS facet_names
        """, tid=tenant_id)

        claims = []
        for r in result:
            claims.append({
                "claim_id": r["claim_id"],
                "text": r["text"] or "",
                "doc_id": r["doc_id"] or "",
                "confidence": r["confidence"] or 0.5,
                "embedding": r["embedding"],
                "facet_names": [f for f in r["facet_names"] if f],
            })

    logger.info(f"[PERSPECTIVE:BUILD] Loaded {len(claims)} claims")
    return claims


# ---------------------------------------------------------------------------
# 2. Mapping doc_id -> sujets
# ---------------------------------------------------------------------------

def load_doc_to_subjects_map(driver, tenant_id: str) -> Dict[str, List[Tuple[str, str]]]:
    """
    Construit un mapping doc_id -> [(subject_id, subject_name), ...]

    Le sujet d'un doc peut etre un SubjectAnchor (via ABOUT_SUBJECT) ou un
    ComparableSubject (via ABOUT_COMPARABLE).
    """
    logger.info("[PERSPECTIVE:BUILD] Loading doc -> subjects map...")
    doc_to_subjects: Dict[str, List[Tuple[str, str]]] = defaultdict(list)

    with driver.session() as session:
        # SubjectAnchors
        result = session.run("""
            MATCH (sa:SubjectAnchor)<-[:ABOUT_SUBJECT]-(dc:DocumentContext)
            RETURN sa.subject_id AS sid, sa.canonical_name AS name, dc.doc_id AS doc_id
        """)
        for r in result:
            if r["doc_id"] and r["sid"]:
                doc_to_subjects[r["doc_id"]].append((r["sid"], r["name"] or ""))

        # ComparableSubjects
        result = session.run("""
            MATCH (cs:ComparableSubject {tenant_id: $tid})<-[:ABOUT_COMPARABLE]-(dc:DocumentContext)
            RETURN cs.subject_id AS sid, cs.canonical_name AS name, dc.doc_id AS doc_id
        """, tid=tenant_id)
        for r in result:
            if r["doc_id"] and r["sid"]:
                doc_to_subjects[r["doc_id"]].append((r["sid"], r["name"] or ""))

    logger.info(f"[PERSPECTIVE:BUILD] Doc->subjects map: {len(doc_to_subjects)} docs")
    return dict(doc_to_subjects)


# ---------------------------------------------------------------------------
# 3. Tensions entre claims
# ---------------------------------------------------------------------------

def load_tensions_map(driver, tenant_id: str) -> Dict[str, set]:
    """Construit un mapping claim_id -> set(claim_ids en tension)."""
    tensions: Dict[str, set] = defaultdict(set)
    with driver.session() as session:
        result = session.run("""
            MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS|REFINES|QUALIFIES]->(c2:Claim)
            RETURN c1.claim_id AS from_id, c2.claim_id AS to_id
        """, tid=tenant_id)
        for r in result:
            if r["from_id"] and r["to_id"]:
                tensions[r["from_id"]].add(r["to_id"])
                tensions[r["to_id"]].add(r["from_id"])
    return dict(tensions)


# ---------------------------------------------------------------------------
# 4. UMAP + HDBSCAN
# ---------------------------------------------------------------------------

def reduce_and_cluster(
    embeddings: np.ndarray,
    config: PerspectiveConfig,
) -> np.ndarray:
    """Reduction UMAP puis clustering HDBSCAN."""
    import umap
    import hdbscan

    logger.info(
        f"[PERSPECTIVE:BUILD] UMAP {embeddings.shape[1]}D -> {config.umap_n_components}D..."
    )
    start = time.time()
    reducer = umap.UMAP(
        n_components=config.umap_n_components,
        n_neighbors=config.umap_n_neighbors,
        min_dist=config.umap_min_dist,
        metric="cosine",
        random_state=42,
    )
    reduced = reducer.fit_transform(embeddings)
    logger.info(f"[PERSPECTIVE:BUILD] UMAP done in {time.time() - start:.1f}s")

    logger.info(
        f"[PERSPECTIVE:BUILD] HDBSCAN min_cluster_size={config.hdbscan_min_cluster_size}..."
    )
    start = time.time()
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=config.hdbscan_min_cluster_size,
        min_samples=config.hdbscan_min_samples,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(reduced)
    logger.info(f"[PERSPECTIVE:BUILD] HDBSCAN done in {time.time() - start:.1f}s")

    return labels


# ---------------------------------------------------------------------------
# 5. Labellisation LLM
# ---------------------------------------------------------------------------

LABEL_PROMPT = """Analyze these claims and identify the THEMATIC AXIS that unites them.

Sample claims:
{claims_text}

Associated facets: {facets_text}

Respond in strict JSON only:
{{"label": "thematic axis in 3-6 words", "description": "1 short sentence", "keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"]}}

RULES:
- Label MUST be a thematic axis (e.g., "Authorization & Access Control", "Data Lifecycle Management", "Logistics Planning"), NOT a product or proper name
- Avoid SAP-specific or domain-specific names unless they describe the theme itself
- Description in the SAME LANGUAGE as the claims (auto-detect)
- 5 keywords for semantic matching
- Respond ONLY with valid JSON, no markdown, no surrounding text"""


def label_cluster_with_llm(
    sample_claims: List[str], dominant_facets: List[Tuple[str, int]],
) -> Dict[str, Any]:
    """Labellise un cluster via llm_router (vLLM burst > Ollama > Anthropic)."""
    claims_text = "\n".join(f"- {c[:200]}" for c in sample_claims[:7])
    facets_text = ", ".join(f"{f}({n})" for f, n in dominant_facets[:3]) or "none"

    prompt = LABEL_PROMPT.format(claims_text=claims_text, facets_text=facets_text)

    try:
        from knowbase.common.llm_router import get_llm_router, TaskType
        router = get_llm_router()
        result = router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
        )
        text = result.text if hasattr(result, "text") else str(result)

        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            data = json.loads(m.group())
            return {
                "label": data.get("label", "Unlabeled"),
                "description": data.get("description", ""),
                "keywords": data.get("keywords", []),
            }
    except Exception as e:
        logger.warning(f"[PERSPECTIVE:LABEL] LLM call failed: {e}")

    return {"label": "Unlabeled", "description": "", "keywords": []}


# ---------------------------------------------------------------------------
# 6. Embedding composite
# ---------------------------------------------------------------------------

def compute_perspective_embedding(
    label: str,
    keywords: List[str],
    representative_texts: List[str],
    cluster_claim_embeddings: List[np.ndarray],
) -> Optional[List[float]]:
    """
    Calcule l'embedding composite : 25% label + 75% claims centroid.

    Le label est encode via E5-large, le centroid est calcule sur les
    embeddings deja disponibles dans les claims.
    """
    try:
        from knowbase.common.clients import get_sentence_transformer
        model = get_sentence_transformer()

        # Label embedding
        label_text = f"passage: {label}. {' '.join(keywords[:5])}"
        label_vec = np.array(model.encode([label_text])[0])

        # Claims centroid (depuis les embeddings deja en memoire)
        if cluster_claim_embeddings:
            centroid = np.mean(np.array(cluster_claim_embeddings), axis=0)
        else:
            centroid = label_vec

        # Composite : 25% label + 75% centroid
        composite = 0.25 * label_vec + 0.75 * centroid
        norm = np.linalg.norm(composite)
        if norm > 0:
            composite = composite / norm

        return composite.tolist()
    except Exception as e:
        logger.warning(f"[PERSPECTIVE:EMBEDDING] Failed: {e}")
        return None


# ---------------------------------------------------------------------------
# 7. Pipeline complet (theme-scoped global)
# ---------------------------------------------------------------------------

def build_all_perspectives(
    driver,
    tenant_id: str,
    config: Optional[PerspectiveConfig] = None,
    skip_llm: bool = False,
) -> Tuple[List[Perspective], Dict[str, List[str]]]:
    """
    Construit toutes les Perspectives theme-scoped pour un tenant.

    Retourne (perspectives, claim_assignments)
    ou claim_assignments = {perspective_id: [claim_ids]}
    """
    config = config or PerspectiveConfig()

    # 1. Charger toutes les donnees
    claims = load_all_claims_with_embeddings(driver, tenant_id)
    if not claims:
        logger.warning("[PERSPECTIVE:BUILD] No claims found")
        return [], {}

    doc_to_subjects = load_doc_to_subjects_map(driver, tenant_id)
    tensions_map = load_tensions_map(driver, tenant_id)

    # 2. Construire la matrice d'embeddings
    embeddings = np.array([c["embedding"] for c in claims])
    logger.info(f"[PERSPECTIVE:BUILD] Embeddings matrix: {embeddings.shape}")

    # 3. Clustering
    labels = reduce_and_cluster(embeddings, config)

    unique_labels = set(labels.tolist())
    n_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
    n_noise = int(np.sum(labels == -1))
    logger.info(
        f"[PERSPECTIVE:BUILD] Clustering: {n_clusters} clusters, "
        f"{n_noise} noise ({n_noise/len(claims)*100:.1f}%)"
    )

    # 4. Trier les clusters par taille (les plus gros d'abord)
    cluster_sizes = []
    for cid in unique_labels:
        if cid == -1:
            continue
        size = int(np.sum(labels == cid))
        cluster_sizes.append((int(cid), size))
    cluster_sizes.sort(key=lambda x: -x[1])

    # 5. Pour chaque cluster, construire la Perspective
    perspectives: List[Perspective] = []
    claim_assignments: Dict[str, List[str]] = {}

    n_to_process = min(len(cluster_sizes), config.max_clusters_to_label)
    logger.info(
        f"[PERSPECTIVE:BUILD] Processing top {n_to_process} clusters "
        f"(filter: doc_count >= {config.min_doc_count})"
    )

    for idx, (cluster_id, _) in enumerate(cluster_sizes[:n_to_process], 1):
        # Recuperer les claims du cluster
        cluster_indices = [i for i in range(len(claims)) if labels[i] == cluster_id]
        cluster_claims = [claims[i] for i in cluster_indices]
        cluster_embeddings = [np.array(c["embedding"]) for c in cluster_claims]

        # Filtres qualite
        doc_ids = set(c["doc_id"] for c in cluster_claims if c["doc_id"])
        n_docs = len(doc_ids)

        if n_docs < config.min_doc_count:
            logger.debug(
                f"  [{idx}/{n_to_process}] Cluster {cluster_id} dropped: "
                f"only {n_docs} docs (min={config.min_doc_count})"
            )
            continue

        if config.drop_clusters_with_single_doc and n_docs == 1:
            continue

        # Metriques
        claim_count = len(cluster_claims)
        cluster_claim_ids = set(c["claim_id"] for c in cluster_claims)
        tension_count = sum(
            1 for cid in cluster_claim_ids
            if cid in tensions_map and tensions_map[cid] & cluster_claim_ids
        )

        # Facets dominantes
        facet_counter = Counter()
        for c in cluster_claims:
            for fn in c["facet_names"]:
                facet_counter[fn] += 1
        dominant_facets = facet_counter.most_common(5)
        dominant_facet_names = [f for f, _ in dominant_facets]

        # Claims representatifs (top par confidence, diversifies)
        sorted_claims = sorted(cluster_claims, key=lambda c: -(c.get("confidence") or 0.5))
        representative = sorted_claims[:config.n_representative_claims]
        representative_texts = [c["text"][:300] for c in representative]
        representative_claim_ids = [c["claim_id"] for c in representative]

        # Linked subjects (via doc_id -> subject)
        linked_subjects: Dict[str, str] = {}
        for doc_id in doc_ids:
            for sid, sname in doc_to_subjects.get(doc_id, []):
                if sid not in linked_subjects:
                    linked_subjects[sid] = sname

        linked_subject_ids = list(linked_subjects.keys())
        linked_subject_names = [linked_subjects[sid] for sid in linked_subject_ids]

        # Labellisation LLM
        if skip_llm:
            label_data = {
                "label": f"Cluster {cluster_id} ({dominant_facet_names[0] if dominant_facet_names else 'mixed'})",
                "description": "",
                "keywords": dominant_facet_names[:5],
            }
        else:
            label_data = label_cluster_with_llm(representative_texts, dominant_facets)

        logger.info(
            f"  [{idx}/{n_to_process}] Cluster {cluster_id}: "
            f"{claim_count} claims, {n_docs} docs, "
            f"{len(linked_subject_ids)} subjects, {tension_count} tensions "
            f"-> {label_data['label']}"
        )

        # Creer la Perspective
        p = Perspective.create_new(
            tenant_id=tenant_id,
            label=label_data["label"],
            cluster_id_in_run=cluster_id,
            description=label_data.get("description", ""),
            keywords=label_data.get("keywords", []),
        )
        p.claim_count = claim_count
        p.doc_count = n_docs
        p.tension_count = tension_count
        p.dominant_facet_names = dominant_facet_names
        p.representative_claim_ids = representative_claim_ids
        p.representative_texts = representative_texts
        p.linked_subject_ids = linked_subject_ids
        p.linked_subject_names = linked_subject_names

        # Importance score
        import math
        p.importance_score = (
            math.log(1 + p.claim_count)
            + 1.5 * math.log(1 + p.doc_count)
            + 0.5 * p.tension_count
        )

        # Embedding composite
        if not skip_llm:
            p.embedding = compute_perspective_embedding(
                p.label, p.keywords, representative_texts, cluster_embeddings,
            )

        perspectives.append(p)
        claim_assignments[p.perspective_id] = [c["claim_id"] for c in cluster_claims]

    logger.info(
        f"[PERSPECTIVE:BUILD] Done: {len(perspectives)} perspectives created "
        f"(claims totaux: {sum(p.claim_count for p in perspectives)})"
    )
    return perspectives, claim_assignments
