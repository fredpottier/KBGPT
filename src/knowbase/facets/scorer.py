"""
FacetEngine V2 — Scorer multi-signal.

Calcule le score d'affinite entre une claim et une facette
a partir de plusieurs signaux convergents :
  - Similarite semantique embedding (poids 0.55)
  - Alignement thematique (poids 0.20)
  - Alignement ClaimKey (poids 0.15)
  - Coherence structurelle (poids 0.10)

Le score determine le promotion_level :
  >= 0.82 et semantic >= 0.75 → STRONG
  >= 0.68 → WEAK
  < 0.68 → pas de lien
"""
from __future__ import annotations

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple

from knowbase.facets.models import FacetAssignment

logger = logging.getLogger(__name__)

# Seuils de promotion
THRESHOLD_STRONG = 0.82
THRESHOLD_STRONG_SEMANTIC = 0.75
THRESHOLD_WEAK = 0.68

# Poids des signaux
WEIGHT_SEMANTIC = 0.55
WEIGHT_THEME = 0.20
WEIGHT_CLAIMKEY = 0.15
WEIGHT_STRUCTURAL = 0.10


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Similarite cosine entre deux vecteurs."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def score_claim_facet(
    claim_embedding: np.ndarray,
    facet_prototype: np.ndarray,
    theme_facet_map: Optional[Dict[str, str]] = None,
    claim_theme_id: Optional[str] = None,
    claimkey_facet_map: Optional[Dict[str, str]] = None,
    claim_claimkey_id: Optional[str] = None,
    facet_id: str = "",
    structural_boost: float = 0.0,
) -> Tuple[float, float, float, float, float]:
    """
    Calcule le score multi-signal d'une claim pour une facette.

    Args:
        claim_embedding: Vecteur 1024d de la claim
        facet_prototype: Vecteur composite 1024d de la facette
        theme_facet_map: Dict theme_id → facet_id (pour theme alignment)
        claim_theme_id: Theme de la claim (si disponible)
        claimkey_facet_map: Dict claimkey_id → facet_id
        claim_claimkey_id: ClaimKey de la claim (si disponible)
        facet_id: ID de la facette evaluee
        structural_boost: Boost de coherence structurelle [0, 1]

    Returns:
        (global_score, semantic_score, theme_score, claimkey_score, structural_score)
    """
    # Signal 1 : Similarite semantique (coeur)
    semantic_score = cosine_similarity(claim_embedding, facet_prototype)

    # Signal 2 : Alignement thematique
    theme_score = 0.0
    if theme_facet_map and claim_theme_id:
        if theme_facet_map.get(claim_theme_id) == facet_id:
            theme_score = 1.0
        elif claim_theme_id and facet_id:
            # Bonus partiel si le theme est proche mais pas exact
            theme_score = 0.3

    # Signal 3 : Alignement ClaimKey
    claimkey_score = 0.0
    if claimkey_facet_map and claim_claimkey_id:
        if claimkey_facet_map.get(claim_claimkey_id) == facet_id:
            claimkey_score = 1.0

    # Signal 4 : Coherence structurelle
    structural_score = min(structural_boost, 1.0)

    # Score global pondere
    global_score = (
        WEIGHT_SEMANTIC * semantic_score
        + WEIGHT_THEME * theme_score
        + WEIGHT_CLAIMKEY * claimkey_score
        + WEIGHT_STRUCTURAL * structural_score
    )

    return global_score, semantic_score, theme_score, claimkey_score, structural_score


def determine_promotion(global_score: float, semantic_score: float) -> Optional[str]:
    """
    Determine le niveau de promotion d'un lien claim→facette.

    Returns:
        "STRONG", "WEAK", ou None (pas de lien)
    """
    if global_score >= THRESHOLD_STRONG and semantic_score >= THRESHOLD_STRONG_SEMANTIC:
        return "STRONG"
    elif global_score >= THRESHOLD_WEAK:
        return "WEAK"
    return None


def batch_score_claims(
    claim_embeddings: np.ndarray,
    claim_ids: List[str],
    facet_prototypes: Dict[str, np.ndarray],
    facet_ids: List[str],
    entity_facet_affinity: Optional[Dict[str, Dict[str, float]]] = None,
    claim_entity_map: Optional[Dict[str, List[str]]] = None,
    claim_doc_ids: Optional[List[str]] = None,
) -> List[FacetAssignment]:
    """
    Score toutes les claims contre toutes les facettes en batch.

    Optimise via multiplication matricielle numpy.

    Args:
        claim_embeddings: Matrice (N, 1024) des embeddings claims
        claim_ids: Liste des claim_ids correspondants
        facet_prototypes: Dict facet_id → vecteur 1024d
        facet_ids: Liste ordonnee des facet_ids

    Returns:
        Liste de FacetAssignment pour les liens >= THRESHOLD_WEAK
    """
    if len(claim_embeddings) == 0 or len(facet_ids) == 0:
        return []

    # Construire la matrice des prototypes facettes (M, 1024)
    facet_matrix = np.array([facet_prototypes[fid] for fid in facet_ids])

    # Normaliser
    claim_norms = np.linalg.norm(claim_embeddings, axis=1, keepdims=True)
    claim_norms = np.where(claim_norms == 0, 1, claim_norms)
    claims_normalized = claim_embeddings / claim_norms

    facet_norms = np.linalg.norm(facet_matrix, axis=1, keepdims=True)
    facet_norms = np.where(facet_norms == 0, 1, facet_norms)
    facets_normalized = facet_matrix / facet_norms

    # Matrice de similarite cosine (N, M)
    similarity_matrix = claims_normalized @ facets_normalized.T

    # Strategie de discrimination relative :
    # Dans un domaine homogene (ex: SAP), le cosine similarity entre tous les textes
    # est naturellement eleve (0.80-0.93). Les seuils absolus ne discriminent pas.
    #
    # Approche : pour chaque claim, calculer le z-score de chaque facette
    # par rapport a la distribution des scores de CETTE claim.
    # Seules les facettes significativement au-dessus de la moyenne sont retenues.
    MAX_FACETS_PER_CLAIM = 2   # Une claim appartient a max 2 facettes
    MIN_ZSCORE_STRONG = 1.2    # Z-score pour STRONG (bien au-dessus de la moyenne)
    MIN_ZSCORE_WEAK = 0.5      # Z-score pour WEAK (au-dessus de la moyenne)

    assignments: List[FacetAssignment] = []

    for i, claim_id in enumerate(claim_ids):
        # Signal 1 : Semantic similarity (cosine claim ↔ facette prototype)
        semantic_scores = np.array([float(similarity_matrix[i, j]) for j in range(len(facet_ids))])

        # Signal 2 : Entity-facet affinity (les entites de cette claim sont-elles
        # associees a cette facette ?)
        entity_scores = np.zeros(len(facet_ids))
        if entity_facet_affinity and claim_entity_map:
            entities = claim_entity_map.get(claim_id, [])
            if entities:
                for eid in entities:
                    if eid in entity_facet_affinity:
                        for j, fid in enumerate(facet_ids):
                            entity_scores[j] = max(
                                entity_scores[j],
                                entity_facet_affinity[eid].get(fid, 0.0),
                            )

        # Score composite pondere
        # Semantic = 0.65, Entity affinity = 0.35
        W_SEM = 0.65
        W_ENT = 0.35 if entity_scores.any() else 0.0
        if W_ENT == 0.0:
            W_SEM = 1.0

        composite_scores = W_SEM * semantic_scores + W_ENT * entity_scores

        # Z-score sur le composite pour discrimination relative
        mean_score = float(np.mean(composite_scores))
        std_score = float(np.std(composite_scores))

        if std_score < 0.001:
            continue

        z_scores = (composite_scores - mean_score) / std_score

        # Trier par z-score decroissant
        ranked = sorted(
            [
                (j, float(composite_scores[j]), float(semantic_scores[j]),
                 float(entity_scores[j]), float(z_scores[j]))
                for j in range(len(facet_ids))
            ],
            key=lambda x: x[4],  # sort by z-score
            reverse=True,
        )

        assigned = 0
        for j, composite, semantic, entity, z_score in ranked:
            if assigned >= MAX_FACETS_PER_CLAIM:
                break

            if z_score >= MIN_ZSCORE_STRONG:
                promotion = "STRONG"
            elif z_score >= MIN_ZSCORE_WEAK:
                promotion = "WEAK"
            else:
                break

            assignments.append(FacetAssignment(
                claim_id=claim_id,
                facet_id=facet_ids[j],
                global_score=composite,
                score_semantic=semantic,
                score_structural=entity,
                promotion_level=promotion,
                assignment_method="multi_signal_zscore",
            ))
            assigned += 1

    # === Pass 2 : Document coherence boost ===
    # Si la majorite des claims d'un document vont vers une facette,
    # les claims non-assignees de ce doc recoivent un boost.
    if claim_doc_ids and len(assignments) > 0:
        assignments = _apply_doc_coherence(
            assignments, claim_ids, claim_doc_ids, facet_ids,
            similarity_matrix, entity_scores_cache={},
        )

    logger.info(
        f"[FacetEngine:Scorer] {len(claim_ids)} claims x {len(facet_ids)} facets "
        f"→ {len(assignments)} assignments "
        f"(STRONG={sum(1 for a in assignments if a.promotion_level == 'STRONG')}, "
        f"WEAK={sum(1 for a in assignments if a.promotion_level == 'WEAK')})"
    )

    return assignments


def _apply_doc_coherence(
    assignments: List[FacetAssignment],
    claim_ids: List[str],
    claim_doc_ids: List[str],
    facet_ids: List[str],
    similarity_matrix: np.ndarray,
    entity_scores_cache: dict,
) -> List[FacetAssignment]:
    """
    Pass 2 : ajoute des assignments WEAK pour les claims non-assignees
    dont le document est fortement associe a une facette.

    Si > 50% des claims d'un doc sont dans facette X, les claims
    non-assignees de ce doc recoivent facette X en WEAK
    (seulement si leur score semantique est > percentile 30 pour cette facette).
    """
    from collections import Counter, defaultdict

    # Compter les assignments par doc × facette
    doc_facet_counts: Dict[str, Counter] = defaultdict(Counter)
    assigned_claims = set()
    for a in assignments:
        idx = claim_ids.index(a.claim_id) if a.claim_id in claim_ids else -1
        if idx >= 0 and idx < len(claim_doc_ids):
            doc_facet_counts[claim_doc_ids[idx]][a.facet_id] += 1
        assigned_claims.add(a.claim_id)

    # Claims par doc
    doc_claims: Dict[str, List[int]] = defaultdict(list)
    for i, doc_id in enumerate(claim_doc_ids):
        doc_claims[doc_id].append(i)

    # Pour chaque doc, trouver la facette dominante
    boosted = 0
    for doc_id, claim_indices in doc_claims.items():
        total_doc = len(claim_indices)
        if total_doc < 5:
            continue

        facet_counts = doc_facet_counts.get(doc_id, Counter())
        if not facet_counts:
            continue

        # Facette dominante
        dominant_facet, dominant_count = facet_counts.most_common(1)[0]
        dominance_ratio = dominant_count / total_doc

        if dominance_ratio < 0.30:
            continue  # Pas de facette dominante claire

        # Trouver les claims non-assignees de ce doc
        fid_idx = facet_ids.index(dominant_facet) if dominant_facet in facet_ids else -1
        if fid_idx < 0:
            continue

        for i in claim_indices:
            claim_id = claim_ids[i]
            if claim_id in assigned_claims:
                continue

            # Score semantique de cette claim pour la facette dominante
            sem_score = float(similarity_matrix[i, fid_idx])

            # Seuil : au moins le score median des claims deja assignees
            if sem_score >= 0.83:  # seuil conservateur
                assignments.append(FacetAssignment(
                    claim_id=claim_id,
                    facet_id=dominant_facet,
                    global_score=sem_score * 0.9,  # legere penalite
                    score_semantic=sem_score,
                    score_structural=dominance_ratio,
                    promotion_level="WEAK",
                    assignment_method="doc_coherence_boost",
                ))
                assigned_claims.add(claim_id)
                boosted += 1

    if boosted > 0:
        logger.info(
            f"[FacetEngine:Scorer] Doc coherence boost: {boosted} additional WEAK assignments"
        )

    return assignments
