"""
FacetEngine V2 — Prototype Builder (Pass F3).

Construit le prototype composite de chaque facette :
  - Embedding du label + description (25%)
  - Centroid des claims prototypes (50%)
  - Centroid ClaimKeys (15%) — Sprint 2
  - Centroid Themes (10%) — Sprint 2

Le prototype est un vecteur 1024d qui represente le coeur
semantique de la facette. C'est lui qui remplace les keywords.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

from knowbase.facets.models import Facet, FacetPrototype

logger = logging.getLogger(__name__)

# Poids du prototype composite
W_LABEL = 0.25
W_CLAIMS = 0.50
W_CLAIMKEY = 0.15  # Sprint 2
W_THEME = 0.10     # Sprint 2


def build_label_embedding(
    facet: Facet,
    encode_fn,
) -> np.ndarray:
    """
    Encode le label + description de la facette.

    Args:
        facet: La facette
        encode_fn: Fonction d'encoding (texte → vecteur 1024d)

    Returns:
        Vecteur 1024d
    """
    text = f"passage: {facet.canonical_label}"
    if facet.description:
        text += f". {facet.description}"
    vectors = encode_fn([text])
    if vectors is not None and len(vectors) > 0:
        return np.array(vectors[0])
    return np.zeros(1024)


def compute_claims_centroid(
    claim_embeddings: List[np.ndarray],
) -> np.ndarray:
    """
    Calcule le centroid des embeddings des claims prototypes.

    Args:
        claim_embeddings: Liste de vecteurs 1024d

    Returns:
        Centroid 1024d (moyenne normalisee)
    """
    if not claim_embeddings:
        return np.zeros(1024)
    matrix = np.array(claim_embeddings)
    centroid = matrix.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm
    return centroid


def select_prototype_claims(
    facet_id: str,
    facet_label: str,
    all_claim_embeddings: np.ndarray,
    all_claim_ids: List[str],
    label_vector: np.ndarray,
    top_k: int = 20,
) -> Tuple[List[str], List[np.ndarray]]:
    """
    Selectionne les claims les plus proches du label de la facette
    comme prototypes initiaux (bootstrap).

    Args:
        facet_id: ID de la facette
        facet_label: Label de la facette
        all_claim_embeddings: Matrice (N, 1024) de toutes les claims
        all_claim_ids: IDs correspondants
        label_vector: Embedding du label de la facette
        top_k: Nombre de prototypes a selectionner

    Returns:
        (prototype_claim_ids, prototype_embeddings)
    """
    if len(all_claim_embeddings) == 0:
        return [], []

    # Normaliser
    label_norm = label_vector / (np.linalg.norm(label_vector) + 1e-10)
    claim_norms = np.linalg.norm(all_claim_embeddings, axis=1, keepdims=True)
    claim_norms = np.where(claim_norms == 0, 1, claim_norms)
    claims_normalized = all_claim_embeddings / claim_norms

    # Similarite cosine
    similarities = claims_normalized @ label_norm

    # Top-K
    top_indices = np.argsort(similarities)[-top_k:][::-1]

    prototype_ids = [all_claim_ids[i] for i in top_indices]
    prototype_embeddings = [all_claim_embeddings[i] for i in top_indices]

    logger.debug(
        f"[FacetEngine:Prototype] {facet_label}: top-{top_k} prototypes, "
        f"sim range [{similarities[top_indices[-1]]:.3f}, {similarities[top_indices[0]]:.3f}]"
    )

    return prototype_ids, prototype_embeddings


def build_prototype(
    facet: Facet,
    label_vector: np.ndarray,
    prototype_claim_embeddings: List[np.ndarray],
    prototype_claim_ids: List[str],
) -> FacetPrototype:
    """
    Construit le prototype composite d'une facette.

    Sprint 1 : label (25%) + claims centroid (75%)
    Sprint 2 : + ClaimKey centroid (15%) + Theme centroid (10%)

    Args:
        facet: La facette
        label_vector: Embedding du label+description
        prototype_claim_embeddings: Embeddings des claims prototypes
        prototype_claim_ids: IDs des claims prototypes

    Returns:
        FacetPrototype avec le vecteur composite
    """
    claims_centroid = compute_claims_centroid(prototype_claim_embeddings)

    # Sprint 1 : redistribuer les poids ClaimKey et Theme vers claims
    # car ces signaux ne sont pas encore disponibles
    effective_w_label = W_LABEL
    effective_w_claims = W_CLAIMS + W_CLAIMKEY + W_THEME  # 0.75

    composite = (
        effective_w_label * label_vector
        + effective_w_claims * claims_centroid
    )

    # Normaliser
    norm = np.linalg.norm(composite)
    if norm > 0:
        composite = composite / norm

    return FacetPrototype(
        facet_id=facet.facet_id,
        vector=composite.tolist(),
        label_vector=label_vector.tolist(),
        claims_centroid=claims_centroid.tolist(),
        prototype_claim_ids=prototype_claim_ids,
        prototype_count=len(prototype_claim_ids),
    )


def build_all_prototypes(
    facets: List[Facet],
    all_claim_embeddings: np.ndarray,
    all_claim_ids: List[str],
    encode_fn,
    top_k: int = 20,
) -> Dict[str, FacetPrototype]:
    """
    Construit les prototypes pour toutes les facettes.

    Args:
        facets: Liste des facettes
        all_claim_embeddings: Matrice (N, 1024)
        all_claim_ids: IDs correspondants
        encode_fn: Fonction d'encoding texte → vecteur
        top_k: Nombre de prototypes par facette

    Returns:
        Dict facet_id → FacetPrototype
    """
    prototypes: Dict[str, FacetPrototype] = {}

    for facet in facets:
        # 1. Embedding du label
        label_vector = build_label_embedding(facet, encode_fn)

        # 2. Selectionner les claims prototypes
        proto_ids, proto_embeddings = select_prototype_claims(
            facet.facet_id,
            facet.canonical_label,
            all_claim_embeddings,
            all_claim_ids,
            label_vector,
            top_k=top_k,
        )

        # 3. Construire le prototype composite
        prototype = build_prototype(
            facet, label_vector, proto_embeddings, proto_ids
        )
        prototypes[facet.facet_id] = prototype
        facet.prototype = prototype

        logger.info(
            f"[FacetEngine:Prototype] {facet.canonical_label}: "
            f"{prototype.prototype_count} prototypes, "
            f"vector norm={np.linalg.norm(prototype.vector):.3f}"
        )

    return prototypes
