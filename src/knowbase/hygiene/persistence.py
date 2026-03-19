"""Persistence Neo4j pour les HygieneAction."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
)

logger = logging.getLogger("[OSMOSE] kg_hygiene_persistence")


class HygieneActionPersister:
    """CRUD HygieneAction dans Neo4j."""

    def __init__(self, neo4j_driver):
        self._driver = neo4j_driver

    def save_action(self, action: HygieneAction) -> None:
        """Persiste une HygieneAction dans Neo4j."""
        props = action.to_neo4j_properties()
        with self._driver.session() as session:
            session.run(
                """
                MERGE (ha:HygieneAction {action_id: $action_id})
                SET ha += $props
                """,
                action_id=action.action_id,
                props=props,
            )

    def save_actions_batch(self, actions: List[HygieneAction]) -> int:
        """Persiste un batch d'actions."""
        saved = 0
        with self._driver.session() as session:
            for action in actions:
                props = action.to_neo4j_properties()
                session.run(
                    """
                    MERGE (ha:HygieneAction {action_id: $action_id})
                    SET ha += $props
                    """,
                    action_id=action.action_id,
                    props=props,
                )
                saved += 1
        return saved

    def get_action(self, action_id: str) -> Optional[HygieneAction]:
        """Récupère une action par ID."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (ha:HygieneAction {action_id: $action_id}) RETURN ha",
                action_id=action_id,
            )
            record = result.single()
            if not record:
                return None
            return HygieneAction.from_neo4j_record(dict(record["ha"]))

    def list_actions(
        self,
        tenant_id: str = "default",
        status: Optional[str] = None,
        layer: Optional[int] = None,
        action_type: Optional[str] = None,
        batch_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[HygieneAction]:
        """Liste les actions avec filtres."""
        where_clauses = ["ha.tenant_id = $tenant_id"]
        params: Dict = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

        if status:
            where_clauses.append("ha.status = $status")
            params["status"] = status
        if layer is not None:
            where_clauses.append("ha.layer = $layer")
            params["layer"] = layer
        if action_type:
            where_clauses.append("ha.action_type = $action_type")
            params["action_type"] = action_type
        if batch_id:
            where_clauses.append("ha.batch_id = $batch_id")
            params["batch_id"] = batch_id

        where = " AND ".join(where_clauses)

        with self._driver.session() as session:
            result = session.run(
                f"""
                MATCH (ha:HygieneAction)
                WHERE {where}
                RETURN ha
                ORDER BY ha.applied_at DESC
                SKIP $offset LIMIT $limit
                """,
                **params,
            )
            return [
                HygieneAction.from_neo4j_record(dict(r["ha"]))
                for r in result
            ]

    def count_actions(
        self,
        tenant_id: str = "default",
        status: Optional[str] = None,
    ) -> int:
        """Compte les actions."""
        where_clauses = ["ha.tenant_id = $tenant_id"]
        params: Dict = {"tenant_id": tenant_id}
        if status:
            where_clauses.append("ha.status = $status")
            params["status"] = status

        where = " AND ".join(where_clauses)
        with self._driver.session() as session:
            result = session.run(
                f"MATCH (ha:HygieneAction) WHERE {where} RETURN count(ha) AS cnt",
                **params,
            )
            return result.single()["cnt"]

    def update_status(
        self,
        action_id: str,
        new_status: HygieneActionStatus,
        **extra_fields,
    ) -> bool:
        """Met à jour le statut d'une action."""
        set_clauses = ["ha.status = $new_status"]
        params: Dict = {"action_id": action_id, "new_status": new_status.value}

        for key, value in extra_fields.items():
            set_clauses.append(f"ha.{key} = ${key}")
            params[key] = value

        set_clause = ", ".join(set_clauses)
        with self._driver.session() as session:
            result = session.run(
                f"""
                MATCH (ha:HygieneAction {{action_id: $action_id}})
                SET {set_clause}
                RETURN ha.action_id AS aid
                """,
                **params,
            )
            return result.single() is not None

    def get_stats(self, tenant_id: str = "default") -> dict:
        """Stats agrégées des actions d'hygiène."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (ha:HygieneAction {tenant_id: $tenant_id})
                RETURN ha.status AS status, ha.layer AS layer,
                       ha.action_type AS action_type, count(*) AS cnt
                """,
                tenant_id=tenant_id,
            )
            stats = {
                "total": 0,
                "by_status": {},
                "by_layer": {},
                "by_type": {},
            }
            for r in result:
                cnt = r["cnt"]
                stats["total"] += cnt
                status = r["status"]
                layer = r["layer"]
                atype = r["action_type"]
                stats["by_status"][status] = stats["by_status"].get(status, 0) + cnt
                stats["by_layer"][str(layer)] = stats["by_layer"].get(str(layer), 0) + cnt
                stats["by_type"][atype] = stats["by_type"].get(atype, 0) + cnt
            return stats

    def is_already_suppressed(self, target_node_id: str, tenant_id: str = "default") -> bool:
        """Vérifie si un noeud est déjà supprimé (via HygieneAction OU flag direct)."""
        with self._driver.session() as session:
            # Vérifier le flag directement sur l'entité (plus fiable)
            flag_result = session.run(
                """
                MATCH (e {tenant_id: $tenant_id})
                WHERE (e.entity_id = $target_node_id
                    OR e.canonical_id = $target_node_id
                    OR e.axis_id = $target_node_id)
                  AND e._hygiene_status = 'suppressed'
                RETURN count(e) > 0 AS exists
                """,
                target_node_id=target_node_id,
                tenant_id=tenant_id,
            )
            flag_record = flag_result.single()
            if flag_record and flag_record["exists"]:
                return True

            # Fallback: vérifier via HygieneAction persistée
            result = session.run(
                """
                MATCH (ha:HygieneAction {
                    target_node_id: $target_node_id,
                    tenant_id: $tenant_id,
                    status: 'APPLIED'
                })
                RETURN count(ha) > 0 AS exists
                """,
                target_node_id=target_node_id,
                tenant_id=tenant_id,
            )
            return result.single()["exists"]

    @staticmethod
    def _sanitize_props(props: dict) -> dict:
        """Convertit les types Neo4j natifs en types JSON-sérialisables."""
        sanitized = {}
        for key, value in props.items():
            if hasattr(value, "isoformat"):
                # neo4j.time.DateTime, datetime, date, etc.
                sanitized[key] = value.isoformat()
            elif isinstance(value, (list, tuple)):
                sanitized[key] = [
                    v.isoformat() if hasattr(v, "isoformat") else v
                    for v in value
                ]
            else:
                sanitized[key] = value
        return sanitized

    def snapshot_node_light(self, node_id: str, node_label: str, tenant_id: str) -> dict:
        """Snapshot léger : propriétés du noeud uniquement (pas de relations)."""
        id_field_map = {
            "Entity": "entity_id",
            "CanonicalEntity": "canonical_entity_id",
            "ApplicabilityAxis": "axis_id",
        }
        id_field = id_field_map.get(node_label, "entity_id")

        try:
            with self._driver.session() as session:
                result = session.run(
                    f"""
                    MATCH (n:{node_label} {{{id_field}: $node_id, tenant_id: $tid}})
                    RETURN properties(n) AS props
                    """,
                    node_id=node_id,
                    tid=tenant_id,
                )
                record = result.single()
                if record:
                    return {"node": self._sanitize_props(dict(record["props"]))}
        except Exception:
            pass
        return {"node": {}}

    def snapshot_node(self, node_id: str, node_label: str, tenant_id: str) -> dict:
        """
        Capture un snapshot complet d'un noeud + relations adjacentes.

        Returns:
            {"node": {...}, "relations": [...]}
        """
        with self._driver.session() as session:
            # ID field depends on node type
            id_field_map = {
                "Entity": "entity_id",
                "CanonicalEntity": "canonical_entity_id",
                "ApplicabilityAxis": "axis_id",
            }
            id_field = id_field_map.get(node_label, "entity_id")

            # Get node properties
            node_result = session.run(
                f"""
                MATCH (n:{node_label} {{{id_field}: $node_id, tenant_id: $tid}})
                RETURN properties(n) AS props
                """,
                node_id=node_id,
                tid=tenant_id,
            )
            node_record = node_result.single()
            if not node_record:
                return {"node": {}, "relations": []}

            node_props = self._sanitize_props(dict(node_record["props"]))

            # Get adjacent relations (1 hop)
            rel_result = session.run(
                f"""
                MATCH (n:{node_label} {{{id_field}: $node_id, tenant_id: $tid}})-[r]-(other)
                RETURN type(r) AS rel_type,
                       CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END AS direction,
                       labels(other)[0] AS other_label,
                       COALESCE(other.entity_id, other.claim_id, other.canonical_id,
                                other.axis_id, other.facet_id, other.qs_id,
                                other.cluster_id, other.slug) AS other_id,
                       properties(r) AS rel_props
                """,
                node_id=node_id,
                tid=tenant_id,
            )
            relations = []
            for r in rel_result:
                relations.append({
                    "type": r["rel_type"],
                    "direction": r["direction"],
                    "other_id": r["other_id"],
                    "other_label": r["other_label"],
                    "props": self._sanitize_props(dict(r["rel_props"])) if r["rel_props"] else {},
                })

            return {"node": node_props, "relations": relations}
