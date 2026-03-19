"""Rollback best-effort pour les actions d'hygiène."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
)
from knowbase.hygiene.persistence import HygieneActionPersister

logger = logging.getLogger("[OSMOSE] kg_hygiene_rollback")


class RollbackResult:
    """Résultat d'un rollback."""

    def __init__(self):
        self.success: bool = False
        self.relations_restored: int = 0
        self.relations_failed: int = 0
        self.failed_reasons: List[str] = []
        self.partial: bool = False

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "relations_restored": self.relations_restored,
            "relations_failed": self.relations_failed,
            "failed_reasons": self.failed_reasons,
            "partial": self.partial,
        }


class HygieneRollback:
    """Rollback best-effort des actions d'hygiène."""

    def __init__(self, neo4j_driver):
        self._driver = neo4j_driver
        self._persister = HygieneActionPersister(neo4j_driver)

    def rollback_action(self, action_id: str) -> RollbackResult:
        """Rollback une action unique."""
        result = RollbackResult()

        action = self._persister.get_action(action_id)
        if not action:
            result.failed_reasons.append(f"Action {action_id} introuvable")
            return result

        if action.status != HygieneActionStatus.APPLIED:
            result.failed_reasons.append(
                f"Action {action_id} non rollbackable (status={action.status.value})"
            )
            return result

        if action.action_type in (
            HygieneActionType.SUPPRESS_ENTITY,
            HygieneActionType.SUPPRESS_AXIS,
        ):
            result = self._rollback_suppress(action)
        elif action.action_type == HygieneActionType.HARD_DELETE_ENTITY:
            result = self._rollback_hard_delete(action)
        elif action.action_type == HygieneActionType.MERGE_CANONICAL:
            result = self._rollback_merge(action)
        elif action.action_type == HygieneActionType.MERGE_AXIS:
            result = self._rollback_merge(action)
        elif action.action_type == HygieneActionType.MERGE_ENTITY:
            result = self._rollback_merge_entity(action)
        else:
            result.failed_reasons.append(f"Type {action.action_type} non supporté pour rollback")
            return result

        if result.success:
            now = datetime.now(timezone.utc).isoformat()
            self._persister.update_status(
                action_id,
                HygieneActionStatus.ROLLED_BACK,
                rolled_back_at=now,
            )
            # Flag wiki articles as stale if applicable
            self._flag_wiki_stale_for_rollback(action)

        return result

    def rollback_batch(self, batch_id: str, tenant_id: str = "default") -> List[Dict]:
        """Rollback un batch entier (ordre inverse chronologique)."""
        actions = self._persister.list_actions(
            tenant_id=tenant_id,
            batch_id=batch_id,
            status=HygieneActionStatus.APPLIED.value,
            limit=1000,
        )
        # Tri inverse chronologique
        actions.sort(key=lambda a: a.applied_at or "", reverse=True)

        results = []
        for action in actions:
            rb_result = self.rollback_action(action.action_id)
            results.append({
                "action_id": action.action_id,
                "target_node_id": action.target_node_id,
                **rb_result.to_dict(),
            })

        return results

    def _rollback_suppress(self, action: HygieneAction) -> RollbackResult:
        """Rollback d'un SUPPRESS : retirer les flags."""
        result = RollbackResult()

        id_field_map = {
            "Entity": "entity_id",
            "CanonicalEntity": "canonical_entity_id",
            "ApplicabilityAxis": "axis_id",
        }
        id_field = id_field_map.get(action.target_node_type, "entity_id")

        with self._driver.session() as session:
            r = session.run(
                f"""
                MATCH (n:{action.target_node_type} {{{id_field}: $node_id, tenant_id: $tid}})
                REMOVE n._hygiene_status, n._hygiene_action_id, n._hygiene_rule, n._hygiene_at
                RETURN n IS NOT NULL AS found
                """,
                node_id=action.target_node_id,
                tid=action.tenant_id,
            )
            record = r.single()
            if record and record["found"]:
                result.success = True
            else:
                result.failed_reasons.append("Noeud introuvable pour retrait du flag")

        return result

    def _rollback_hard_delete(self, action: HygieneAction) -> RollbackResult:
        """Rollback d'un HARD_DELETE : recréer le noeud + relations best-effort."""
        result = RollbackResult()
        before = action.before_state

        if not before.get("node"):
            result.failed_reasons.append("Pas de snapshot before_state.node")
            return result

        node_props = before["node"]
        relations = before.get("relations", [])

        id_field_map = {
            "Entity": "entity_id",
            "CanonicalEntity": "canonical_entity_id",
            "ApplicabilityAxis": "axis_id",
        }
        id_field = id_field_map.get(action.target_node_type, "entity_id")

        with self._driver.session() as session:
            # Recréer le noeud
            session.run(
                f"""
                CREATE (n:{action.target_node_type})
                SET n = $props
                """,
                props=node_props,
            )

            # Recréer les relations
            for rel in relations:
                other_id = rel.get("other_id")
                if not other_id:
                    result.relations_failed += 1
                    result.failed_reasons.append(f"Relation sans other_id: {rel.get('type')}")
                    continue

                other_label = rel.get("other_label", "Entity")
                rel_type = rel["type"]
                direction = rel.get("direction", "outgoing")
                rel_props = rel.get("props", {})

                # Déterminer le champ ID pour le noeud voisin
                other_id_field = _guess_id_field(other_label)

                # Vérifier que le voisin existe encore
                check = session.run(
                    f"""
                    MATCH (other:{other_label} {{{other_id_field}: $other_id}})
                    RETURN other IS NOT NULL AS exists
                    """,
                    other_id=other_id,
                )
                check_record = check.single()
                if not check_record or not check_record["exists"]:
                    result.relations_failed += 1
                    result.failed_reasons.append(
                        f"Voisin {other_label}:{other_id} n'existe plus"
                    )
                    continue

                # Recréer la relation
                if direction == "outgoing":
                    session.run(
                        f"""
                        MATCH (n:{action.target_node_type} {{{id_field}: $node_id}})
                        MATCH (other:{other_label} {{{other_id_field}: $other_id}})
                        CREATE (n)-[r:{rel_type}]->(other)
                        SET r = $rel_props
                        """,
                        node_id=action.target_node_id,
                        other_id=other_id,
                        rel_props=rel_props,
                    )
                else:
                    session.run(
                        f"""
                        MATCH (n:{action.target_node_type} {{{id_field}: $node_id}})
                        MATCH (other:{other_label} {{{other_id_field}: $other_id}})
                        CREATE (other)-[r:{rel_type}]->(n)
                        SET r = $rel_props
                        """,
                        node_id=action.target_node_id,
                        other_id=other_id,
                        rel_props=rel_props,
                    )
                result.relations_restored += 1

        result.success = True
        if result.relations_failed > 0:
            result.partial = True

        return result

    def _rollback_merge_entity(self, action: HygieneAction) -> RollbackResult:
        """Rollback d'un MERGE_ENTITY : recréer le nœud source + re-transférer les claims."""
        result = RollbackResult()
        before = action.before_state

        if not before.get("node"):
            result.failed_reasons.append("Pas de snapshot before_state.node — rollback impossible")
            return result

        # 1. Recréer le nœud Entity source (comme HARD_DELETE)
        node_props = before["node"]
        relations = before.get("relations", [])
        source_entity_id = action.target_node_id
        target_entity_id = action.after_state.get("merge_target_entity_id")

        with self._driver.session() as session:
            # Recréer le nœud
            session.run(
                """
                CREATE (n:Entity)
                SET n = $props
                """,
                props=node_props,
            )

            # Recréer les relations depuis le snapshot
            for rel in relations:
                other_id = rel.get("other_id")
                if not other_id:
                    result.relations_failed += 1
                    continue

                other_label = rel.get("other_label", "Entity")
                rel_type = rel["type"]
                direction = rel.get("direction", "outgoing")
                rel_props = rel.get("props", {})
                other_id_field = _guess_id_field(other_label)

                # Vérifier que le voisin existe encore
                check = session.run(
                    f"""
                    MATCH (other:{other_label} {{{other_id_field}: $other_id}})
                    RETURN other IS NOT NULL AS exists
                    """,
                    other_id=other_id,
                )
                check_record = check.single()
                if not check_record or not check_record["exists"]:
                    result.relations_failed += 1
                    result.failed_reasons.append(
                        f"Voisin {other_label}:{other_id} n'existe plus"
                    )
                    continue

                if direction == "outgoing":
                    session.run(
                        f"""
                        MATCH (n:Entity {{entity_id: $node_id}})
                        MATCH (other:{other_label} {{{other_id_field}: $other_id}})
                        CREATE (n)-[r:{rel_type}]->(other)
                        SET r = $rel_props
                        """,
                        node_id=source_entity_id,
                        other_id=other_id,
                        rel_props=rel_props,
                    )
                else:
                    session.run(
                        f"""
                        MATCH (n:Entity {{entity_id: $node_id}})
                        MATCH (other:{other_label} {{{other_id_field}: $other_id}})
                        CREATE (other)-[r:{rel_type}]->(n)
                        SET r = $rel_props
                        """,
                        node_id=source_entity_id,
                        other_id=other_id,
                        rel_props=rel_props,
                    )
                result.relations_restored += 1

            # 2. Retirer du target les claims qui étaient à l'origine liés au source
            #    (on les retrouve dans les relations snapshot de type ABOUT incoming)
            if target_entity_id:
                about_claim_ids = [
                    rel["other_id"]
                    for rel in relations
                    if rel.get("type") == "ABOUT"
                    and rel.get("direction") == "incoming"
                    and rel.get("other_label") == "Claim"
                ]
                if about_claim_ids:
                    session.run(
                        """
                        MATCH (target:Entity {entity_id: $target_id})
                        UNWIND $claim_ids AS cid
                        MATCH (c:Claim {claim_id: cid})-[r:ABOUT]->(target)
                        DELETE r
                        """,
                        target_id=target_entity_id,
                        claim_ids=about_claim_ids,
                    )
                    logger.info(
                        f"MERGE_ENTITY rollback: {len(about_claim_ids)} claims "
                        f"détachés du target '{target_entity_id}'"
                    )

        result.success = True
        if result.relations_failed > 0:
            result.partial = True

        return result

    def _rollback_merge(self, action: HygieneAction) -> RollbackResult:
        """Rollback d'un MERGE : restaurer l'entité absorbée."""
        # Réutilise la même logique que hard_delete rollback
        return self._rollback_hard_delete(action)

    def _flag_wiki_stale_for_rollback(self, action: HygieneAction) -> None:
        """Flag les WikiArticle dont le concept source a été modifié par rollback."""
        try:
            with self._driver.session() as session:
                # Chercher les WikiArticle liés à ce noeud
                session.run(
                    """
                    MATCH (wa:WikiArticle)-[:ABOUT]->(e)
                    WHERE (e.entity_id = $node_id OR e.canonical_id = $node_id)
                      AND wa.tenant_id = $tid
                    SET wa._wiki_stale = true
                    """,
                    node_id=action.target_node_id,
                    tid=action.tenant_id,
                )
        except Exception as e:
            logger.warning(f"Flag wiki stale après rollback échoué: {e}")


def _guess_id_field(label: str) -> str:
    """Devine le champ ID d'un noeud Neo4j par son label."""
    label_to_id = {
        "Entity": "entity_id",
        "CanonicalEntity": "canonical_entity_id",
        "ApplicabilityAxis": "axis_id",
        "Claim": "claim_id",
        "Facet": "facet_id",
        "QuestionSignature": "qs_id",
        "ClaimCluster": "cluster_id",
        "WikiArticle": "slug",
        "WikiCategory": "category_key",
    }
    return label_to_id.get(label, "entity_id")
