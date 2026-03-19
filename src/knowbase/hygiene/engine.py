"""Orchestrateur du système d'hygiène KG."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneRunResult,
    HygieneRunScope,
)
from knowbase.hygiene.persistence import HygieneActionPersister
from knowbase.hygiene.rules.base import HygieneRule
from knowbase.hygiene.rules.layer1_entities import (
    DomainStoplistRule,
    InvalidEntityNameRule,
    StructuralEntityRule,
)
# layer1_axes et layer2_axes désactivés — schéma ApplicabilityAxis incompatible
# avec les requêtes actuelles. Sera remplacé par un L3 dédié axes.

logger = logging.getLogger("[OSMOSE] kg_hygiene_engine")


# Registry des règles par couche
LAYER1_RULES: List[HygieneRule] = [
    StructuralEntityRule(),
    InvalidEntityNameRule(),
    DomainStoplistRule(),
    # ConservativeAxisMergeRule() — désactivé, en attente L3 axes
]

LAYER2_RULES: List[HygieneRule] = []  # Chargées dynamiquement (dépendances LLM)


def _get_layer2_rules() -> List[HygieneRule]:
    """Charge les règles L2 (lazy import pour éviter dépendances LLM au boot)."""
    from knowbase.hygiene.rules.acronym_dedup import AcronymDedupRule
    from knowbase.hygiene.rules.layer2_entities import (
        CanonicalDedupRule,
        SameCanonEntityDedupRule,
        SingletonNoiseRule,
        WeakEntityRule,
    )
    # AxisCoherenceRule désactivée — en attente L3 axes dédié

    return [
        AcronymDedupRule(),
        SingletonNoiseRule(),
        WeakEntityRule(),
        CanonicalDedupRule(),
        SameCanonEntityDedupRule(),
    ]


def _get_layer3_rules() -> List[HygieneRule]:
    """Charge les règles L3 axes (lazy import)."""
    from knowbase.hygiene.rules.layer3_axes import (
        LowValueAxisRule,
        MisnamedAxisRule,
        RedundantAxisRule,
    )

    return [
        LowValueAxisRule(),
        RedundantAxisRule(),
        MisnamedAxisRule(),
    ]


class HygieneEngine:
    """Moteur d'hygiène KG — scan → snapshot → execute → persist."""

    def __init__(self, neo4j_driver, tenant_id: str = "default"):
        self._driver = neo4j_driver
        self._tenant_id = tenant_id
        self._persister = HygieneActionPersister(neo4j_driver)

    def run(
        self,
        dry_run: bool = False,
        layers: Optional[List[int]] = None,
        scope: HygieneRunScope = HygieneRunScope.TENANT,
        scope_params: Optional[Dict] = None,
        auto_apply_threshold: float = 0.9,
    ) -> HygieneRunResult:
        """
        Lance un run d'hygiène.

        Args:
            dry_run: Preview sans modification
            layers: Couches à exécuter [1], [2], ou [1, 2]
            scope: Scope du run
            scope_params: Paramètres du scope (ex: {"doc_ids": [...]})
            auto_apply_threshold: Seuil auto-apply L2

        Returns:
            HygieneRunResult avec toutes les actions
        """
        if layers is None:
            layers = [1]

        batch_id = f"hyg_run_{uuid.uuid4().hex[:8]}"
        result = HygieneRunResult(batch_id=batch_id, dry_run=dry_run)

        logger.info(
            f"[OSMOSE:Hygiene] Starting run batch={batch_id} "
            f"layers={layers} scope={scope.value} dry_run={dry_run}"
        )

        # Collecter les règles
        rules: List[HygieneRule] = []
        if 1 in layers:
            rules.extend(LAYER1_RULES)
        if 2 in layers:
            rules.extend(_get_layer2_rules())
        if 3 in layers:
            rules.extend(_get_layer3_rules())

        # Exécuter chaque règle
        for rule in rules:
            try:
                logger.info(f"  Running rule: {rule.name} (L{rule.layer})")
                scan_kwargs = {
                    "neo4j_driver": self._driver,
                    "tenant_id": self._tenant_id,
                    "batch_id": batch_id,
                    "scope": scope.value,
                    "scope_params": scope_params,
                    "dry_run": dry_run,
                }
                # L2 rules may accept auto_apply_threshold
                if rule.layer == 2:
                    import inspect
                    sig = inspect.signature(rule.scan)
                    if "auto_apply_threshold" in sig.parameters:
                        scan_kwargs["auto_apply_threshold"] = auto_apply_threshold

                actions = rule.scan(**scan_kwargs)

                for action in actions:
                    # Idempotence: skip si noeud déjà supprimé
                    if self._persister.is_already_suppressed(
                        action.target_node_id, self._tenant_id
                    ):
                        result.skipped_already_suppressed += 1
                        continue

                    # Enrichir avec le nom du noeud cible (utile pour l'UI)
                    if "target_name" not in action.after_state:
                        target_name = self._resolve_node_name(
                            action.target_node_id, action.target_node_type
                        )
                        if target_name:
                            action.after_state["target_name"] = target_name

                    if dry_run:
                        # Snapshot léger en dry run (props seulement, pas de relations)
                        action.before_state = self._persister.snapshot_node_light(
                            action.target_node_id,
                            action.target_node_type,
                            self._tenant_id,
                        )
                    else:
                        # Snapshot complet pour rollback
                        action.before_state = self._persister.snapshot_node(
                            action.target_node_id,
                            action.target_node_type,
                            self._tenant_id,
                        )

                        # Appliquer si status = APPLIED
                        if action.status == HygieneActionStatus.APPLIED:
                            success = rule.apply_action(self._driver, action)
                            if success:
                                result.applied += 1
                                # Flag wiki stale si impact
                                self._flag_wiki_stale(action)
                            else:
                                action.status = HygieneActionStatus.PROPOSED
                                result.proposed += 1
                        else:
                            result.proposed += 1

                        # Persister l'action
                        self._persister.save_action(action)

                    result.actions.append(action)
                    result.total_actions += 1

            except Exception as e:
                error_msg = f"Rule {rule.name} failed: {e}"
                logger.error(f"[OSMOSE:Hygiene] {error_msg}")
                result.errors.append(error_msg)

        logger.info(
            f"[OSMOSE:Hygiene] Run complete: {result.total_actions} actions "
            f"({result.applied} applied, {result.proposed} proposed, "
            f"{result.skipped_already_suppressed} skipped)"
        )

        return result

    def _resolve_node_name(self, node_id: str, node_type: str) -> Optional[str]:
        """Résout le nom d'un noeud par son ID."""
        id_field_map = {
            "Entity": "entity_id",
            "CanonicalEntity": "canonical_entity_id",
            "ApplicabilityAxis": "axis_id",
        }
        id_field = id_field_map.get(node_type, "entity_id")
        name_field = "axis_key" if node_type == "ApplicabilityAxis" else "name"

        try:
            with self._driver.session() as session:
                result = session.run(
                    f"""
                    MATCH (n:{node_type} {{{id_field}: $node_id, tenant_id: $tid}})
                    RETURN n.{name_field} AS name
                    """,
                    node_id=node_id,
                    tid=self._tenant_id,
                )
                record = result.single()
                if record:
                    return record["name"]
        except Exception:
            pass
        return None

    def _flag_wiki_stale(self, action: HygieneAction) -> None:
        """Flag les WikiArticle dont le concept source est impacté."""
        try:
            with self._driver.session() as session:
                session.run(
                    """
                    MATCH (wa:WikiArticle)-[:ABOUT]->(e)
                    WHERE (e.entity_id = $node_id OR e.canonical_id = $node_id)
                      AND wa.tenant_id = $tid
                    SET wa._wiki_stale = true
                    """,
                    node_id=action.target_node_id,
                    tid=self._tenant_id,
                )
        except Exception as e:
            logger.warning(f"Flag wiki stale failed: {e}")
