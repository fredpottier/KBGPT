"""
FacetEngine V2 — Normalizer (Pass F2).

Deduplique et fusionne les facettes proches :
- Normalisation lexicale du label
- Embedding similarity entre facettes
- Fusion des facettes avec similarity > seuil
"""
from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

from knowbase.facets.models import Facet
from knowbase.facets.scorer import cosine_similarity

logger = logging.getLogger(__name__)

MERGE_THRESHOLD = 0.97  # Cosine similarity au-dessus de laquelle on fusionne
# Note: dans un domaine homogene (SAP), les embeddings de descriptions courtes
# sont naturellement tres proches (0.90-0.96). Le seuil doit etre tres haut
# pour ne fusionner que les vrais doublons ("Deployment & Migration" x2).


def normalize_facets(
    facets: List[Facet],
    encode_fn=None,
) -> List[Facet]:
    """
    Deduplique et normalise les facettes.

    Phase 1 : dedup lexicale (meme label normalise)
    Phase 2 : dedup par embedding (si encode_fn fourni)

    Args:
        facets: Liste de facettes
        encode_fn: Fonction d'encoding texte → vecteur (optionnel)

    Returns:
        Liste de facettes normalisees (potentiellement reduite)
    """
    if not facets:
        return []

    # Phase 1 : dedup lexicale
    facets = _dedup_lexical(facets)

    # Phase 2 : dedup par embedding
    if encode_fn and len(facets) > 1:
        facets = _dedup_embedding(facets, encode_fn)

    return facets


def _dedup_lexical(facets: List[Facet]) -> List[Facet]:
    """Deduplique par label normalise."""
    seen: Dict[str, Facet] = {}
    result = []

    for f in facets:
        key = f.canonical_label.lower().strip()
        # Normaliser les variantes courantes
        key = key.replace("&", "and").replace("-", " ").replace("_", " ")
        key = " ".join(key.split())  # normaliser les espaces

        if key in seen:
            existing = seen[key]
            # Garder la facette validated
            if f.status == "validated" and existing.status != "validated":
                seen[key] = f
                result = [x for x in result if x.facet_id != existing.facet_id]
                result.append(f)
                logger.info(
                    f"[FacetEngine:Normalize] Lexical dedup: replaced "
                    f"'{existing.canonical_label}' with '{f.canonical_label}'"
                )
            else:
                # Enrichir la description si l'existante est vide
                if not existing.description and f.description:
                    existing.description = f.description
        else:
            seen[key] = f
            result.append(f)

    if len(result) < len(facets):
        logger.info(
            f"[FacetEngine:Normalize] Lexical dedup: {len(facets)} → {len(result)}"
        )
    return result


def _dedup_embedding(facets: List[Facet], encode_fn) -> List[Facet]:
    """Fusionne les facettes avec embeddings tres proches."""
    # Encoder les labels + descriptions
    texts = [
        f"passage: {f.canonical_label}. {f.description}"
        for f in facets
    ]
    vectors = encode_fn(texts)
    if vectors is None or len(vectors) == 0:
        return facets

    vectors = np.array(vectors)
    n = len(facets)
    merged = set()
    result = []

    for i in range(n):
        if i in merged:
            continue

        # Chercher les facettes tres proches
        group = [i]
        for j in range(i + 1, n):
            if j in merged:
                continue
            sim = cosine_similarity(vectors[i], vectors[j])
            if sim >= MERGE_THRESHOLD:
                group.append(j)
                merged.add(j)

        if len(group) > 1:
            # Fusionner : garder la facette validated, ou la premiere
            best = group[0]
            for idx in group:
                if facets[idx].status == "validated":
                    best = idx
                    break
            merged_names = [facets[idx].canonical_label for idx in group if idx != best]
            logger.info(
                f"[FacetEngine:Normalize] Embedding merge: "
                f"'{facets[best].canonical_label}' absorbs {merged_names}"
            )
            result.append(facets[best])
        else:
            result.append(facets[i])

    if len(result) < n:
        logger.info(
            f"[FacetEngine:Normalize] Embedding dedup: {n} → {len(result)}"
        )
    return result
