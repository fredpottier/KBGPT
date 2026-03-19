"""Classe abstraite pour les règles d'hygiène KG."""

from __future__ import annotations

import abc
from typing import List

from knowbase.hygiene.models import HygieneAction


class HygieneRule(abc.ABC):
    """Règle d'hygiène abstraite."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Nom unique de la règle."""

    @property
    @abc.abstractmethod
    def layer(self) -> int:
        """Couche (1 ou 2)."""

    @property
    def description(self) -> str:
        return ""

    @abc.abstractmethod
    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        """
        Scanne le graphe et retourne les actions proposées.

        Args:
            neo4j_driver: Driver Neo4j
            tenant_id: ID tenant
            batch_id: ID du run courant
            scope: "tenant" | "document_set"
            scope_params: Params optionnels (ex: {"doc_ids": [...]})
            dry_run: Si True, ne pas appliquer

        Returns:
            Liste d'actions à appliquer/proposer
        """

    def apply_action(self, neo4j_driver, action: HygieneAction) -> bool:
        """
        Applique une action sur le graphe.

        Par défaut : SUPPRESS (ajout flag).
        Override pour MERGE, HARD_DELETE, etc.
        """
        from knowbase.hygiene.models import HygieneActionType

        if action.action_type in (
            HygieneActionType.SUPPRESS_ENTITY,
            HygieneActionType.SUPPRESS_AXIS,
        ):
            return self._apply_suppress(neo4j_driver, action)
        if action.action_type == HygieneActionType.MERGE_CANONICAL:
            return self._apply_merge_canonical(neo4j_driver, action)
        if action.action_type == HygieneActionType.MERGE_ENTITY:
            return self._apply_merge_entity(neo4j_driver, action)
        return False

    def _apply_suppress(self, neo4j_driver, action: HygieneAction) -> bool:
        """Applique un SUPPRESS : ajoute les flags d'hygiène."""
        from datetime import datetime, timezone

        id_field_map = {
            "Entity": "entity_id",
            "CanonicalEntity": "canonical_entity_id",
            "ApplicabilityAxis": "axis_id",
        }
        id_field = id_field_map.get(action.target_node_type, "entity_id")
        now = datetime.now(timezone.utc).isoformat()

        with neo4j_driver.session() as session:
            result = session.run(
                f"""
                MATCH (n:{action.target_node_type} {{{id_field}: $node_id, tenant_id: $tid}})
                SET n._hygiene_status = 'suppressed',
                    n._hygiene_action_id = $action_id,
                    n._hygiene_rule = $rule_name,
                    n._hygiene_at = $now
                RETURN n IS NOT NULL AS found
                """,
                node_id=action.target_node_id,
                tid=action.tenant_id,
                action_id=action.action_id,
                rule_name=action.rule_name,
                now=now,
            )
            record = result.single()
            if record and record["found"]:
                action.applied_at = now
                return True
        return False

    def _apply_merge_canonical(self, neo4j_driver, action: HygieneAction) -> bool:
        """Applique un MERGE_CANONICAL : lie une Entity vers un CanonicalEntity via SAME_CANON_AS.

        Crée le CanonicalEntity s'il n'existe pas encore (auto-apply).
        """
        from datetime import datetime, timezone

        target_id = action.after_state.get("merge_target_id")
        if not target_id:
            return False

        source_id = action.target_node_id
        canonical_name = action.after_state.get("canonical_name", "")
        now = datetime.now(timezone.utc).isoformat()

        try:
            with neo4j_driver.session() as session:
                # Étape 1 : Assurer l'existence du CanonicalEntity (MERGE)
                session.run(
                    """
                    MERGE (ce:CanonicalEntity {
                        canonical_entity_id: $target_id,
                        tenant_id: $tid
                    })
                    ON CREATE SET ce.canonical_name = $canonical_name,
                                  ce.entity_type = 'concept',
                                  ce.method = 'hygiene_acronym_dedup',
                                  ce.created_at = datetime()
                    """,
                    target_id=target_id,
                    tid=action.tenant_id,
                    canonical_name=canonical_name,
                )

                # Étape 2 : Lier Entity → CanonicalEntity + flags hygiene
                result = session.run(
                    """
                    MATCH (source:Entity {entity_id: $source_id, tenant_id: $tid})
                    MATCH (target:CanonicalEntity {canonical_entity_id: $target_id, tenant_id: $tid})
                    MERGE (source)-[r:SAME_CANON_AS]->(target)
                    ON CREATE SET r.method = 'hygiene_acronym_dedup',
                                  r.confidence = $confidence,
                                  r.created_at = datetime()
                    SET source._hygiene_status = 'suppressed',
                        source._hygiene_action_id = $action_id,
                        source._hygiene_rule = $rule_name,
                        source._hygiene_at = $now,
                        target.aliases = CASE
                            WHEN target.aliases IS NULL THEN [source.name]
                            WHEN NOT source.name IN target.aliases THEN target.aliases + source.name
                            ELSE target.aliases
                        END
                    RETURN source IS NOT NULL AS found
                    """,
                    source_id=source_id,
                    target_id=target_id,
                    tid=action.tenant_id,
                    confidence=action.confidence,
                    action_id=action.action_id,
                    rule_name=action.rule_name,
                    now=now,
                )
                record = result.single()
                if record and record["found"]:
                    action.applied_at = now
                    return True
        except Exception:
            import logging
            logging.getLogger("[OSMOSE] kg_hygiene_base").error(
                f"Erreur lors du MERGE_CANONICAL {action.action_id}", exc_info=True
            )
        return False

    def _apply_merge_entity(self, neo4j_driver, action: HygieneAction) -> bool:
        """Applique un MERGE_ENTITY : transfère claims/relations du source vers le target, puis supprime le source.

        after_state doit contenir :
        - merge_target_entity_id : entity_id de l'entité cible (la plus grosse)
        """
        from datetime import datetime, timezone

        import logging as _logging

        _logger = _logging.getLogger("[OSMOSE] kg_hygiene_base")

        target_entity_id = action.after_state.get("merge_target_entity_id")
        if not target_entity_id:
            return False

        source_entity_id = action.target_node_id
        now = datetime.now(timezone.utc).isoformat()

        try:
            with neo4j_driver.session() as session:
                # 1. Transférer les relations ABOUT (Claim→Entity) du source vers le target
                transfer_result = session.run(
                    """
                    MATCH (source:Entity {entity_id: $source_id, tenant_id: $tid})
                    MATCH (target:Entity {entity_id: $target_id, tenant_id: $tid})
                    OPTIONAL MATCH (c:Claim)-[r:ABOUT]->(source)
                    WHERE NOT (c)-[:ABOUT]->(target)
                    WITH source, target, collect(c) AS claims_to_move
                    UNWIND claims_to_move AS claim
                    MERGE (claim)-[:ABOUT]->(target)
                    RETURN count(claim) AS transferred
                    """,
                    source_id=source_entity_id,
                    target_id=target_entity_id,
                    tid=action.tenant_id,
                )
                transferred = transfer_result.single()["transferred"]

                # 2. Transférer WikiArticle ABOUT
                session.run(
                    """
                    MATCH (source:Entity {entity_id: $source_id, tenant_id: $tid})
                    MATCH (target:Entity {entity_id: $target_id, tenant_id: $tid})
                    OPTIONAL MATCH (wa:WikiArticle)-[r:ABOUT]->(source)
                    WHERE NOT (wa)-[:ABOUT]->(target)
                    WITH source, target, collect(wa) AS wikis
                    UNWIND wikis AS w
                    MERGE (w)-[:ABOUT]->(target)
                    """,
                    source_id=source_entity_id,
                    target_id=target_entity_id,
                    tid=action.tenant_id,
                )

                # 3. Fusionner les aliases (ajouter source.name + source.aliases au target)
                session.run(
                    """
                    MATCH (source:Entity {entity_id: $source_id, tenant_id: $tid})
                    MATCH (target:Entity {entity_id: $target_id, tenant_id: $tid})
                    WITH source, target,
                         coalesce(target.aliases, []) AS existing,
                         coalesce(source.aliases, []) + [source.name] AS to_add
                    WITH target, existing,
                         [x IN to_add WHERE NOT x IN existing] AS new_aliases
                    SET target.aliases = existing + new_aliases
                    """,
                    source_id=source_entity_id,
                    target_id=target_entity_id,
                    tid=action.tenant_id,
                )

                # 4. Supprimer toutes les relations du source puis le nœud
                session.run(
                    """
                    MATCH (source:Entity {entity_id: $source_id, tenant_id: $tid})
                    DETACH DELETE source
                    """,
                    source_id=source_entity_id,
                    tid=action.tenant_id,
                )

                action.applied_at = now
                _logger.info(
                    f"MERGE_ENTITY: '{source_entity_id}' → '{target_entity_id}' "
                    f"({transferred} claims transférés)"
                )
                return True

        except Exception:
            _logger.error(
                f"Erreur lors du MERGE_ENTITY {action.action_id}", exc_info=True
            )
        return False
