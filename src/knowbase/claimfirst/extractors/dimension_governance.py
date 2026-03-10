# src/knowbase/claimfirst/extractors/dimension_governance.py
"""
Dimension Governance — Audit + split/merge du registre de dimensions.

Analyse la santé du registre de QuestionDimension et propose des actions :
- should_split : dimension trop large (>5 valeurs + >3 scopes, ou >8 valeurs)
- merge_candidate : dimensions similaires (embedding cosine > 0.85)
- healthy : aucune action nécessaire

Le workflow de merge :
- A.status = "merged", A.merged_into = B.dimension_id
- QS de A re-rattachées à B
- DimensionMapperV2 ignore les dimensions status=merged
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from knowbase.claimfirst.models.question_dimension import QuestionDimension

logger = logging.getLogger("[OSMOSE] dimension_governance")


@dataclass
class DimensionHealthReport:
    """Rapport de santé d'une dimension."""
    dimension_id: str
    dimension_key: str
    qs_count: int = 0
    doc_count: int = 0
    distinct_values: int = 0
    distinct_scopes: int = 0
    health_status: str = "healthy"  # "healthy" | "needs_review" | "should_split"
    split_suggestion: Optional[List[str]] = None
    merge_candidates: Optional[List[str]] = None


@dataclass
class AuditReport:
    """Rapport d'audit complet du registre."""
    total_dimensions: int = 0
    healthy_count: int = 0
    needs_review_count: int = 0
    should_split_count: int = 0
    merge_pairs: List[Tuple[str, str, float]] = field(default_factory=list)
    dimension_reports: List[DimensionHealthReport] = field(default_factory=list)
    scope_policy_suggestions: List[Dict] = field(default_factory=list)


class DimensionAuditor:
    """Auditeur de santé du registre de dimensions."""

    def __init__(self, use_embeddings: bool = True):
        self._use_embeddings = use_embeddings
        self._encoder = None
        self._embedding_cache: Dict[str, np.ndarray] = {}

    def _get_encoder(self):
        if self._encoder is None:
            from knowbase.common.clients.embeddings import EmbeddingModelManager
            self._encoder = EmbeddingModelManager()
        return self._encoder

    def _encode(self, text: str) -> np.ndarray:
        if text in self._embedding_cache:
            return self._embedding_cache[text]
        encoder = self._get_encoder()
        result = encoder.encode([text])
        vec = result[0] if len(result.shape) > 1 else result
        self._embedding_cache[text] = vec
        return vec

    def audit_dimension(
        self,
        dim: QuestionDimension,
        qs_values: List[str],
        qs_scopes: List[str],
        qs_doc_ids: List[str],
    ) -> DimensionHealthReport:
        """
        Évalue la santé d'une dimension unique.

        Args:
            dim: La QuestionDimension à auditer
            qs_values: Valeurs extraites des QS rattachées
            qs_scopes: Scopes des QS rattachées
            qs_doc_ids: Doc IDs des QS rattachées
        """
        distinct_values = len(set(v.strip().lower() for v in qs_values if v))
        distinct_scopes = len(set(s.strip().lower() for s in qs_scopes if s))
        doc_count = len(set(qs_doc_ids))

        report = DimensionHealthReport(
            dimension_id=dim.dimension_id,
            dimension_key=dim.dimension_key,
            qs_count=len(qs_values),
            doc_count=doc_count,
            distinct_values=distinct_values,
            distinct_scopes=distinct_scopes,
        )

        # Critères de split
        if distinct_values > 8:
            report.health_status = "should_split"
            report.split_suggestion = [
                f"Dimension has {distinct_values} distinct values — likely conflates multiple concepts"
            ]
        elif distinct_values > 5 and distinct_scopes > 3:
            report.health_status = "should_split"
            report.split_suggestion = [
                f"{distinct_values} values across {distinct_scopes} scopes — consider splitting by scope"
            ]
        elif distinct_values > 5 or distinct_scopes > 3:
            report.health_status = "needs_review"

        return report

    def find_merge_candidates(
        self,
        registry: List[QuestionDimension],
        similarity_threshold: float = 0.92,
        min_key_overlap: float = 0.40,
    ) -> List[Tuple[str, str, float]]:
        """
        Trouve les paires de dimensions candidates au merge.

        Ne compare que les dimensions de même value_type.
        Deux filtres combinés :
        1. Cosine similarity sur canonical_question ≥ threshold
        2. Token overlap sur dimension_key ≥ min_key_overlap

        Le filtre token overlap empêche les faux merges entre questions de
        structure similaire ("What is the X?") mais de sens différent.
        """
        if not self._use_embeddings:
            return []

        # Grouper par value_type
        by_type: Dict[str, List[QuestionDimension]] = {}
        for dim in registry:
            if dim.status == "merged":
                continue
            by_type.setdefault(dim.value_type, []).append(dim)

        pairs: List[Tuple[str, str, float]] = []

        for vtype, dims in by_type.items():
            if len(dims) < 2:
                continue

            # Encoder toutes les questions
            try:
                encoder = self._get_encoder()
                questions = [d.canonical_question for d in dims]
                embeddings = encoder.encode(questions)
            except Exception as e:
                logger.warning(f"[Auditor] Embedding failed for {vtype}: {e}")
                continue

            # Comparer toutes les paires
            for i in range(len(dims)):
                for j in range(i + 1, len(dims)):
                    # Skip si inversion sémantique
                    from knowbase.claimfirst.extractors.dimension_mapper import _is_semantic_inversion
                    if _is_semantic_inversion(
                        dims[i].dimension_key.lower(),
                        dims[j].dimension_key.lower(),
                    ):
                        continue

                    # Token overlap sur dimension_key
                    overlap = _key_token_overlap(
                        dims[i].dimension_key, dims[j].dimension_key
                    )
                    if overlap < min_key_overlap:
                        continue

                    vec_i = embeddings[i] if len(embeddings.shape) > 1 else embeddings
                    vec_j = embeddings[j] if len(embeddings.shape) > 1 else embeddings

                    sim = _cosine_similarity(vec_i, vec_j)
                    if sim >= similarity_threshold:
                        pairs.append((dims[i].dimension_id, dims[j].dimension_id, sim))

        return pairs

    def suggest_scope_policies(
        self,
        registry: List[QuestionDimension],
        qs_data: Dict[str, Dict],
    ) -> List[Dict]:
        """
        Propose des scope_policy basées sur les métriques.

        Mode "proposé" : retourne un rapport, pas une action automatique.

        Args:
            registry: Registre de dimensions
            qs_data: {dimension_id: {"values": [...], "scopes": [...], "doc_ids": [...]}}
        """
        suggestions = []
        for dim in registry:
            if dim.status == "merged" or dim.scope_policy != "any":
                continue
            data = qs_data.get(dim.dimension_id, {})
            values = data.get("values", [])
            scopes = data.get("scopes", [])
            distinct_values = len(set(v.strip().lower() for v in values if v))
            distinct_scopes = len(set(s.strip().lower() for s in scopes if s))

            if distinct_values > 5 and distinct_scopes > 3:
                suggestions.append({
                    "dimension_id": dim.dimension_id,
                    "dimension_key": dim.dimension_key,
                    "current_policy": "any",
                    "suggested_policy": "requires_product",
                    "reason": f"{distinct_values} values, {distinct_scopes} scopes — needs product-specific discrimination",
                    "distinct_values": distinct_values,
                    "distinct_scopes": distinct_scopes,
                })

        return suggestions

    def full_audit(
        self,
        registry: List[QuestionDimension],
        qs_data: Dict[str, Dict],
    ) -> AuditReport:
        """
        Audit complet du registre.

        Args:
            registry: Registre de dimensions
            qs_data: {dimension_id: {"values": [...], "scopes": [...], "doc_ids": [...]}}
        """
        report = AuditReport(total_dimensions=len(registry))

        for dim in registry:
            if dim.status == "merged":
                continue
            data = qs_data.get(dim.dimension_id, {})
            dim_report = self.audit_dimension(
                dim,
                data.get("values", []),
                data.get("scopes", []),
                data.get("doc_ids", []),
            )
            report.dimension_reports.append(dim_report)

            if dim_report.health_status == "healthy":
                report.healthy_count += 1
            elif dim_report.health_status == "needs_review":
                report.needs_review_count += 1
            elif dim_report.health_status == "should_split":
                report.should_split_count += 1

        # Merge candidates
        report.merge_pairs = self.find_merge_candidates(registry)

        # Scope policy suggestions
        report.scope_policy_suggestions = self.suggest_scope_policies(registry, qs_data)

        return report


def _key_token_overlap(key_a: str, key_b: str) -> float:
    """
    Calcule le ratio de tokens partagés entre deux dimension_keys.

    Ex: "data_deletion_requirement" vs "deletion_requirement" → 2/3 = 0.67
    """
    tokens_a = set(key_a.lower().split("_"))
    tokens_b = set(key_b.lower().split("_"))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    # Ratio par rapport au plus petit ensemble (Jaccard modifié)
    return len(intersection) / min(len(tokens_a), len(tokens_b))


def _cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Cosine similarity entre deux vecteurs."""
    if v1 is None or v2 is None:
        return 0.0
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


__all__ = [
    "DimensionAuditor",
    "DimensionHealthReport",
    "AuditReport",
]
