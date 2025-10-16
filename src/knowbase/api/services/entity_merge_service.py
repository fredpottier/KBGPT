"""
EntityMergeService - Merge entités Neo4j en préservant relations.

Phase 5B - Solution 3 Hybride
Step 4 - Merge sécurisé avec transfert relations

Fusionne entités duplicatas en transférant toutes les relations (IN + OUT)
vers l'entité master avant de supprimer les duplicatas.
"""
from typing import List, Dict, Optional
from datetime import datetime

from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "entity_merge.log")


class EntityMergeService:
    """Service de merge entités Neo4j avec préservation relations."""

    def __init__(self, kg_service: Optional[KnowledgeGraphService] = None):
        """
        Initialize service.

        Args:
            kg_service: Service Knowledge Graph (optionnel)
        """
        self.kg_service = kg_service or KnowledgeGraphService()

    def merge_entities(
        self,
        master_uuid: str,
        duplicate_uuids: List[str],
        canonical_name: str,
        tenant_id: str = "default"
    ) -> Dict:
        """
        Merge entités duplicatas vers master.

        **Opérations effectuées** (dans transaction):
        1. Transférer relations OUT des duplicatas vers master
        2. Transférer relations IN des duplicatas vers master
        3. Update master avec canonical_name + status=validated
        4. Delete duplicatas

        Args:
            master_uuid: UUID entité master (conservée)
            duplicate_uuids: UUIDs entités à merger (supprimées)
            canonical_name: Nom canonique final pour master
            tenant_id: Tenant ID

        Returns:
            Dict résultat:
            {
                "master_uuid": "...",
                "canonical_name": "...",
                "duplicates_merged": 3,
                "relations_transferred": {"out": 12, "in": 8},
                "merged_at": "2025-10-06T..."
            }
        """
        logger.info(
            f"🔄 Merge entités: master={master_uuid}, "
            f"duplicates={len(duplicate_uuids)}, canonical={canonical_name}"
        )

        # Filtrer master des duplicatas (ne pas merger master avec lui-même)
        duplicate_uuids_clean = [uid for uid in duplicate_uuids if uid != master_uuid]

        if len(duplicate_uuids_clean) == 0:
            logger.warning("Aucune entité duplicate à merger")
            return {
                "master_uuid": master_uuid,
                "canonical_name": canonical_name,
                "duplicates_merged": 0,
                "relations_transferred": {"out": 0, "in": 0},
                "merged_at": datetime.utcnow().isoformat()
            }

        # Exécuter merge dans transaction Neo4j
        result = self._execute_merge_transaction(
            master_uuid=master_uuid,
            duplicate_uuids=duplicate_uuids_clean,
            canonical_name=canonical_name,
            tenant_id=tenant_id
        )

        logger.info(
            f"✅ Merge terminé: {result['duplicates_merged']} duplicates supprimés, "
            f"{result['relations_transferred']['out']} OUT + "
            f"{result['relations_transferred']['in']} IN transférées"
        )

        return result

    def _execute_merge_transaction(
        self,
        master_uuid: str,
        duplicate_uuids: List[str],
        canonical_name: str,
        tenant_id: str
    ) -> Dict:
        """
        Exécute merge dans transaction Neo4j.

        Args:
            master_uuid: UUID master
            duplicate_uuids: UUIDs duplicates
            canonical_name: Nom canonique
            tenant_id: Tenant ID

        Returns:
            Dict résultat
        """
        from neo4j import GraphDatabase
        import os

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        relations_out = 0
        relations_in = 0

        with driver.session() as session:
            def _transaction_work(tx):
                nonlocal relations_out, relations_in

                # 1. Transférer relations OUT
                # Pour chaque relation sortante d'un duplicate vers une cible,
                # créer la même relation depuis master (si pas déjà existante)
                query_transfer_out = """
                MATCH (dup:Entity)-[r]->(target)
                WHERE dup.uuid IN $dup_uuids AND dup.tenant_id = $tenant_id
                MATCH (master:Entity {uuid: $master_uuid, tenant_id: $tenant_id})
                WHERE NOT (master)-[]->(target)
                WITH master, target, r, type(r) AS rel_type, properties(r) AS rel_props
                CALL apoc.create.relationship(master, rel_type, rel_props, target) YIELD rel
                RETURN count(rel) AS count_out
                """

                result_out = tx.run(
                    query_transfer_out,
                    dup_uuids=duplicate_uuids,
                    master_uuid=master_uuid,
                    tenant_id=tenant_id
                )
                record_out = result_out.single()
                relations_out = record_out["count_out"] if record_out else 0

                # 2. Transférer relations IN
                # Pour chaque relation entrante vers un duplicate depuis une source,
                # créer la même relation vers master (si pas déjà existante)
                query_transfer_in = """
                MATCH (source)-[r]->(dup:Entity)
                WHERE dup.uuid IN $dup_uuids AND dup.tenant_id = $tenant_id
                MATCH (master:Entity {uuid: $master_uuid, tenant_id: $tenant_id})
                WHERE NOT (source)-[]->(master)
                WITH source, master, r, type(r) AS rel_type, properties(r) AS rel_props
                CALL apoc.create.relationship(source, rel_type, rel_props, master) YIELD rel
                RETURN count(rel) AS count_in
                """

                result_in = tx.run(
                    query_transfer_in,
                    dup_uuids=duplicate_uuids,
                    master_uuid=master_uuid,
                    tenant_id=tenant_id
                )
                record_in = result_in.single()
                relations_in = record_in["count_in"] if record_in else 0

                # 3. Update master avec canonical name + status validated
                query_update_master = """
                MATCH (master:Entity {uuid: $master_uuid, tenant_id: $tenant_id})
                SET master.name = $canonical_name,
                    master.canonical_name = $canonical_name,
                    master.status = 'validated',
                    master.normalized_at = datetime(),
                    master.normalized_from = $dup_count
                RETURN master
                """

                tx.run(
                    query_update_master,
                    master_uuid=master_uuid,
                    canonical_name=canonical_name,
                    tenant_id=tenant_id,
                    dup_count=len(duplicate_uuids)
                )

                # 4. Delete duplicatas (DETACH DELETE pour supprimer relations restantes)
                query_delete_dups = """
                MATCH (dup:Entity)
                WHERE dup.uuid IN $dup_uuids AND dup.tenant_id = $tenant_id
                DETACH DELETE dup
                RETURN count(dup) AS deleted_count
                """

                result_delete = tx.run(
                    query_delete_dups,
                    dup_uuids=duplicate_uuids,
                    tenant_id=tenant_id
                )
                record_delete = result_delete.single()
                deleted_count = record_delete["deleted_count"] if record_delete else 0

                return deleted_count

            # Exécuter transaction
            deleted = session.execute_write(_transaction_work)

        driver.close()

        return {
            "master_uuid": master_uuid,
            "canonical_name": canonical_name,
            "duplicates_merged": deleted,
            "relations_transferred": {
                "out": relations_out,
                "in": relations_in
            },
            "merged_at": datetime.utcnow().isoformat()
        }

    def batch_merge_from_preview(
        self,
        merge_groups: List[Dict],
        tenant_id: str = "default"
    ) -> Dict:
        """
        Exécute batch merge depuis preview (plusieurs groupes).

        Args:
            merge_groups: Liste groupes depuis FuzzyMatcher
            tenant_id: Tenant ID

        Returns:
            Dict statistiques globales
        """
        logger.info(f"📦 Batch merge: {len(merge_groups)} groupes")

        # Fusionner les groupes avec le même canonical_name
        deduplicated_groups = self._deduplicate_canonical_names(merge_groups)
        logger.info(f"📊 Après déduplication: {len(deduplicated_groups)} groupes")

        total_merged = 0
        total_relations = {"out": 0, "in": 0}
        errors = []

        for group in deduplicated_groups:
            try:
                master_uuid = group["master_uuid"]
                canonical_name = group["canonical_name"]

                # Récupérer UUIDs à merger (tous sauf master)
                duplicate_uuids = [
                    e["uuid"] for e in group["entities"]
                    if e["uuid"] != master_uuid
                ]

                if len(duplicate_uuids) == 0:
                    # Entité unique : juste valider le master sans merge
                    self._validate_single_entity(
                        entity_uuid=master_uuid,
                        canonical_name=canonical_name,
                        tenant_id=tenant_id
                    )
                    continue

                # Merge ce groupe
                result = self.merge_entities(
                    master_uuid=master_uuid,
                    duplicate_uuids=duplicate_uuids,
                    canonical_name=canonical_name,
                    tenant_id=tenant_id
                )

                total_merged += result["duplicates_merged"]
                total_relations["out"] += result["relations_transferred"]["out"]
                total_relations["in"] += result["relations_transferred"]["in"]

            except Exception as e:
                logger.error(f"❌ Erreur merge groupe {group.get('canonical_key')}: {e}")
                errors.append({
                    "canonical_key": group.get("canonical_key"),
                    "error": str(e)
                })

        logger.info(
            f"✅ Batch merge terminé: {total_merged} entités mergées, "
            f"{len(errors)} erreurs"
        )

        return {
            "groups_processed": len(merge_groups),
            "entities_merged": total_merged,
            "relations_transferred": total_relations,
            "errors": errors,
            "completed_at": datetime.utcnow().isoformat()
        }

    def _deduplicate_canonical_names(self, merge_groups: List[Dict]) -> List[Dict]:
        """
        Fusionne les groupes ayant le même canonical_name.

        Si 2+ groupes ont le même canonical_name, on les fusionne en 1 seul groupe
        avec toutes leurs entités combinées.
        """
        canonical_to_group = {}

        for group in merge_groups:
            canonical = group["canonical_name"]

            if canonical in canonical_to_group:
                # Fusionner avec le groupe existant
                existing = canonical_to_group[canonical]
                existing["entities"].extend(group["entities"])

                # Choisir le meilleur master (celui avec le score le plus élevé)
                all_entities = existing["entities"]
                best_master = max(all_entities, key=lambda e: e.get("score", 0))
                existing["master_uuid"] = best_master["uuid"]

            else:
                # Premier groupe avec ce canonical_name
                canonical_to_group[canonical] = group

        return list(canonical_to_group.values())

    def _validate_single_entity(
        self,
        entity_uuid: str,
        canonical_name: str,
        tenant_id: str
    ):
        """
        Valide une entité unique (sans merge).

        Pour les entités sans variantes, on les passe juste en status=validated
        avec leur nom comme canonical_name.
        """
        from neo4j import GraphDatabase
        import os

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            query = """
            MATCH (e:Entity {uuid: $uuid, tenant_id: $tenant_id})
            SET e.canonical_name = $canonical_name,
                e.status = 'validated',
                e.normalized_at = datetime()
            RETURN e
            """

            session.run(
                query,
                uuid=entity_uuid,
                canonical_name=canonical_name,
                tenant_id=tenant_id
            )

        driver.close()

        logger.info(f"✅ Entité unique validée: {entity_uuid} → {canonical_name}")


__all__ = ["EntityMergeService"]
