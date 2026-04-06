"""
FacetEngine V2 — Consolidator.

Regroupe les micro-facettes emergentes (80-200) en macro-facettes
navigables (15-40) via clustering hierarchique des centroids.

Pipeline :
  1. Clustering agglomeratif des centroids de micro-facettes
  2. Labellisation LLM de chaque macro-groupe
  3. Rattachement des claims : micro→macro propagation
  4. Conservation de la hierarchie micro/macro pour navigation fine

Le resultat est une structure a deux niveaux :
  - Macro-facettes : navigation produit (15-30)
  - Micro-facettes : precision interne (maintenues comme sous-facettes)
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from knowbase.facets.clustering import EmergentFacet
from knowbase.facets.scorer import cosine_similarity

logger = logging.getLogger(__name__)

TARGET_MACRO_FACETS_MIN = 12
TARGET_MACRO_FACETS_MAX = 30


@dataclass
class MacroFacet:
    """Facette consolidee (niveau navigation)."""
    facet_id: str
    canonical_label: str
    description: str
    negative_boundary: str = ""
    facet_family: str = "cross_cutting_concern"
    centroid: Optional[np.ndarray] = None
    micro_facet_ids: List[str] = field(default_factory=list)
    total_claims: int = 0
    total_docs: int = 0
    quality: str = "good"


def consolidate_facets(
    micro_facets: List[EmergentFacet],
    llm_fn: Optional[Callable] = None,
    claim_texts: Optional[List[str]] = None,
    claim_ids: Optional[List[str]] = None,
) -> Tuple[List[MacroFacet], Dict[str, str]]:
    """
    Consolide les micro-facettes en macro-facettes.

    Args:
        micro_facets: Liste de micro-facettes emergentes
        llm_fn: Fonction LLM pour labellisation
        claim_texts: Textes des claims (pour context LLM)
        claim_ids: IDs des claims

    Returns:
        (macro_facets, micro_to_macro_map)
        micro_to_macro_map: Dict micro_facet_id → macro_facet_id
    """
    if len(micro_facets) <= TARGET_MACRO_FACETS_MAX:
        # Pas assez de micro-facettes pour consolider
        logger.info(
            f"[FacetEngine:Consolidate] {len(micro_facets)} micro-facets <= "
            f"{TARGET_MACRO_FACETS_MAX} target → no consolidation needed"
        )
        return _promote_micros_as_macros(micro_facets), {}

    # === Phase 1 : Clustering agglomeratif des centroids ===
    logger.info(
        f"[FacetEngine:Consolidate] Clustering {len(micro_facets)} micro-facets "
        f"into {TARGET_MACRO_FACETS_MIN}-{TARGET_MACRO_FACETS_MAX} macro-facets..."
    )

    centroids = []
    valid_micros = []
    for mf in micro_facets:
        if mf.centroid is not None:
            centroids.append(mf.centroid)
            valid_micros.append(mf)

    if len(centroids) < TARGET_MACRO_FACETS_MIN:
        return _promote_micros_as_macros(micro_facets), {}

    centroid_matrix = np.array(centroids)

    # Clustering agglomeratif avec distance cosine
    from sklearn.cluster import AgglomerativeClustering

    # Trouver le bon nombre de clusters
    # On essaie d'abord la cible mediane, puis on ajuste
    target_k = min(
        TARGET_MACRO_FACETS_MAX,
        max(TARGET_MACRO_FACETS_MIN, len(valid_micros) // 4)
    )

    clustering = AgglomerativeClustering(
        n_clusters=target_k,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(centroid_matrix)

    n_groups = len(set(labels))
    logger.info(
        f"[FacetEngine:Consolidate] Agglomerative: {len(valid_micros)} → {n_groups} groups"
    )

    # === Phase 2 : Construire les macro-facettes ===
    groups: Dict[int, List[EmergentFacet]] = defaultdict(list)
    for i, label in enumerate(labels):
        groups[label].append(valid_micros[i])

    macro_facets: List[MacroFacet] = []
    micro_to_macro: Dict[str, str] = {}

    for group_id, members in sorted(groups.items()):
        # Centroid du groupe
        group_centroids = [m.centroid for m in members if m.centroid is not None]
        if group_centroids:
            group_centroid = np.mean(group_centroids, axis=0)
            norm = np.linalg.norm(group_centroid)
            if norm > 0:
                group_centroid = group_centroid / norm
        else:
            group_centroid = None

        total_claims = sum(m.member_count for m in members)
        all_docs = set()
        for m in members:
            # Approximation : doc_count des micro-facettes
            all_docs.add(m.doc_count)  # pas exact mais suffisant

        micro_ids = [m.facet_id for m in members]

        # Label du groupe : le plus gros micro-facet ou LLM
        if llm_fn:
            label, desc, neg_boundary = _label_group_with_llm(
                members, llm_fn, claim_texts, claim_ids
            )
        else:
            # Fallback : prendre le label du plus gros membre
            biggest = max(members, key=lambda m: m.member_count)
            label = biggest.canonical_label
            desc = biggest.description
            neg_boundary = biggest.negative_boundary

        macro_id = f"facet_macro_{label.lower().replace(' ', '_').replace('&', 'and')[:30]}"

        macro = MacroFacet(
            facet_id=macro_id,
            canonical_label=label,
            description=desc,
            negative_boundary=neg_boundary,
            centroid=group_centroid,
            micro_facet_ids=micro_ids,
            total_claims=total_claims,
            total_docs=len(all_docs),
        )
        macro_facets.append(macro)

        for mid in micro_ids:
            micro_to_macro[mid] = macro_id

        member_labels = [m.canonical_label for m in members]
        logger.info(
            f"[FacetEngine:Consolidate] Macro '{label}': "
            f"{len(members)} micros, {total_claims} claims, "
            f"members={member_labels[:5]}{'...' if len(member_labels) > 5 else ''}"
        )

    logger.info(
        f"[FacetEngine:Consolidate] Result: {len(macro_facets)} macro-facets "
        f"from {len(valid_micros)} micro-facets"
    )

    return macro_facets, micro_to_macro


def _label_group_with_llm(
    members: List[EmergentFacet],
    llm_fn: Callable,
    claim_texts: Optional[List[str]],
    claim_ids: Optional[List[str]],
) -> Tuple[str, str, str]:
    """Labellise un groupe de micro-facettes via LLM."""
    import json, re

    member_info = []
    for m in sorted(members, key=lambda x: x.member_count, reverse=True)[:8]:
        sample_claims = ""
        if claim_texts and m.prototype_claim_indices:
            samples = [
                claim_texts[idx][:100]
                for idx in m.prototype_claim_indices[:3]
                if idx < len(claim_texts)
            ]
            sample_claims = " | ".join(samples)
        member_info.append(
            f"- {m.canonical_label} ({m.member_count} claims): {sample_claims}"
        )

    system_prompt = """You are a document analyst. Given a group of related micro-facets,
create a single consolidated macro-facet that encompasses them all.

Output JSON:
{
  "canonical_label": "short name (1-3 words)",
  "description": "what this macro-facet covers (1-2 sentences)",
  "negative_boundary": "what it does NOT include (1 sentence)"
}"""

    user_prompt = (
        f"These {len(members)} micro-facets should be grouped under one macro-facet:\n\n"
        + "\n".join(member_info)
        + "\n\nCreate a consolidated label that covers all of them."
    )

    try:
        response = llm_fn(system_prompt, user_prompt)
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        data = json.loads(text)
        return (
            data.get("canonical_label", members[0].canonical_label),
            data.get("description", ""),
            data.get("negative_boundary", ""),
        )
    except Exception as e:
        logger.warning(f"[FacetEngine:Consolidate] LLM labeling failed: {e}")
        biggest = max(members, key=lambda m: m.member_count)
        return biggest.canonical_label, biggest.description, biggest.negative_boundary


def _promote_micros_as_macros(micros: List[EmergentFacet]) -> List[MacroFacet]:
    """Quand pas assez de micro-facettes, les promouvoir directement."""
    return [
        MacroFacet(
            facet_id=m.facet_id,
            canonical_label=m.canonical_label,
            description=m.description,
            negative_boundary=m.negative_boundary,
            facet_family=m.facet_family,
            centroid=m.centroid,
            micro_facet_ids=[m.facet_id],
            total_claims=m.member_count,
            total_docs=m.doc_count,
            quality=m.quality,
        )
        for m in micros
    ]
