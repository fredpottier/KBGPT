"""
Service d'injection directe dans Neo4j (bypass Graphiti LLM extraction)

Contexte:
- Pipeline extrait déjà entities/relations via UN SEUL appel LLM Vision par slide
- Graphiti API /messages RE-FAIT extraction LLM (doublon coût + temps)
- Solution: Injecter directement dans Neo4j au format Graphiti

Architecture:
┌─────────────────────────────────────────────────────────┐
│  Pipeline SAP KB                                        │
│  ✅ 1 LLM call/slide → 904 entities + 617 relations    │
│                                                          │
│  ↓ (bypass Graphiti API)                                │
│                                                          │
│  Neo4j Direct Ingest                                    │
│  • CREATE (:Entity) nodes                               │
│  • CREATE (:EpisodicNode) pour episode                  │
│  • CREATE [:RELATES_TO] relations                       │
│  • CREATE [:MENTIONS] episode ↔ entities                │
│                                                          │
│  ✅ 0 LLM additionnel !                                 │
└─────────────────────────────────────────────────────────┘

Référence:
- doc/architecture/UNIFIED_LLM_EXTRACTION_STRATEGY.md
- Issue: Double LLM extraction (904 entities → 16 entities après Graphiti)
"""

from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from neo4j import GraphDatabase, Session
import uuid

logger = logging.getLogger(__name__)


class Neo4jDirectIngest:
    """
    Service d'injection directe dans Neo4j au format Graphiti

    Bypass l'API Graphiti /messages pour éviter re-extraction LLM.
    Injecte directement entities/relations extraites par notre pipeline.
    """

    def __init__(
        self,
        uri: str = "bolt://graphiti-neo4j:7687",
        user: str = "neo4j",
        password: str = "graphiti_neo4j_pass"
    ):
        """
        Initialise connexion Neo4j directe

        Args:
            uri: URI Neo4j (défaut: service Docker)
            user: Username Neo4j
            password: Password Neo4j
        """
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"✅ [Neo4jDirectIngest] Connexion établie: {uri}")

    def close(self):
        """Ferme la connexion Neo4j"""
        if self.driver:
            self.driver.close()
            logger.info("🔌 [Neo4jDirectIngest] Connexion fermée")

    def create_episode_with_entities(
        self,
        episode_id: str,
        episode_name: str,
        group_id: str,
        entities: List[Dict[str, Any]],
        relations: List[Dict[str, Any]],
        episode_content: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Crée un episode + toutes ses entities/relations directement dans Neo4j

        Architecture Neo4j Graphiti:

        (:EpisodicNode {uuid, name, content, group_id, created_at})
            |
            | [:MENTIONS]
            ↓
        (:Entity {uuid, name, entity_type, summary, group_id, created_at})
            |
            | [:RELATES_TO {relation_type}]
            ↓
        (:Entity)

        Args:
            episode_id: ID custom de l'episode (ex: "default_doc_20251002")
            episode_name: Nom lisible (ex: "PPTX: doc.pptx")
            group_id: Tenant ID (isolation multi-tenant)
            entities: Liste entities extraites [{name, entity_type, summary}]
            relations: Liste relations extraites [{source, target, relation_type}]
            episode_content: Contenu textuel episode (metadata document)
            metadata: Metadata additionnelles (source_date, solution, etc.)

        Returns:
            Dict avec stats {episode_uuid, entities_created, relations_created}
        """

        stats = {
            "episode_uuid": None,
            "entities_created": 0,
            "relations_created": 0,
            "mentions_created": 0,
            "errors": []
        }

        # Générer UUID episode
        episode_uuid = str(uuid.uuid4())
        stats["episode_uuid"] = episode_uuid

        with self.driver.session() as session:
            try:
                # 1. Créer EpisodicNode (episode)
                logger.info(f"📝 [Neo4j] Création episode: {episode_name}")
                session.execute_write(
                    self._create_episode_tx,
                    episode_uuid=episode_uuid,
                    episode_id=episode_id,
                    episode_name=episode_name,
                    group_id=group_id,
                    content=episode_content,
                    metadata=metadata or {}
                )

                # 2. Créer toutes les entities (batch)
                logger.info(f"🌐 [Neo4j] Création {len(entities)} entities...")
                entity_uuids = session.execute_write(
                    self._create_entities_batch_tx,
                    entities=entities,
                    group_id=group_id,
                    episode_uuid=episode_uuid
                )
                stats["entities_created"] = len(entity_uuids)

                # 3. Créer relations MENTIONS (episode → entities)
                logger.info(f"🔗 [Neo4j] Création liens MENTIONS episode → entities...")
                mentions_count = session.execute_write(
                    self._create_mentions_tx,
                    episode_uuid=episode_uuid,
                    entity_uuids=list(entity_uuids.values())
                )
                stats["mentions_created"] = mentions_count

                # 4. Créer relations sémantiques (entity → entity)
                logger.info(f"↔️ [Neo4j] Création {len(relations)} relations sémantiques...")
                relations_created = session.execute_write(
                    self._create_relations_batch_tx,
                    relations=relations,
                    entity_uuids=entity_uuids,
                    group_id=group_id
                )
                stats["relations_created"] = relations_created

                logger.info(
                    f"✅ [Neo4j] Episode créé: {episode_name}\n"
                    f"   📊 Stats: {stats['entities_created']} entities, "
                    f"{stats['relations_created']} relations, "
                    f"{stats['mentions_created']} mentions"
                )

            except Exception as e:
                logger.error(f"❌ [Neo4j] Erreur création episode: {e}")
                stats["errors"].append(str(e))
                raise

        return stats

    @staticmethod
    def _create_episode_tx(
        tx: Session,
        episode_uuid: str,
        episode_id: str,
        episode_name: str,
        group_id: str,
        content: str,
        metadata: Dict[str, Any]
    ):
        """Transaction: Créer EpisodicNode"""
        query = """
        CREATE (e:EpisodicNode {
            uuid: $episode_uuid,
            episode_id: $episode_id,
            name: $episode_name,
            content: $content,
            group_id: $group_id,
            created_at: datetime(),
            source_date: $source_date,
            source_type: $source_type,
            solution: $solution
        })
        RETURN e.uuid as uuid
        """

        result = tx.run(
            query,
            episode_uuid=episode_uuid,
            episode_id=episode_id,
            episode_name=episode_name,
            content=content,
            group_id=group_id,
            source_date=metadata.get("source_date", ""),
            source_type=metadata.get("source_type", "pptx"),
            solution=metadata.get("main_solution", "")
        )

        return result.single()["uuid"]

    @staticmethod
    def _create_entities_batch_tx(
        tx: Session,
        entities: List[Dict[str, Any]],
        group_id: str,
        episode_uuid: str
    ) -> Dict[str, str]:
        """
        Transaction: Créer toutes les entities en batch

        Returns:
            Dict {entity_name: entity_uuid} pour mapping relations
        """
        entity_uuids = {}

        # Dédoublonnage entities par nom (même nom = même entity)
        # ET accumulation des summaries pour enrichissement
        unique_entities = {}
        for entity in entities:
            name = entity.get("name", "").strip()
            if name:
                if name not in unique_entities:
                    unique_entities[name] = entity
                else:
                    # Enrichir le summary existant avec le nouveau contexte
                    existing_summary = unique_entities[name].get("summary", "")
                    new_summary = entity.get("summary", entity.get("description", ""))
                    if new_summary and new_summary not in existing_summary:
                        unique_entities[name]["summary"] = f"{existing_summary} | {new_summary}"

        logger.debug(f"   🔹 Dédoublonnage: {len(entities)} → {len(unique_entities)} entities uniques")

        # Créer chaque entity unique (SANS group_id dans la contrainte pour globalité)
        query = """
        MERGE (e:Entity {name: $name})
        ON CREATE SET
            e.uuid = $uuid,
            e.entity_type = $entity_type,
            e.summary = $summary,
            e.group_id = $group_id,
            e.created_at = datetime(),
            e.created_by_episode = $episode_uuid
        ON MATCH SET
            e.summary = CASE
                WHEN $summary IS NOT NULL AND NOT $summary IN split(e.summary, ' | ')
                THEN e.summary + ' | ' + $summary
                ELSE e.summary
            END,
            e.updated_at = datetime(),
            e.last_seen_episode = $episode_uuid
        RETURN e.uuid as uuid, e.name as name
        """

        for name, entity in unique_entities.items():
            entity_uuid = str(uuid.uuid4())

            result = tx.run(
                query,
                uuid=entity_uuid,
                name=name,
                entity_type=entity.get("entity_type", "CONCEPT"),
                summary=entity.get("summary", entity.get("description", "")),
                group_id=group_id,
                episode_uuid=episode_uuid
            )

            record = result.single()
            entity_uuids[record["name"]] = record["uuid"]

        return entity_uuids

    @staticmethod
    def _create_mentions_tx(
        tx: Session,
        episode_uuid: str,
        entity_uuids: List[str]
    ) -> int:
        """
        Transaction: Créer relations MENTIONS (episode → entities)

        Returns:
            Nombre de relations MENTIONS créées
        """
        if not entity_uuids:
            return 0

        query = """
        MATCH (episode:EpisodicNode {uuid: $episode_uuid})
        MATCH (entity:Entity)
        WHERE entity.uuid IN $entity_uuids
        MERGE (episode)-[m:MENTIONS]->(entity)
        ON CREATE SET m.created_at = datetime()
        RETURN count(m) as mentions_count
        """

        result = tx.run(
            query,
            episode_uuid=episode_uuid,
            entity_uuids=entity_uuids
        )

        return result.single()["mentions_count"]

    @staticmethod
    def _create_relations_batch_tx(
        tx: Session,
        relations: List[Dict[str, Any]],
        entity_uuids: Dict[str, str],
        group_id: str
    ) -> int:
        """
        Transaction: Créer relations sémantiques (entity → entity)

        Args:
            relations: Liste [{source, target, relation_type}]
            entity_uuids: Mapping {entity_name: uuid}
            group_id: Tenant ID

        Returns:
            Nombre de relations créées
        """
        relations_created = 0

        query = """
        MATCH (source:Entity {name: $source_name, group_id: $group_id})
        MATCH (target:Entity {name: $target_name, group_id: $group_id})
        MERGE (source)-[r:RELATES_TO {relation_type: $relation_type}]->(target)
        ON CREATE SET r.created_at = datetime()
        RETURN r
        """

        for relation in relations:
            source_name = relation.get("source", "").strip()
            target_name = relation.get("target", "").strip()
            relation_type = relation.get("relation_type", "RELATED_TO")

            # Skip si source ou target manquants
            if not source_name or not target_name:
                continue

            # Skip si entities n'existent pas (peuvent avoir été filtrées)
            if source_name not in entity_uuids or target_name not in entity_uuids:
                logger.debug(f"   ⚠️ Relation ignorée (entity manquante): {source_name} → {target_name}")
                continue

            try:
                result = tx.run(
                    query,
                    source_name=source_name,
                    target_name=target_name,
                    relation_type=relation_type,
                    group_id=group_id
                )

                if result.single():
                    relations_created += 1

            except Exception as e:
                logger.warning(f"   ⚠️ Erreur création relation {source_name} → {target_name}: {e}")
                continue

        return relations_created

    def get_episode_stats(self, episode_uuid: str) -> Dict[str, Any]:
        """
        Récupère statistiques d'un episode

        Returns:
            Dict {entities_count, relations_count, mentions_count}
        """
        with self.driver.session() as session:
            query = """
            MATCH (episode:EpisodicNode {uuid: $episode_uuid})
            OPTIONAL MATCH (episode)-[m:MENTIONS]->(e:Entity)
            OPTIONAL MATCH (e)-[r:RELATES_TO]->()
            RETURN
                episode.name as episode_name,
                count(DISTINCT e) as entities_count,
                count(DISTINCT m) as mentions_count,
                count(DISTINCT r) as relations_count
            """

            result = session.run(query, episode_uuid=episode_uuid)
            record = result.single()

            if not record:
                return {"error": "Episode not found"}

            return {
                "episode_name": record["episode_name"],
                "entities_count": record["entities_count"],
                "mentions_count": record["mentions_count"],
                "relations_count": record["relations_count"]
            }


def get_neo4j_direct_ingest() -> Neo4jDirectIngest:
    """Factory pour obtenir instance Neo4jDirectIngest"""
    import os

    uri = os.getenv("GRAPHITI_NEO4J_URI", "bolt://graphiti-neo4j:7687")
    user = os.getenv("GRAPHITI_NEO4J_USER", "neo4j")
    password = os.getenv("GRAPHITI_NEO4J_PASSWORD", "graphiti_neo4j_pass")

    return Neo4jDirectIngest(uri=uri, user=user, password=password)


__all__ = ["Neo4jDirectIngest", "get_neo4j_direct_ingest"]
