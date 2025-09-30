"""
Service Knowledge Graph Enterprise
Gestion du graphe de connaissances corporate avec Graphiti
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4
import json
from pathlib import Path

from knowbase.common.graphiti.graphiti_store import GraphitiStore
from knowbase.common.graphiti.config import GraphitiConfig
from knowbase.api.schemas.knowledge_graph import (
    EntityCreate, EntityResponse, RelationCreate, RelationResponse,
    SubgraphRequest, SubgraphResponse, GraphNode, GraphEdge,
    KnowledgeGraphStats, EntityType, RelationType
)

logger = logging.getLogger(__name__)

CORPORATE_GROUP_ID = "corporate"

# Cache temporaire pour les entités et relations (solution temporaire Phase 1)
_ENTITY_CACHE: Dict[str, Dict[str, Any]] = {}
_RELATION_CACHE: Dict[str, Dict[str, Any]] = {}


class KnowledgeGraphService:
    """Service de gestion du Knowledge Graph Enterprise"""

    def __init__(self):
        """Initialise le service avec le store Graphiti"""
        config = GraphitiConfig.from_env()
        self.store = GraphitiStore(config)
        self._initialized = False

    async def _ensure_initialized(self):
        """Garantit que le groupe corporate existe"""
        if not self._initialized:
            await self._initialize_corporate_group()
            self._initialized = True

    async def _initialize_corporate_group(self):
        """Initialise le groupe corporate avec schéma de base"""
        try:
            # Initialiser le store Graphiti
            await self.store.initialize()

            # Configurer le store pour le groupe corporate
            await self.store.set_group(CORPORATE_GROUP_ID)

            # Vérifier la santé du système
            health = await self.store.health()
            if not health:
                logger.warning("Store Graphiti n'est pas complètement opérationnel")

            logger.info(f"Groupe corporate '{CORPORATE_GROUP_ID}' initialisé")

        except Exception as e:
            logger.error(f"Erreur initialisation groupe corporate: {e}")
            raise

    async def create_entity(self, entity: EntityCreate) -> EntityResponse:
        """
        Crée une nouvelle entité dans le knowledge graph corporate

        Args:
            entity: Données de l'entité à créer

        Returns:
            Entité créée avec métadonnées
        """
        await self._ensure_initialized()

        try:
            # Créer l'entité via le store Graphiti
            entity_id_base = f"{entity.entity_type.value}_{entity.name}".replace(" ", "_").lower()
            entity_properties = {
                "name": entity.name,
                "type": entity.entity_type.value,
                "description": entity.description,
                **entity.attributes
            }

            entity_id = await self.store.create_entity(entity_id_base, entity_properties)

            # ✅ PHASE 2: Utiliser le groupe courant au lieu de forcer "corporate"
            current_group = getattr(self, '_current_group_id', CORPORATE_GROUP_ID)

            # Ajouter au cache temporaire pour résoudre le problème get_entity
            entity_data = {
                "uuid": entity_id,
                "name": entity.name,
                "entity_type": entity.entity_type.value,
                "description": entity.description,
                "attributes": entity.attributes,
                "created_at": datetime.utcnow().isoformat(),
                "group_id": current_group  # Changed from CORPORATE_GROUP_ID
            }
            _ENTITY_CACHE[entity_id] = entity_data

            logger.info(f"Entité créée: {entity.name} (ID: {entity_id}) - ajoutée au cache (groupe: {current_group})")

            return EntityResponse(
                uuid=entity_id,
                name=entity.name,
                entity_type=entity.entity_type,
                description=entity.description,
                attributes=entity.attributes,
                created_at=datetime.utcnow(),
                group_id=current_group  # ✅ Utilise le groupe courant (corporate OU user_xxx)
            )

        except Exception as e:
            logger.error(f"Erreur création entité {entity.name}: {e}")
            raise

    async def get_entity(self, entity_id: str) -> Optional[EntityResponse]:
        """
        Récupère une entité par son ID

        Args:
            entity_id: Identifiant de l'entité

        Returns:
            Entité trouvée ou None
        """
        await self._ensure_initialized()

        try:
            # Solution temporaire Phase 1: vérifier d'abord le cache
            if entity_id in _ENTITY_CACHE:
                entity_data = _ENTITY_CACHE[entity_id]

                # ✅ PHASE 2: Filtrer par group_id pour isolation multi-tenant
                current_group = getattr(self, '_current_group_id', CORPORATE_GROUP_ID)
                cache_group = entity_data.get("group_id", CORPORATE_GROUP_ID)

                if cache_group != current_group:
                    # Entité appartient à un autre groupe - ne pas la retourner
                    logger.debug(f"Entité {entity_id} ignorée du cache (groupe {cache_group} != {current_group})")
                    return None

                logger.info(f"Entité {entity_id} récupérée du cache temporaire (groupe: {current_group})")

                return EntityResponse(
                    uuid=entity_data["uuid"],
                    name=entity_data["name"],
                    entity_type=EntityType(entity_data["entity_type"]),
                    description=entity_data.get("description"),
                    attributes=entity_data.get("attributes", {}),
                    created_at=datetime.fromisoformat(entity_data["created_at"]),
                    group_id=entity_data["group_id"]
                )

            # Sinon, essayer via le store (pour les entités plus anciennes)
            entity_data = await self.store.get_entity(entity_id)

            if not entity_data:
                return None

            return EntityResponse(
                uuid=entity_data["uuid"],
                name=entity_data["name"],
                entity_type=EntityType(entity_data["entity_type"]),
                description=entity_data.get("description"),
                attributes=entity_data.get("attributes", {}),
                created_at=datetime.fromisoformat(entity_data["created_at"]) if entity_data.get("created_at") else datetime.utcnow(),
                group_id=entity_data["group_id"]
            )

        except Exception as e:
            logger.error(f"Erreur récupération entité {entity_id}: {e}")
            return None  # Retourner None plutôt que lever l'exception pour la Phase 1

    async def create_relation(self, relation: RelationCreate) -> RelationResponse:
        """
        Crée une nouvelle relation dans le knowledge graph

        Args:
            relation: Données de la relation à créer

        Returns:
            Relation créée avec métadonnées
        """
        await self._ensure_initialized()

        try:
            # Vérifier que les entités source et cible existent
            source_entity = await self.get_entity(relation.source_entity_id)
            target_entity = await self.get_entity(relation.target_entity_id)

            if not source_entity:
                raise ValueError(f"Entité source {relation.source_entity_id} introuvable")
            if not target_entity:
                raise ValueError(f"Entité cible {relation.target_entity_id} introuvable")

            # Créer la relation via un fait structuré
            fact_content = f"{source_entity.name} {relation.relation_type.value} {target_entity.name}"
            if relation.description:
                fact_content += f" ({relation.description})"

            # Créer le dictionnaire fact selon la signature attendue
            fact_data = {
                "subject": source_entity.name,
                "predicate": relation.relation_type.value,
                "object": target_entity.name,
                "confidence": relation.confidence,
                "source_entity_id": relation.source_entity_id,
                "target_entity_id": relation.target_entity_id,
                "description": relation.description,
                **relation.attributes
            }

            # ✅ PHASE 2: Utiliser le groupe courant au lieu de forcer "corporate"
            current_group = getattr(self, '_current_group_id', CORPORATE_GROUP_ID)

            relation_id = await self.store.create_fact(
                fact=fact_data,
                group_id=current_group
            )

            # Ajouter au cache temporaire
            relation_data = {
                "uuid": relation_id,
                "source_entity_id": relation.source_entity_id,
                "target_entity_id": relation.target_entity_id,
                "relation_type": relation.relation_type.value,
                "description": relation.description,
                "confidence": relation.confidence,
                "attributes": relation.attributes,
                "created_at": datetime.utcnow().isoformat(),
                "group_id": current_group
            }
            _RELATION_CACHE[relation_id] = relation_data

            logger.info(f"Relation créée: {source_entity.name} -> {target_entity.name} (ID: {relation_id}) - ajoutée au cache")

            return RelationResponse(
                uuid=relation_id,
                source_entity_id=relation.source_entity_id,
                target_entity_id=relation.target_entity_id,
                relation_type=relation.relation_type,
                description=relation.description,
                confidence=relation.confidence,
                attributes=relation.attributes,
                created_at=datetime.utcnow(),
                group_id=current_group  # ✅ Utilise le groupe courant (corporate OU user_xxx)
            )

        except Exception as e:
            logger.error(f"Erreur création relation: {e}")
            raise

    async def list_relations(self,
                           entity_id: Optional[str] = None,
                           relation_type: Optional[RelationType] = None,
                           limit: int = 100) -> List[RelationResponse]:
        """
        Liste les relations du knowledge graph

        Args:
            entity_id: Filtrer par entité (source ou cible)
            relation_type: Filtrer par type de relation
            limit: Nombre maximum de résultats

        Returns:
            Liste des relations
        """
        await self._ensure_initialized()

        try:
            # Solution temporaire Phase 1: utiliser d'abord le cache
            relations = []

            # ✅ PHASE 2: Obtenir le groupe courant pour filtrage
            current_group = getattr(self, '_current_group_id', CORPORATE_GROUP_ID)

            for relation_data in _RELATION_CACHE.values():
                # ✅ PHASE 2: Filtrer par group_id pour isolation multi-tenant
                relation_group = relation_data.get("group_id", CORPORATE_GROUP_ID)
                if relation_group != current_group:
                    continue  # Ignorer les relations d'autres groupes

                # Appliquer les filtres
                if relation_type and relation_data.get("relation_type") != relation_type.value:
                    continue

                if entity_id and (
                    relation_data.get("source_entity_id") != entity_id and
                    relation_data.get("target_entity_id") != entity_id
                ):
                    continue

                try:
                    relations.append(RelationResponse(
                        uuid=relation_data["uuid"],
                        source_entity_id=relation_data["source_entity_id"],
                        target_entity_id=relation_data["target_entity_id"],
                        relation_type=RelationType(relation_data["relation_type"]),
                        description=relation_data.get("description"),
                        confidence=relation_data.get("confidence", 1.0),
                        attributes=relation_data.get("attributes", {}),
                        created_at=datetime.fromisoformat(relation_data["created_at"]),
                        group_id=relation_data["group_id"]
                    ))
                except Exception as e:
                    logger.warning(f"Erreur parsing relation cache {relation_data.get('uuid')}: {e}")
                    continue

            # Limiter les résultats
            relations = relations[:limit]

            logger.info(f"Relations listées depuis cache: {len(relations)} résultats")
            return relations

        except Exception as e:
            logger.error(f"Erreur listage relations: {e}")
            raise

    async def delete_relation(self, relation_id: str) -> bool:
        """
        Supprime une relation du knowledge graph

        Args:
            relation_id: Identifiant de la relation à supprimer

        Returns:
            True si supprimé avec succès
        """
        await self._ensure_initialized()

        try:
            # ✅ PHASE 2: Vérifier que la relation appartient au groupe courant
            current_group = getattr(self, '_current_group_id', CORPORATE_GROUP_ID)

            # Vérifier dans le cache si la relation appartient au bon groupe
            if relation_id in _RELATION_CACHE:
                relation_group = _RELATION_CACHE[relation_id].get("group_id", CORPORATE_GROUP_ID)
                if relation_group != current_group:
                    logger.warning(f"Tentative suppression relation {relation_id} d'un autre groupe ({relation_group} != {current_group})")
                    return False  # Refuser suppression cross-groupe

            success = await self.store.delete_relation(relation_id)

            # Supprimer du cache temporaire aussi
            if relation_id in _RELATION_CACHE:
                del _RELATION_CACHE[relation_id]
                logger.info(f"Relation supprimée du cache: {relation_id}")

            if success:
                logger.info(f"Relation supprimée du store: {relation_id}")
            else:
                logger.warning(f"Relation {relation_id} non trouvée dans le store pour suppression")

            return success

        except Exception as e:
            logger.error(f"Erreur suppression relation {relation_id}: {e}")
            raise

    async def get_subgraph(self, request: SubgraphRequest) -> SubgraphResponse:
        """
        Récupère un sous-graphe centré sur une entité

        Args:
            request: Paramètres de la requête sous-graphe

        Returns:
            Sous-graphe structuré avec noeuds et arêtes
        """
        await self._ensure_initialized()

        try:
            logger.info(f"Génération sous-graphe pour entité {request.entity_id}, profondeur {request.depth}")

            # Récupérer l'entité centrale
            central_entity = await self.get_entity(request.entity_id)
            if not central_entity:
                raise ValueError(f"Entité centrale {request.entity_id} introuvable")

            logger.info(f"Entité centrale trouvée: {central_entity.name}")

            # Récupérer le sous-graphe via le store
            logger.info("Appel store.get_subgraph...")
            current_group = getattr(self, '_current_group_id', CORPORATE_GROUP_ID)
            subgraph_data = await self.store.get_subgraph(
                entity_id=request.entity_id,
                depth=request.depth,
                group_id=current_group
            )
            logger.info(f"Store.get_subgraph retourné: type={type(subgraph_data)}")

            # Transformer en format structuré
            nodes = []
            edges = []

            # Ajouter l'entité centrale
            central_node = GraphNode(
                uuid=central_entity.uuid,
                name=central_entity.name,
                entity_type=central_entity.entity_type,
                description=central_entity.description,
                attributes=central_entity.attributes
            )
            nodes.append(central_node)
            node_ids = {central_entity.uuid}

            # Traiter les données du sous-graphe
            logger.info(f"Données sous-graphe reçues: type={type(subgraph_data)}, count={len(subgraph_data) if hasattr(subgraph_data, '__len__') else 'N/A'}")

            for i, item in enumerate(subgraph_data):
                logger.debug(f"Item {i}: type={type(item)}, content={item}")

                # Vérifier que item est un dictionnaire
                if not isinstance(item, dict):
                    logger.warning(f"Item {i} n'est pas un dictionnaire: {type(item)} = {item}")
                    continue

                # Traiter comme relation/arête
                if isinstance(item, dict) and "source_entity_id" in item.get("attributes", {}):
                    attributes = item.get("attributes", {})

                    # Ajouter l'arête
                    try:
                        edge = GraphEdge(
                            uuid=item["uuid"],
                            source_id=attributes["source_entity_id"],
                            target_id=attributes["target_entity_id"],
                            relation_type=RelationType(item.get("predicate", "relates_to")),
                            description=attributes.get("description"),
                            confidence=item.get("confidence", 1.0),
                            attributes=attributes
                        )
                        edges.append(edge)

                        # Récupérer et ajouter les entités liées si pas déjà présentes
                        for entity_id in [edge.source_id, edge.target_id]:
                            if entity_id not in node_ids:
                                entity = await self.get_entity(entity_id)
                                if entity:
                                    node = GraphNode(
                                        uuid=entity.uuid,
                                        name=entity.name,
                                        entity_type=entity.entity_type,
                                        description=entity.description,
                                        attributes=entity.attributes
                                    )
                                    nodes.append(node)
                                    node_ids.add(entity_id)

                    except Exception as e:
                        logger.warning(f"Erreur traitement arête {item.get('uuid') if isinstance(item, dict) else 'N/A'}: {e}")
                        continue

            logger.info(f"Sous-graphe généré: {len(nodes)} noeuds, {len(edges)} arêtes")

            return SubgraphResponse(
                central_entity=central_node,
                nodes=nodes,
                edges=edges,
                depth_reached=min(request.depth, len(nodes)),
                total_nodes=len(nodes),
                total_edges=len(edges)
            )

        except Exception as e:
            logger.error(f"Erreur génération sous-graphe pour {request.entity_id}: {e}")
            raise

    async def get_stats(self) -> KnowledgeGraphStats:
        """
        Récupère les statistiques du knowledge graph corporate

        Returns:
            Statistiques complètes
        """
        await self._ensure_initialized()

        try:
            # ✅ Utiliser le groupe courant
            current_group = getattr(self, '_current_group_id', CORPORATE_GROUP_ID)

            # Compter directement dans Neo4j pour avoir des stats exactes
            from neo4j import GraphDatabase
            from knowbase.common.graphiti.config import GraphitiConfig

            config = GraphitiConfig.from_env()
            driver = GraphDatabase.driver(
                config.neo4j_uri,
                auth=(config.neo4j_user, config.neo4j_password)
            )

            with driver.session() as session:
                # Compter entités par groupe
                result = session.run(
                    "MATCH (n:Entity) WHERE n.group_id = $group_id RETURN count(n) as total",
                    group_id=current_group
                )
                total_entities = result.single()["total"]

                # Compter relations par groupe (via entités source)
                result = session.run(
                    """
                    MATCH (source:Entity)-[r]->(target:Entity)
                    WHERE source.group_id = $group_id
                    RETURN count(r) as total, type(r) as rel_type
                    """,
                    group_id=current_group
                )

                total_relations = 0
                relation_types_count = {}
                for record in result:
                    count = record["total"]
                    rel_type = record["rel_type"]
                    total_relations += count
                    relation_types_count[rel_type] = count

                # Compter types d'entités
                result = session.run(
                    """
                    MATCH (n:Entity)
                    WHERE n.group_id = $group_id
                    RETURN n.entity_type as type, count(*) as count
                    """,
                    group_id=current_group
                )

                entity_types_count = {}
                for record in result:
                    entity_type = record["type"]
                    count = record["count"]
                    if entity_type:
                        entity_types_count[entity_type] = count

            driver.close()

            logger.info(f"Stats KG: {total_entities} entités, {total_relations} relations (groupe: {current_group})")

            return KnowledgeGraphStats(
                total_entities=total_entities,
                total_relations=total_relations,
                entity_types_count=entity_types_count,
                relation_types_count=relation_types_count,
                group_id=current_group
            )

        except Exception as e:
            logger.error(f"Erreur calcul statistiques: {e}")
            raise
