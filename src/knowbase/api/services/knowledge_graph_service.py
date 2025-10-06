"""
Service Knowledge Graph pour gestion entities, relations, episodes dans Neo4j.

Phase 3 - Knowledge Graph Neo4j Native
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
import uuid

from neo4j import GraphDatabase

from knowbase.api.schemas.knowledge_graph import (
    EntityCreate,
    EntityResponse,
    RelationCreate,
    RelationResponse,
    EpisodeCreate,
    EpisodeResponse,
)
from knowbase.common.logging import setup_logging
from knowbase.common.entity_normalizer import get_entity_normalizer
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "knowledge_graph_service.log")


class KnowledgeGraphService:
    """Service pour gestion Knowledge Graph Neo4j."""

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le service Knowledge Graph.

        Args:
            tenant_id: ID du tenant pour isolation multi-tenant
        """
        self.tenant_id = tenant_id
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )
        self.normalizer = get_entity_normalizer()

    def close(self):
        """Ferme la connexion Neo4j."""
        if self.driver:
            self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # === ENTITIES ===

    def create_entity(self, entity: EntityCreate) -> EntityResponse:
        """
        Crée une entité dans Neo4j.

        Args:
            entity: Données entité à créer

        Returns:
            EntityResponse: Entité créée avec UUID
        """
        with self.driver.session() as session:
            result = session.execute_write(self._create_entity_tx, entity)
            return result

    @staticmethod
    def _create_entity_tx(tx, entity: EntityCreate) -> EntityResponse:
        """Transaction création entité."""
        entity_uuid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Convertir attributes dict en JSON string pour Neo4j
        import json
        attributes_json = json.dumps(entity.attributes) if entity.attributes else "{}"

        query = """
        CREATE (e:Entity {
            uuid: $uuid,
            name: $name,
            entity_type: $entity_type,
            description: $description,
            confidence: $confidence,
            attributes: $attributes,
            source_slide_number: $source_slide_number,
            source_document: $source_document,
            source_chunk_id: $source_chunk_id,
            tenant_id: $tenant_id,
            created_at: datetime($created_at),
            updated_at: datetime($updated_at)
        })
        RETURN e
        """

        result = tx.run(
            query,
            uuid=entity_uuid,
            name=entity.name,
            entity_type=entity.entity_type,
            description=entity.description,
            confidence=entity.confidence,
            attributes=attributes_json,
            source_slide_number=entity.source_slide_number,
            source_document=entity.source_document,
            source_chunk_id=entity.source_chunk_id,
            tenant_id=entity.tenant_id,
            created_at=now.isoformat(),
            updated_at=now.isoformat()
        )

        record = result.single()
        node = record["e"]

        # Reconvertir attributes JSON string → dict pour Pydantic
        import json
        attributes_dict = json.loads(node["attributes"]) if node["attributes"] else {}

        return EntityResponse(
            uuid=node["uuid"],
            name=node["name"],
            entity_type=node["entity_type"],
            description=node["description"],
            confidence=node["confidence"],
            attributes=attributes_dict,
            source_slide_number=node["source_slide_number"],
            source_document=node["source_document"],
            source_chunk_id=node["source_chunk_id"],
            tenant_id=node["tenant_id"],
            created_at=node["created_at"].to_native(),
            updated_at=node["updated_at"].to_native() if node["updated_at"] else None
        )

    def get_or_create_entity(self, entity: EntityCreate) -> EntityResponse:
        """
        Récupère une entité existante ou la crée si elle n'existe pas.

        Critère unicité: (canonical_name, entity_type, tenant_id)

        Normalise le nom de l'entité avant insertion pour éviter doublons.

        **Phase 2**: Enregistre automatiquement le entity_type dans le registry
        avec status=pending si découvert par LLM.

        Args:
            entity: Données entité

        Returns:
            EntityResponse: Entité (existante ou créée)
        """
        # Phase 2: Enregistrer le type dans le registry (auto-discovery)
        from knowbase.db import get_db
        from knowbase.api.services.entity_type_registry_service import EntityTypeRegistryService

        db_session = next(get_db())
        try:
            type_registry_service = EntityTypeRegistryService(db_session)
            type_registry_service.get_or_create_type(
                type_name=entity.entity_type,
                tenant_id=entity.tenant_id,
                discovered_by="llm"  # Type découvert par LLM lors de l'extraction
            )
        except Exception as e:
            logger.warning(f"⚠️  Erreur enregistrement type {entity.entity_type}: {e}")
        finally:
            db_session.close()

        # Normaliser le nom avant insertion
        entity_id, canonical_name, is_cataloged = self.normalizer.normalize_entity_name(
            entity.name,
            entity.entity_type
        )

        # Définir status et is_cataloged automatiquement
        if is_cataloged:
            entity.status = "validated"  # Entité trouvée dans ontologie → validée
            entity.is_cataloged = True
        else:
            entity.status = "pending"  # Entité non cataloguée → en attente validation
            entity.is_cataloged = False

        # Si catalogué, enrichir metadata
        if entity_id:
            metadata = self.normalizer.get_entity_metadata(
                entity_id,
                entity.entity_type
            )
            if metadata:
                entity.attributes["catalog_id"] = entity_id
                if "category" in metadata:
                    entity.attributes["category"] = metadata["category"]
                if "vendor" in metadata:
                    entity.attributes["vendor"] = metadata["vendor"]

            logger.debug(
                f"✅ Entité normalisée via catalogue: '{entity.name}' → '{canonical_name}' "
                f"(type={entity.entity_type}, id={entity_id}, status=validated)"
            )
        else:
            # Entité non cataloguée → log pour enrichissement futur
            self.normalizer.log_uncataloged_entity(
                entity.name,
                entity.entity_type,
                entity.tenant_id
            )
            logger.info(
                f"⚠️  Entité non cataloguée: '{entity.name}' (type={entity.entity_type}) "
                f"- status=pending, ajoutée à uncataloged_entities.log"
            )

        # Remplacer nom par forme canonique
        entity.name = canonical_name

        with self.driver.session() as session:
            result = session.execute_write(self._get_or_create_entity_tx, entity)
            return result

    @staticmethod
    def _get_or_create_entity_tx(tx, entity: EntityCreate) -> EntityResponse:
        """Transaction get_or_create entité."""
        # Chercher entité existante
        query_find = """
        MATCH (e:Entity {
            name: $name,
            entity_type: $entity_type,
            tenant_id: $tenant_id
        })
        RETURN e
        LIMIT 1
        """

        result = tx.run(
            query_find,
            name=entity.name,
            entity_type=entity.entity_type,
            tenant_id=entity.tenant_id
        )

        record = result.single()

        if record:
            # Entité existe déjà
            node = record["e"]

            # Reconvertir attributes JSON string → dict pour Pydantic
            import json
            attributes_dict = json.loads(node["attributes"]) if node.get("attributes") else {}

            return EntityResponse(
                uuid=node["uuid"],
                name=node["name"],
                entity_type=node["entity_type"],
                description=node["description"],
                confidence=node["confidence"],
                attributes=attributes_dict,
                source_slide_number=node.get("source_slide_number"),
                source_document=node.get("source_document"),
                source_chunk_id=node.get("source_chunk_id"),
                tenant_id=node["tenant_id"],
                status=node.get("status", "pending"),  # Backward compat
                is_cataloged=node.get("is_cataloged", False),  # Backward compat
                created_at=node["created_at"].to_native(),
                updated_at=node["updated_at"].to_native() if node.get("updated_at") else None
            )

        # Créer nouvelle entité
        entity_uuid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Convertir attributes dict en JSON string pour Neo4j
        import json
        attributes_json = json.dumps(entity.attributes) if entity.attributes else "{}"

        query_create = """
        CREATE (e:Entity {
            uuid: $uuid,
            name: $name,
            entity_type: $entity_type,
            description: $description,
            confidence: $confidence,
            attributes: $attributes,
            source_slide_number: $source_slide_number,
            source_document: $source_document,
            source_chunk_id: $source_chunk_id,
            tenant_id: $tenant_id,
            status: $status,
            is_cataloged: $is_cataloged,
            created_at: datetime($created_at),
            updated_at: datetime($updated_at)
        })
        RETURN e
        """

        result = tx.run(
            query_create,
            uuid=entity_uuid,
            name=entity.name,
            entity_type=entity.entity_type,
            description=entity.description,
            confidence=entity.confidence,
            attributes=attributes_json,
            source_slide_number=entity.source_slide_number,
            source_document=entity.source_document,
            source_chunk_id=entity.source_chunk_id,
            tenant_id=entity.tenant_id,
            status=entity.status,
            is_cataloged=entity.is_cataloged,
            created_at=now.isoformat(),
            updated_at=now.isoformat()
        )

        record = result.single()
        node = record["e"]

        # Reconvertir attributes JSON string → dict pour Pydantic
        import json
        attributes_dict = json.loads(node["attributes"]) if node["attributes"] else {}

        return EntityResponse(
            uuid=node["uuid"],
            name=node["name"],
            entity_type=node["entity_type"],
            description=node["description"],
            confidence=node["confidence"],
            attributes=attributes_dict,
            source_slide_number=node.get("source_slide_number"),
            source_document=node.get("source_document"),
            source_chunk_id=node.get("source_chunk_id"),
            tenant_id=node["tenant_id"],
            status=node["status"],
            is_cataloged=node["is_cataloged"],
            created_at=node["created_at"].to_native(),
            updated_at=node.get("updated_at").to_native() if node.get("updated_at") else None
        )

    # === RELATIONS ===

    def create_relation(self, relation: RelationCreate) -> RelationResponse:
        """
        Crée une relation entre deux entités.

        Args:
            relation: Données relation à créer

        Returns:
            RelationResponse: Relation créée

        Raises:
            ValueError: Si entité source ou cible n'existe pas
        """
        with self.driver.session() as session:
            result = session.execute_write(self._create_relation_tx, relation)
            return result

    @staticmethod
    def _create_relation_tx(tx, relation: RelationCreate) -> RelationResponse:
        """Transaction création relation."""
        relation_uuid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Vérifier que les entités existent et créer la relation
        query = """
        MATCH (source:Entity {name: $source_name, tenant_id: $tenant_id})
        MATCH (target:Entity {name: $target_name, tenant_id: $tenant_id})
        CREATE (source)-[r:RELATION {
            uuid: $uuid,
            relation_type: $relation_type,
            description: $description,
            confidence: $confidence,
            source_slide_number: $source_slide_number,
            source_document: $source_document,
            source_chunk_id: $source_chunk_id,
            tenant_id: $tenant_id,
            created_at: datetime($created_at)
        }]->(target)
        RETURN r, source.uuid AS source_uuid, target.uuid AS target_uuid
        """

        result = tx.run(
            query,
            uuid=relation_uuid,
            source_name=relation.source,
            target_name=relation.target,
            relation_type=relation.relation_type,
            description=relation.description,
            confidence=relation.confidence,
            source_slide_number=relation.source_slide_number,
            source_document=relation.source_document,
            source_chunk_id=relation.source_chunk_id,
            tenant_id=relation.tenant_id,
            created_at=now.isoformat()
        )

        record = result.single()

        if not record:
            raise ValueError(
                f"Entities not found: source='{relation.source}', target='{relation.target}', "
                f"tenant_id='{relation.tenant_id}'"
            )

        rel = record["r"]

        return RelationResponse(
            uuid=rel["uuid"],
            source=relation.source,
            target=relation.target,
            relation_type=rel["relation_type"],
            description=rel["description"],
            confidence=rel["confidence"],
            source_slide_number=rel["source_slide_number"],
            source_document=rel["source_document"],
            source_chunk_id=rel["source_chunk_id"],
            tenant_id=rel["tenant_id"],
            source_uuid=record["source_uuid"],
            target_uuid=record["target_uuid"],
            created_at=rel["created_at"].to_native()
        )

    # === EPISODES ===

    def create_episode(self, episode: EpisodeCreate) -> EpisodeResponse:
        """
        Crée un épisode (unité de connaissance liée à un document/slide).

        Args:
            episode: Données épisode à créer

        Returns:
            EpisodeResponse: Épisode créé
        """
        with self.driver.session() as session:
            result = session.execute_write(self._create_episode_tx, episode)
            return result

    @staticmethod
    def _create_episode_tx(tx, episode: EpisodeCreate) -> EpisodeResponse:
        """Transaction création épisode."""
        episode_uuid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        query = """
        CREATE (ep:Episode {
            uuid: $uuid,
            name: $name,
            source_document: $source_document,
            source_type: $source_type,
            content_summary: $content_summary,
            chunk_ids: $chunk_ids,
            entity_uuids: $entity_uuids,
            relation_uuids: $relation_uuids,
            fact_uuids: $fact_uuids,
            slide_number: $slide_number,
            tenant_id: $tenant_id,
            metadata: $metadata,
            created_at: datetime($created_at)
        })
        RETURN ep
        """

        # Convertir metadata dict en JSON string pour Neo4j
        import json
        metadata_json = json.dumps(episode.metadata) if episode.metadata else "{}"

        result = tx.run(
            query,
            uuid=episode_uuid,
            name=episode.name,
            source_document=episode.source_document,
            source_type=episode.source_type,
            content_summary=episode.content_summary,
            chunk_ids=episode.chunk_ids,
            entity_uuids=episode.entity_uuids,
            relation_uuids=episode.relation_uuids,
            fact_uuids=episode.fact_uuids,
            slide_number=episode.slide_number,
            tenant_id=episode.tenant_id,
            metadata=metadata_json,
            created_at=now.isoformat()
        )

        record = result.single()
        node = record["ep"]

        # Reconvertir metadata JSON string → dict pour Pydantic
        import json
        metadata_dict = json.loads(node["metadata"]) if node["metadata"] else {}

        return EpisodeResponse(
            uuid=node["uuid"],
            name=node["name"],
            source_document=node["source_document"],
            source_type=node["source_type"],
            content_summary=node["content_summary"],
            chunk_ids=node["chunk_ids"],
            entity_uuids=node["entity_uuids"],
            relation_uuids=node["relation_uuids"],
            fact_uuids=node["fact_uuids"],
            slide_number=node["slide_number"],
            tenant_id=node["tenant_id"],
            metadata=metadata_dict,
            created_at=node["created_at"].to_native()
        )

    def get_episode_by_name(self, episode_name: str) -> Optional[EpisodeResponse]:
        """
        Récupère un épisode par son nom.

        Args:
            episode_name: Nom de l'épisode

        Returns:
            EpisodeResponse ou None si non trouvé
        """
        with self.driver.session() as session:
            result = session.execute_read(self._get_episode_by_name_tx, episode_name, self.tenant_id)
            return result

    @staticmethod
    def _get_episode_by_name_tx(tx, episode_name: str, tenant_id: str) -> Optional[EpisodeResponse]:
        """Transaction récupération épisode par nom."""
        query = """
        MATCH (ep:Episode {name: $name, tenant_id: $tenant_id})
        RETURN ep
        LIMIT 1
        """

        result = tx.run(query, name=episode_name, tenant_id=tenant_id)
        record = result.single()

        if not record:
            return None

        node = record["ep"]

        return EpisodeResponse(
            uuid=node["uuid"],
            name=node["name"],
            source_document=node["source_document"],
            source_type=node["source_type"],
            content_summary=node["content_summary"],
            chunk_ids=node["chunk_ids"],
            entity_uuids=node["entity_uuids"],
            relation_uuids=node["relation_uuids"],
            fact_uuids=node["fact_uuids"],
            slide_number=node["slide_number"],
            tenant_id=node["tenant_id"],
            metadata=node["metadata"],
            created_at=node["created_at"].to_native()
        )


__all__ = [
    "KnowledgeGraphService",
]
