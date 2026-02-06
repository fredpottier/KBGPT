"""
OSMOSE Pipeline V2.2 - Pass 1.D: Validation Gate
=================================================
Purity check + budget gate + active concept coverage.

Invariants:
- I3: Budget adaptatif (concepts proportionnels à la taille du document)
- I4: No Empty Nodes (vérifié en amont par 1.B)
- I5: Purity Gate (cohérence interne des clusters)
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

from knowbase.stratified.pass1_v22.models import (
    AssertionCluster,
    ConceptStatus,
    ZonedAssertion,
)

logger = logging.getLogger(__name__)


def compute_budget(n_sections: int) -> int:
    """
    Calcule le budget adaptatif de concepts.

    Formule:
    - < 30 sections: max(10, min(20, n_sections))
    - 30-99 sections: 20 + (n - 30) // 5
    - >= 100 sections: min(60, 34 + (n - 100) // 10)
    """
    if n_sections < 30:
        return max(10, min(20, n_sections))
    elif n_sections < 100:
        return 20 + (n_sections - 30) // 5
    else:
        return min(60, 34 + (n_sections - 100) // 10)


class ValidationGate:
    """
    Pass 1.D — Purity check + budget gate.

    Phase D.1: Purity check (intra_similarity ou LLM pour gros clusters)
    Phase D.2: Budget gate (tri par support_count, top-K → ACTIVE)
    Phase D.3: Active concept coverage (garde-fou anti-tout-DRAFT)
    """

    def validate(
        self,
        clusters: List[AssertionCluster],
        assertions: List[ZonedAssertion],
        embeddings: np.ndarray,
        budget_config: Dict,
        llm_client=None,
    ) -> Tuple[List[AssertionCluster], List[AssertionCluster], List[int], float]:
        """
        Valide les clusters et applique le budget.

        Args:
            clusters: Clusters candidats (sortie de Pass 1.B)
            assertions: Toutes les assertions
            embeddings: Embeddings normalisés
            budget_config: Config contenant "n_sections"
            llm_client: Client LLM optionnel pour purity check gros clusters

        Returns:
            (active_clusters, draft_clusters, newly_unlinked_indices, active_coverage)
        """
        if not clusters:
            return [], [], [], 0.0

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1D] Validation de {len(clusters)} clusters"
        )

        # Phase D.1: Purity check
        valid_clusters, invalid_indices = self._purity_check(
            clusters, assertions, embeddings, llm_client
        )

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1D] Post-purity: {len(valid_clusters)} valid, "
            f"{len(invalid_indices)} unlinked"
        )

        # Phase D.2: Budget gate
        n_sections = budget_config.get("n_sections", 30)
        budget = compute_budget(n_sections)

        active, draft = self._apply_budget(valid_clusters, budget)

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1D] Budget {budget}: "
            f"{len(active)} ACTIVE, {len(draft)} DRAFT"
        )

        # Phase D.3: Active concept coverage
        total_promoted = sum(c.support_count for c in valid_clusters)
        active_count = sum(c.support_count for c in active)
        active_coverage = active_count / total_promoted if total_promoted > 0 else 0.0

        if active_coverage < 0.50 and draft:
            logger.warning(
                f"[OSMOSE:Pass1:V2.2:1D] Active coverage {active_coverage:.0%} < 50%, "
                f"increasing budget by 20%"
            )
            # Mitigation: augmenter le budget de 20%
            increased_budget = int(budget * 1.2)
            active, draft = self._apply_budget(valid_clusters, increased_budget)

            active_count = sum(c.support_count for c in active)
            active_coverage = active_count / total_promoted if total_promoted > 0 else 0.0
            logger.info(
                f"[OSMOSE:Pass1:V2.2:1D] Post-increase: "
                f"{len(active)} ACTIVE, {len(draft)} DRAFT, "
                f"coverage={active_coverage:.0%}"
            )

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1D] Final: {len(active)} ACTIVE, "
            f"{len(draft)} DRAFT, {len(invalid_indices)} unlinked, "
            f"active_coverage={active_coverage:.0%}"
        )

        return active, draft, invalid_indices, active_coverage

    def _purity_check(
        self,
        clusters: List[AssertionCluster],
        assertions: List[ZonedAssertion],
        embeddings: np.ndarray,
        llm_client=None,
    ) -> Tuple[List[AssertionCluster], List[int]]:
        """
        Phase D.1: Vérification de pureté des clusters.

        - Clusters <= 10 assertions: purity = intra_similarity, seuil >= 0.65
        - Clusters > 10 assertions: LLM purity check (si disponible)
        """
        PURITY_THRESHOLD = 0.65
        valid = []
        unlinked = []

        for cluster in clusters:
            if cluster.support_count <= 10:
                # Purity par intra_similarity
                if cluster.intra_similarity >= PURITY_THRESHOLD:
                    valid.append(cluster)
                else:
                    # Cluster impure: essayer de splitter
                    logger.info(
                        f"[OSMOSE:Pass1:V2.2:1D] Cluster {cluster.cluster_id} "
                        f"impure (sim={cluster.intra_similarity:.2f}), marking unlinked"
                    )
                    unlinked.extend(cluster.assertion_indices)
            else:
                # Gros cluster: LLM purity check si disponible
                if llm_client:
                    is_pure, removed = self._llm_purity_check(
                        cluster, assertions, llm_client
                    )
                    if is_pure:
                        valid.append(cluster)
                    else:
                        # Retirer les assertions hors-sujet
                        if removed:
                            remaining = [
                                i for i in cluster.assertion_indices
                                if i not in removed
                            ]
                            if len(remaining) >= 3:
                                cluster.assertion_indices = remaining
                                cluster.support_count = len(remaining)
                                valid.append(cluster)
                            else:
                                unlinked.extend(cluster.assertion_indices)
                        else:
                            unlinked.extend(cluster.assertion_indices)
                else:
                    # Pas de LLM: accepter si intra_similarity ok
                    if cluster.intra_similarity >= PURITY_THRESHOLD:
                        valid.append(cluster)
                    else:
                        unlinked.extend(cluster.assertion_indices)

        return valid, unlinked

    def _llm_purity_check(
        self,
        cluster: AssertionCluster,
        assertions: List[ZonedAssertion],
        llm_client,
    ) -> Tuple[bool, List[int]]:
        """
        LLM purity check pour gros clusters (> 10 assertions).

        Échantillonne 5 assertions et demande au LLM si elles sont cohérentes.

        Returns:
            (is_pure, indices_to_remove)
        """
        import random

        sample_indices = random.sample(
            cluster.assertion_indices,
            min(5, len(cluster.assertion_indices)),
        )
        sample_texts = []
        for idx in sample_indices:
            if 0 <= idx < len(assertions):
                sample_texts.append(f"{idx}: {assertions[idx].text}")

        prompt = (
            "Ces phrases sont censées parler du même sujet. "
            "Est-ce le cas ?\n\n"
            + "\n".join(sample_texts) + "\n\n"
            "Réponds en JSON:\n"
            '{"coherent": true/false, "outlier_indices": [indices des phrases hors-sujet]}'
        )

        try:
            response = llm_client.generate(
                system_prompt="Tu es un expert en analyse sémantique. Réponds en JSON.",
                user_prompt=prompt,
                max_tokens=300,
                temperature=0.1,
            )

            # Parse JSON
            import json
            text = response.strip()
            if "```" in text:
                start = text.find("{")
                end = text.rfind("}") + 1
                text = text[start:end]
            parsed = json.loads(text)

            is_coherent = parsed.get("coherent", True)
            outlier_indices = parsed.get("outlier_indices", [])

            if is_coherent:
                return True, []
            else:
                # Mapper les indices d'échantillon vers les indices globaux
                removed = []
                for oi in outlier_indices:
                    if isinstance(oi, int) and oi in [idx for idx in sample_indices]:
                        removed.append(oi)
                return False, removed

        except Exception as e:
            logger.warning(
                f"[OSMOSE:Pass1:V2.2:1D] LLM purity check failed: {e}"
            )
            # En cas d'erreur, accepter le cluster
            return True, []

    def _apply_budget(
        self,
        clusters: List[AssertionCluster],
        budget: int,
    ) -> Tuple[List[AssertionCluster], List[AssertionCluster]]:
        """
        Phase D.2: Budget gate.

        Trie les clusters par support_count décroissant.
        Top-K → ACTIVE, reste → DRAFT.
        """
        sorted_clusters = sorted(
            clusters, key=lambda c: c.support_count, reverse=True
        )

        active = sorted_clusters[:budget]
        draft = sorted_clusters[budget:]

        return active, draft
