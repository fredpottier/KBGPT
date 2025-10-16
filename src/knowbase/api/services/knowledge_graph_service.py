"""
Service Knowledge Graph pour gestion entities, relations, episodes dans Neo4j.

Phase 3 - Knowledge Graph Neo4j Native
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Dict
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
from knowbase.ontology.entity_normalizer_neo4j import get_entity_normalizer_neo4j
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "knowledge_graph_service.log")


# Vocabulaire contrôlé des types de relations Neo4j
# Types sémantiquement significatifs pour SAP knowledge graph
RELATION_TYPE_VOCABULARY = {
    # Relations structurelles
    "PART_OF": ["part_of", "component_of", "module_of", "belongs_to", "contained_in"],
    "CONTAINS": ["contains", "includes", "has", "comprises"],
    "HAS_MEMBER": ["has_member", "member_of", "includes_member"],

    # Relations fonctionnelles
    "USES": ["uses", "utilizes", "employs", "leverages", "relies_on"],
    "USED_BY": ["used_by", "employed_by"],
    "REQUIRES": ["requires", "needs", "depends_on", "prerequisite"],
    "PROVIDES": ["provides", "offers", "supplies", "delivers"],

    # Relations d'implémentation
    "IMPLEMENTS": ["implements", "realizes", "executes"],
    "SUPPORTS": ["supports", "enables", "facilitates"],
    "EXTENDS": ["extends", "enhances", "augments"],

    # Relations de référence
    "MENTIONS": ["mentions", "references", "refers_to", "cites"],
    "RELATED_TO": ["related_to", "associated_with", "connected_to", "linked_to"],

    # Relations temporelles
    "PRECEDES": ["precedes", "before", "prior_to"],
    "FOLLOWS": ["follows", "after", "succeeds"],

    # Relations de version
    "REPLACES": ["replaces", "supersedes", "obsoletes"],
    "REPLACED_BY": ["replaced_by", "superseded_by"],

    # Relations techniques
    "INTEGRATES_WITH": ["integrates_with", "connects_to", "interfaces_with"],
    "DEPENDS_ON": ["depends_on", "requires"],
    "COMPATIBLE_WITH": ["compatible_with", "works_with"],
}


def normalize_relation_type(relation_type: str) -> str:
    """
    Normalise un type de relation vers le vocabulaire contrôlé.

    Args:
        relation_type: Type de relation brut du LLM

    Returns:
        Type de relation normalisé (ex: "USES", "PART_OF", etc.)
        Fallback vers "RELATED_TO" si non reconnu
    """
    if not relation_type:
        return "RELATED_TO"

    # Nettoyer et normaliser le type
    cleaned = relation_type.strip().upper().replace(" ", "_")

    # Si déjà dans le vocabulaire principal, retourner tel quel
    if cleaned in RELATION_TYPE_VOCABULARY:
        return cleaned

    # Chercher dans les synonymes
    for canonical_type, synonyms in RELATION_TYPE_VOCABULARY.items():
        if cleaned.lower() in [s.lower() for s in synonyms]:
            logger.debug(f"🔄 Relation type normalisé: '{relation_type}' → '{canonical_type}'")
            return canonical_type

    # Fallback: utiliser RELATED_TO pour types non reconnus
    logger.info(f"⚠️  Type de relation non reconnu: '{relation_type}' - utilisation de RELATED_TO")
    return "RELATED_TO"


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
        self.normalizer = get_entity_normalizer_neo4j(self.driver)

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
            status: $status,
            is_cataloged: $is_cataloged,
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
            source_slide_number=node["source_slide_number"],
            source_document=node["source_document"],
            source_chunk_id=node["source_chunk_id"],
            tenant_id=node["tenant_id"],
            status=node.get("status", "pending"),
            is_cataloged=node.get("is_cataloged", False),
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
        entity_id, canonical_name, entity_type_corrected, is_cataloged = self.normalizer.normalize_entity_name(
            entity.name,
            entity_type_hint=entity.entity_type,
            tenant_id=entity.tenant_id
        )

        # Si type corrigé par ontologie, utiliser le type corrigé
        if entity_type_corrected and entity_type_corrected != entity.entity_type:
            logger.info(
                f"🔄 Type corrigé par ontologie: {entity.entity_type} → {entity_type_corrected}"
            )
            entity.entity_type = entity_type_corrected

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
                tenant_id=entity.tenant_id
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
                confidence=node.get("confidence", 0.0),  # Backward compat
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
        """
        Transaction création relation avec type dynamique.

        Normalise le type de relation vers le vocabulaire contrôlé,
        puis crée la relation avec le type comme label Neo4j (ex: [:USES], [:PART_OF]).
        """
        relation_uuid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Normaliser le type de relation vers vocabulaire contrôlé
        normalized_type = normalize_relation_type(relation.relation_type)

        # IMPORTANT: Construction dynamique de la requête Cypher avec type de relation
        # Neo4j ne permet pas de paramétrer les types de relations, donc on injecte
        # le type après validation/normalisation (sécurisé car vocabulaire contrôlé)
        query = f"""
        MATCH (source:Entity {{name: $source_name, tenant_id: $tenant_id}})
        MATCH (target:Entity {{name: $target_name, tenant_id: $tenant_id}})
        CREATE (source)-[r:{normalized_type} {{
            uuid: $uuid,
            description: $description,
            confidence: $confidence,
            source_slide_number: $source_slide_number,
            source_document: $source_document,
            source_chunk_id: $source_chunk_id,
            tenant_id: $tenant_id,
            created_at: datetime($created_at)
        }}]->(target)
        RETURN r, source.uuid AS source_uuid, target.uuid AS target_uuid, type(r) AS relation_type
        """

        result = tx.run(
            query,
            uuid=relation_uuid,
            source_name=relation.source,
            target_name=relation.target,
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
            relation_type=record["relation_type"],  # Type Neo4j réel
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

    def get_episode_by_uuid(self, episode_uuid: str) -> Optional[EpisodeResponse]:
        """
        Récupère un épisode par son UUID.

        Args:
            episode_uuid: UUID de l'épisode

        Returns:
            EpisodeResponse ou None si non trouvé
        """
        with self.driver.session() as session:
            result = session.execute_read(self._get_episode_by_uuid_tx, episode_uuid, self.tenant_id)
            return result

    @staticmethod
    def _get_episode_by_uuid_tx(tx, episode_uuid: str, tenant_id: str) -> Optional[EpisodeResponse]:
        """Transaction récupération épisode par UUID."""
        query = """
        MATCH (ep:Episode {uuid: $uuid, tenant_id: $tenant_id})
        RETURN ep
        LIMIT 1
        """

        result = tx.run(query, uuid=episode_uuid, tenant_id=tenant_id)
        record = result.single()

        if not record:
            return None

        node = record["ep"]

        import json
        metadata = json.loads(node["metadata"]) if node.get("metadata") else {}

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
            metadata=metadata,
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


    def count_entities_by_type(
        self,
        entity_type: str,
        tenant_id: str = "default"
    ) -> Dict[str, int]:
        """
        Compte les entités d'un type donné par statut.

        Args:
            entity_type: Type d'entité (SOLUTION, ORGANIZATION, etc.)
            tenant_id: Tenant ID

        Returns:
            Dict avec compteurs:
            {
                "total": int,  # Total entités du type
                "pending": int,  # Entités status=pending
                "validated": int  # Entités status=validated
            }
        """
        query = """
        MATCH (e:Entity {entity_type: $entity_type, tenant_id: $tenant_id})
        RETURN
            count(e) AS total,
            sum(CASE WHEN e.status = 'pending' THEN 1 ELSE 0 END) AS pending,
            sum(CASE WHEN e.status = 'validated' THEN 1 ELSE 0 END) AS validated
        """

        with self.driver.session() as session:
            result = session.run(
                query,
                entity_type=entity_type,
                tenant_id=tenant_id
            )

            record = result.single()

            if not record:
                return {"total": 0, "pending": 0, "validated": 0}

            return {
                "total": record["total"] or 0,
                "pending": record["pending"] or 0,
                "validated": record["validated"] or 0
            }

    def get_entities_by_type(
        self,
        entity_type: str,
        tenant_id: str = "default",
        status: Optional[str] = None,
        limit: int = 1000
    ) -> List[Dict]:
        """
        Récupère toutes les entités d'un type donné.

        Args:
            entity_type: Type d'entité (SOLUTION, ORGANIZATION, etc.)
            tenant_id: Tenant ID
            status: Filtrer par status (optionnel: 'pending', 'validated')
            limit: Limite résultats (défaut: 1000)

        Returns:
            Liste de dictionnaires avec données entités:
            [
                {
                    "uuid": str,
                    "name": str,
                    "entity_type": str,
                    "description": str,
                    "confidence": float,
                    "attributes": dict,
                    "status": str,
                    "source_document": str,
                    "created_at": str
                },
                ...
            ]
        """
        # Build query avec filtre status optionnel
        query = """
        MATCH (e:Entity {entity_type: $entity_type, tenant_id: $tenant_id})
        """

        params = {
            "entity_type": entity_type,
            "tenant_id": tenant_id,
            "limit": limit
        }

        if status:
            query += " WHERE e.status = $status"
            params["status"] = status

        query += """
        RETURN e
        ORDER BY e.created_at DESC
        LIMIT $limit
        """

        entities = []
        with self.driver.session() as session:
            result = session.run(query, params)

            for record in result:
                node = record["e"]

                # Parser attributes JSON string vers dict
                import json
                attributes = node.get("attributes", {})
                if isinstance(attributes, str):
                    try:
                        attributes = json.loads(attributes) if attributes else {}
                    except:
                        attributes = {}

                entities.append({
                    "uuid": node["uuid"],
                    "name": node["name"],
                    "entity_type": node["entity_type"],
                    "description": node.get("description", ""),
                    "confidence": float(node.get("confidence", 0.0)),
                    "attributes": attributes,
                    "status": node.get("status", "pending"),
                    "source_document": node.get("source_document", ""),
                    "source_slide_number": node.get("source_slide_number"),
                    "source_chunk_id": node.get("source_chunk_id"),
                    "created_at": str(node.get("created_at", "")),
                    "updated_at": str(node.get("updated_at", ""))
                })

        return entities

    def deduplicate_entities_by_name(
        self,
        tenant_id: str = "default",
        dry_run: bool = False
    ) -> Dict:
        """
        Dé-duplique les entités ayant exactement le même nom (case-insensitive).

        Pour chaque groupe d'entités avec le même nom:
        - Garde l'entité "maître" (celle avec le plus de relations)
        - Réassigne toutes les relations vers l'entité maître
        - Supprime les entités dupliquées

        Args:
            tenant_id: Tenant ID
            dry_run: Si True, ne fait que simuler (retourne ce qui serait fait)

        Returns:
            Dict avec statistiques:
            {
                "duplicate_groups": int,  # Nombre de groupes de doublons
                "entities_to_merge": int,  # Nombre d'entités à fusionner
                "entities_kept": int,      # Nombre d'entités conservées
                "relations_updated": int,  # Nombre de relations réassignées
                "groups": [...]           # Détails des groupes (si dry_run)
            }
        """
        stats = {
            "duplicate_groups": 0,
            "entities_to_merge": 0,
            "entities_kept": 0,
            "relations_updated": 0,
            "groups": []
        }

        logger.info(f"🔍 Démarrage dé-duplication des entités (tenant: {tenant_id}, dry_run: {dry_run})")

        with self.driver.session() as session:
            # 1. Trouver tous les groupes d'entités avec le même nom
            # OPTIMISÉ: Pas de comptage de relations (trop lent), on prend la plus ancienne comme master
            find_duplicates_query = """
            MATCH (e:Entity {tenant_id: $tenant_id})
            WITH toLower(trim(e.name)) as normalized_name,
                 collect({
                     uuid: e.uuid,
                     name: e.name,
                     entity_type: e.entity_type,
                     created_at: e.created_at,
                     status: coalesce(e.status, 'pending')
                 }) as entities
            WHERE size(entities) > 1
            RETURN normalized_name,
                   entities,
                   size(entities) as entity_count
            ORDER BY entity_count DESC
            """

            result = session.run(find_duplicates_query, tenant_id=tenant_id)
            duplicate_groups = []

            for record in result:
                normalized_name = record["normalized_name"]
                entities = list(record["entities"])
                entity_count = record["entity_count"]

                # Convertir les DateTime en strings pour sérialisation JSON
                from neo4j.time import DateTime

                def convert_datetime(dt):
                    """Convertit neo4j.time.DateTime en string ISO 8601."""
                    if dt is None:
                        return None
                    if isinstance(dt, DateTime):
                        try:
                            return dt.to_native().isoformat()
                        except Exception:
                            return str(dt)
                    return str(dt)

                # Trier par date de création (la plus ancienne en premier = la plus fiable)
                entities.sort(key=lambda x: x.get("created_at") or "9999")

                # L'entité maître est la plus ancienne
                master_entity = entities[0]
                duplicate_entities = entities[1:]

                duplicate_groups.append({
                    "normalized_name": normalized_name,
                    "name": master_entity["name"],  # Nom original de l'entité master
                    "type": master_entity["entity_type"],
                    "entity_count": entity_count,
                    "master_entity": {
                        "uuid": master_entity["uuid"],
                        "name": master_entity["name"],
                        "entity_type": master_entity["entity_type"],
                        "created_at": convert_datetime(master_entity.get("created_at")),
                        "status": master_entity["status"]
                    },
                    "duplicates": [
                        {
                            "uuid": d["uuid"],
                            "name": d["name"],
                            "entity_type": d["entity_type"],
                            "created_at": convert_datetime(d.get("created_at")),
                            "status": d["status"]
                        }
                        for d in duplicate_entities
                    ]
                })

                stats["duplicate_groups"] += 1
                stats["entities_to_merge"] += len(duplicate_entities)
                stats["entities_kept"] += 1

            logger.info(f"📊 Trouvé {stats['duplicate_groups']} groupes de doublons, {stats['entities_to_merge']} entités à fusionner")

            # 2. Si dry_run, retourner seulement les statistiques (limiter à 20 groupes)
            if dry_run:
                stats["groups"] = duplicate_groups[:20]  # Limiter pour éviter de surcharger la réponse
                return stats

            # 3. Pour chaque groupe, fusionner les doublons vers le maître
            # OPTIMISÉ: Traiter par lots pour éviter Out of Memory sur gros groupes
            for group in duplicate_groups:
                master_uuid = group["master_entity"]["uuid"]
                duplicate_uuids = [d["uuid"] for d in group["duplicates"]]

                total_deleted_relations = 0
                total_deleted_entities = 0

                # Traiter par lots de 10 entités à la fois pour éviter OOM
                BATCH_SIZE = 10
                for i in range(0, len(duplicate_uuids), BATCH_SIZE):
                    batch_uuids = duplicate_uuids[i:i + BATCH_SIZE]

                    # Étape 1: Transférer les relations (seulement celles qui ne créent pas de doublon)
                    for dup_uuid in batch_uuids:
                        # Relations sortantes: (duplicate)-[r]->(target)
                        update_outgoing_query = """
                        MATCH (dup:Entity {uuid: $dup_uuid})-[r]->(target)
                        MATCH (master:Entity {uuid: $master_uuid})
                        WHERE NOT (master)-[]->(target)
                        CREATE (master)-[r2:MERGED_RELATION]->(target)
                        SET r2 = properties(r)
                        SET r2.merged_from = $dup_uuid
                        DELETE r
                        RETURN count(r) as updated_count
                        """

                        result = session.run(
                            update_outgoing_query,
                            dup_uuid=dup_uuid,
                            master_uuid=master_uuid
                        )
                        record = result.single()
                        if record:
                            stats["relations_updated"] += record["updated_count"] or 0

                        # Relations entrantes: (source)-[r]->(duplicate)
                        update_incoming_query = """
                        MATCH (source)-[r]->(dup:Entity {uuid: $dup_uuid})
                        MATCH (master:Entity {uuid: $master_uuid})
                        WHERE NOT (source)-[]->(master)
                        CREATE (source)-[r2:MERGED_RELATION]->(master)
                        SET r2 = properties(r)
                        SET r2.merged_from = $dup_uuid
                        DELETE r
                        RETURN count(r) as updated_count
                        """

                        result = session.run(
                            update_incoming_query,
                            dup_uuid=dup_uuid,
                            master_uuid=master_uuid
                        )
                        record = result.single()
                        if record:
                            stats["relations_updated"] += record["updated_count"] or 0

                    # Étape 2: Supprimer toutes les relations restantes du batch
                    # (celles qui n'ont pas pu être transférées car elles créeraient des doublons)
                    delete_remaining_relations_query = """
                    MATCH (e:Entity)-[r]-()
                    WHERE e.uuid IN $batch_uuids
                    DELETE r
                    RETURN count(r) as deleted_relations_count
                    """

                    result = session.run(delete_remaining_relations_query, batch_uuids=batch_uuids)
                    record = result.single()
                    deleted_relations = record["deleted_relations_count"] if record else 0
                    total_deleted_relations += deleted_relations

                    # Étape 3: Supprimer les entités du batch (qui n'ont maintenant plus de relations)
                    delete_query = """
                    MATCH (e:Entity)
                    WHERE e.uuid IN $batch_uuids
                    DELETE e
                    RETURN count(e) as deleted_count
                    """

                    result = session.run(delete_query, batch_uuids=batch_uuids)
                    record = result.single()
                    deleted_count = record["deleted_count"] if record else 0
                    total_deleted_entities += deleted_count

                logger.info(
                    f"✅ Groupe '{group['normalized_name']}': "
                    f"{len(duplicate_uuids)} doublons fusionnés vers {master_uuid}, "
                    f"{total_deleted_relations} relations supprimées, "
                    f"{total_deleted_entities} entités supprimées"
                )

        logger.info(
            f"🎉 Dé-duplication terminée: "
            f"{stats['duplicate_groups']} groupes traités, "
            f"{stats['entities_to_merge']} entités fusionnées, "
            f"{stats['relations_updated']} relations réassignées"
        )

        return stats


__all__ = [
    "KnowledgeGraphService",
]
