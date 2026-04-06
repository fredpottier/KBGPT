"""
FacetEngine V2 — Governance (Pass F5).

Calcule les metriques de sante de chaque facette et detecte :
- Facettes sur-specialisees (mono-doc)
- Facettes trop generiques (dispersion)
- Facettes en doublon (merge candidates)
- Facettes instables (drift)
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Dict, List, Optional

import numpy as np

from knowbase.facets.models import Facet, FacetAssignment, FacetHealth
from knowbase.facets.scorer import cosine_similarity

logger = logging.getLogger(__name__)

# Seuils de gouvernance
MIN_CLAIMS_VALIDATED = 10      # Minimum claims pour promotion candidate → validated
MIN_DOCS_VALIDATED = 3         # Minimum docs distincts pour promotion
MAX_DOC_CONCENTRATION = 0.80   # Si > 80% dans un doc → suspecte de sur-specialisation
MERGE_SIMILARITY_THRESHOLD = 0.96  # Cosine entre prototypes pour merge candidate
# Note: les prototypes composites sont plus discriminants que les labels seuls,
# mais dans un domaine homogene il faut rester prudent.


def compute_health(
    facets: List[Facet],
    assignments: List[FacetAssignment],
    claim_doc_ids: List[str],
    claim_id_to_idx: Dict[str, int],
    facet_prototypes: Optional[Dict[str, np.ndarray]] = None,
) -> None:
    """
    Calcule les metriques de sante et met a jour le status des facettes.

    Modifie les facettes in-place (facet.health, facet.status).
    """
    # Grouper les assignments par facette
    facet_assignments: Dict[str, List[FacetAssignment]] = defaultdict(list)
    for a in assignments:
        facet_assignments[a.facet_id].append(a)

    for facet in facets:
        fa = facet_assignments.get(facet.facet_id, [])
        if not fa:
            facet.health = FacetHealth(facet_id=facet.facet_id)
            continue

        # Documents des claims assignees
        docs = Counter()
        for a in fa:
            idx = claim_id_to_idx.get(a.claim_id)
            if idx is not None and idx < len(claim_doc_ids):
                docs[claim_doc_ids[idx]] += 1

        total = len(fa)
        strong_count = sum(1 for a in fa if a.promotion_level == "STRONG")
        weak_count = total - strong_count

        # Concentration max sur un doc
        top_doc_pct = max(docs.values()) / total if docs and total > 0 else 0

        # Stabilite cross-doc
        total_docs_in_corpus = len(set(claim_doc_ids))
        cross_doc = len(docs) / max(1, total_docs_in_corpus) if docs else 0

        health = FacetHealth(
            facet_id=facet.facet_id,
            info_count=total,
            doc_count=len(docs),
            weak_ratio=weak_count / total if total > 0 else 0,
            strong_ratio=strong_count / total if total > 0 else 0,
            top_doc_concentration=top_doc_pct,
            cross_doc_stability=cross_doc,
        )

        # === Detection des anomalies ===

        # Sur-specialisation : mono-doc avec peu de claims
        if len(docs) == 1 and total < MIN_CLAIMS_VALIDATED:
            health.drift_alert = True
            logger.warning(
                f"[FacetEngine:Governance] '{facet.canonical_label}': "
                f"mono-doc ({total} claims) → reste candidate"
            )

        # Trop generique : forte dispersion, faible concentration
        if top_doc_pct < 0.05 and len(docs) > 10:
            health.drift_alert = True
            logger.warning(
                f"[FacetEngine:Governance] '{facet.canonical_label}': "
                f"very dispersed (top_doc={top_doc_pct:.0%}) → possible split"
            )
            health.split_candidate = True

        facet.health = health

        # === Promotion automatique ===
        if facet.status == "candidate":
            if total >= MIN_CLAIMS_VALIDATED and len(docs) >= MIN_DOCS_VALIDATED:
                facet.status = "validated"
                logger.info(
                    f"[FacetEngine:Governance] Promoted '{facet.canonical_label}' "
                    f"→ validated ({total} claims, {len(docs)} docs)"
                )

    # === Detection merge candidates ===
    if facet_prototypes:
        _detect_merge_candidates(facets, facet_prototypes)


def _detect_merge_candidates(
    facets: List[Facet],
    facet_prototypes: Dict[str, np.ndarray],
) -> None:
    """Detecte les paires de facettes candidates a fusion."""
    n = len(facets)
    for i in range(n):
        fi = facets[i]
        vi = facet_prototypes.get(fi.facet_id)
        if vi is None:
            continue

        for j in range(i + 1, n):
            fj = facets[j]
            vj = facet_prototypes.get(fj.facet_id)
            if vj is None:
                continue

            sim = cosine_similarity(vi, vj)
            if sim >= MERGE_SIMILARITY_THRESHOLD:
                # Marquer les deux comme merge candidates
                fi.health = fi.health or FacetHealth(facet_id=fi.facet_id)
                fj.health = fj.health or FacetHealth(facet_id=fj.facet_id)
                fi.health.merge_candidate_with = fj.facet_id
                fj.health.merge_candidate_with = fi.facet_id

                logger.info(
                    f"[FacetEngine:Governance] Merge candidate: "
                    f"'{fi.canonical_label}' ↔ '{fj.canonical_label}' "
                    f"(sim={sim:.3f})"
                )
