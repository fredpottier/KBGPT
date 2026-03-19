"""Règles Layer 1 — Fusion conservatrice des axes temporels."""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Set, Tuple

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
    HygieneRunScope,
)
from knowbase.hygiene.rules.base import HygieneRule

logger = logging.getLogger("[OSMOSE] kg_hygiene_l1_axes")

# Pattern pour détecter des valeurs temporelles (années)
YEAR_PATTERN = re.compile(r"^\d{4}$")
DATE_PATTERN = re.compile(r"^\d{4}[-/]\d{2}([-/]\d{2})?$")

# Clés temporelles connues à ne PAS fusionner (sémantiquement distinctes)
DISTINCT_TEMPORAL_KEYS = {
    "publication_year", "effective_year", "baseline_year", "study_year",
    "launch_year", "end_of_life_year", "sunset_year",
    "publication_date", "effective_date", "baseline_date",
}


def _normalize_axis_key(key: str) -> str:
    """Normalise une clé d'axe pour comparaison."""
    return re.sub(r"[_\-\s]+", "_", key.lower().strip())


def _are_keys_similar(key1: str, key2: str) -> bool:
    """Vérifie si deux clés d'axes sont proches lexicalement."""
    n1 = _normalize_axis_key(key1)
    n2 = _normalize_axis_key(key2)

    if n1 == n2:
        return True

    # Si les deux sont dans DISTINCT_TEMPORAL_KEYS et différentes → pas similaires
    if n1 in DISTINCT_TEMPORAL_KEYS and n2 in DISTINCT_TEMPORAL_KEYS:
        return False

    # Vérifier si l'une est un préfixe/suffixe de l'autre
    if n1.startswith(n2) or n2.startswith(n1):
        return True

    # Vérifier via les mots clés communs
    words1 = set(n1.split("_"))
    words2 = set(n2.split("_"))
    if words1 and words2:
        overlap = len(words1 & words2) / max(len(words1), len(words2))
        if overlap >= 0.5:
            return True

    return False


def _all_temporal_values(values: List[str]) -> bool:
    """Vérifie si toutes les valeurs sont temporelles (années ou dates)."""
    if not values:
        return False
    return all(
        YEAR_PATTERN.match(v.strip()) or DATE_PATTERN.match(v.strip())
        for v in values
        if v and v.strip()
    )


class ConservativeAxisMergeRule(HygieneRule):
    """
    Fusionne les axes temporels redondants de manière très conservatrice.

    Conditions de fusion L1 (toutes requises):
    1. Clés proches lexicalement
    2. Valeurs du même type (toutes des années, toutes des dates)
    3. Absence d'ambiguïté contextuelle (pas de clés distinctes connues)

    En cas de doute → PROPOSED en L2, pas fusion L1.
    """

    @property
    def name(self) -> str:
        return "conservative_axis_merge"

    @property
    def layer(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return "Fusionne les axes temporels redondants (clés proches + mêmes types de valeurs)"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        axes = self._load_axes(neo4j_driver, tenant_id, scope, scope_params)

        if len(axes) < 2:
            return []

        actions = []
        processed_ids: Set[str] = set()

        for i, ax1 in enumerate(axes):
            if ax1["axis_id"] in processed_ids:
                continue

            for ax2 in axes[i + 1:]:
                if ax2["axis_id"] in processed_ids:
                    continue

                key1 = ax1.get("axis_key", "")
                key2 = ax2.get("axis_key", "")
                nk1 = _normalize_axis_key(key1)
                nk2 = _normalize_axis_key(key2)

                # Condition 3: Pas de clés sémantiquement distinctes
                if nk1 in DISTINCT_TEMPORAL_KEYS and nk2 in DISTINCT_TEMPORAL_KEYS:
                    if nk1 != nk2:
                        continue

                # Condition 1: Clés proches
                if not _are_keys_similar(key1, key2):
                    continue

                # Condition 2: Mêmes types de valeurs
                vals1 = ax1.get("values", [])
                vals2 = ax2.get("values", [])
                if not (_all_temporal_values(vals1) and _all_temporal_values(vals2)):
                    continue

                # Toutes les conditions remplies → MERGE
                # Le target est l'axe avec le plus de valeurs
                if len(vals1) >= len(vals2):
                    target, source = ax1, ax2
                else:
                    target, source = ax2, ax1

                action = HygieneAction(
                    action_type=HygieneActionType.MERGE_AXIS,
                    target_node_id=source["axis_id"],
                    target_node_type="ApplicabilityAxis",
                    layer=1,
                    confidence=1.0,
                    reason=(
                        f"Axes temporels redondants: '{source.get('axis_key')}' → "
                        f"'{target.get('axis_key')}' (fusion conservatrice)"
                    ),
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=HygieneActionStatus.PROPOSED,  # MERGE = toujours PROPOSED
                    decision_source="rule",
                    tenant_id=tenant_id,
                    after_state={"merge_target_id": target["axis_id"]},
                )
                actions.append(action)
                processed_ids.add(source["axis_id"])
                break  # Un seul merge par axe

        logger.info(f"  → {len(actions)} axes temporels candidats à fusion")
        return actions

    def _load_axes(
        self, neo4j_driver, tenant_id: str, scope: str, scope_params: dict | None
    ) -> list:
        """Charge les axes applicabilité."""
        with neo4j_driver.session() as session:
            if scope == HygieneRunScope.DOCUMENT_SET.value and scope_params and scope_params.get("doc_ids"):
                result = session.run(
                    """
                    MATCH (c:Claim {tenant_id: $tid})-[:HAS_AXIS]->(a:ApplicabilityAxis {tenant_id: $tid})
                    WHERE c.doc_id IN $doc_ids
                      AND a._hygiene_status IS NULL
                    RETURN DISTINCT a.axis_id AS axis_id, a.axis_key AS axis_key,
                           a.values AS values
                    """,
                    tid=tenant_id,
                    doc_ids=scope_params["doc_ids"],
                )
            else:
                result = session.run(
                    """
                    MATCH (a:ApplicabilityAxis {tenant_id: $tid})
                    WHERE a._hygiene_status IS NULL
                    RETURN a.axis_id AS axis_id, a.axis_key AS axis_key,
                           a.values AS values
                    """,
                    tid=tenant_id,
                )
            axes = []
            for r in result:
                vals = r.get("values")
                if isinstance(vals, str):
                    vals = [vals]
                elif vals is None:
                    vals = []
                axes.append({
                    "axis_id": r["axis_id"],
                    "axis_key": r.get("axis_key", ""),
                    "values": vals,
                })
            return axes
