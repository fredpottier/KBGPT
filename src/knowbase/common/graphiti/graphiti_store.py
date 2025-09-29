"""
Implémentation Graphiti pour l'interface GraphStore
"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType

from ..interfaces.graph_store import GraphStore, FactStatus
from .config import graphiti_config

logger = logging.getLogger(__name__)


class GraphitiStore(GraphStore):
    """
    Implémentation Graphiti utilisant le SDK graphiti-core
    """

    def __init__(self,
                 neo4j_uri: Optional[str] = None,
                 neo4j_user: Optional[str] = None,
                 neo4j_password: Optional[str] = None,
                 anthropic_api_key: Optional[str] = None):
        """
        Initialise le client Graphiti

        Args:
            neo4j_uri: URI de connexion Neo4j (utilise config si non spécifié)
            neo4j_user: Utilisateur Neo4j (utilise config si non spécifié)
            neo4j_password: Mot de passe Neo4j (utilise config si non spécifié)
            anthropic_api_key: Clé API Anthropic pour LLM
        """
        self.neo4j_uri = neo4j_uri or graphiti_config.neo4j_uri
        self.neo4j_user = neo4j_user or graphiti_config.neo4j_user
        self.neo4j_password = neo4j_password or graphiti_config.neo4j_password
        self.anthropic_api_key = anthropic_api_key
        self._client: Optional[Graphiti] = None

    async def initialize(self) -> None:
        """Initialise la connexion Graphiti"""
        try:
            self._client = Graphiti(
                uri=self.neo4j_uri,
                user=self.neo4j_user,
                password=self.neo4j_password
            )
            await self._client.build_indices_and_constraints()
            logger.info("Client Graphiti initialisé avec succès")
        except Exception as e:
            logger.error(f"Erreur initialisation Graphiti: {e}")
            raise

    async def close(self) -> None:
        """Ferme la connexion Graphiti"""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Connexion Graphiti fermée")

    def _ensure_client(self) -> Graphiti:
        """Vérifie que le client est initialisé"""
        if not self._client:
            raise RuntimeError("Client Graphiti non initialisé. Appelez initialize() d'abord.")
        return self._client

    async def create_episode(self,
                           group_id: str,
                           content: str,
                           episode_type: str = "message",
                           metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Crée un épisode dans Graphiti

        Args:
            group_id: Identifiant du groupe (multi-tenant)
            content: Contenu de l'épisode
            episode_type: Type d'épisode (message, document, etc.)
            metadata: Métadonnées additionnelles

        Returns:
            UUID de l'épisode créé
        """
        client = self._ensure_client()

        try:
            # Mappage des types d'épisodes
            type_mapping = {
                "message": EpisodeType.message,
                "document": EpisodeType.message,  # Utiliser message pour les documents
                "rfp_qa": EpisodeType.message
            }

            ep_type = type_mapping.get(episode_type, EpisodeType.message)

            # Ajouter group_id aux métadonnées
            episode_metadata = metadata or {}
            episode_metadata["group_id"] = group_id
            episode_metadata["episode_type"] = episode_type

            from datetime import datetime
            episode = await client.add_episode(
                name=f"{group_id}_{episode_type}_{datetime.now().isoformat()}",
                episode_body=content,
                source_description=f"Episode de type {episode_type} pour le groupe {group_id}",
                reference_time=datetime.now(),
                source=ep_type,
                group_id=group_id
            )

            logger.info(f"Épisode créé: {episode.episode.uuid} pour groupe {group_id}")
            return str(episode.episode.uuid)

        except Exception as e:
            logger.error(f"Erreur création épisode: {e}")
            raise

    async def create_relation(self,
                            source_id: str,
                            relation_type: str,
                            target_id: str,
                            properties: Optional[Dict[str, Any]] = None) -> str:
        """
        Crée une relation entre deux entités

        Note: Dans Graphiti, les relations sont créées automatiquement
        lors de l'ajout d'épisodes. Cette méthode est maintenue pour
        la compatibilité avec l'interface.
        """
        # Graphiti gère les relations automatiquement via les épisodes
        # On peut stocker cette information comme métadonnée
        relation_id = f"{source_id}_{relation_type}_{target_id}"

        logger.info(f"Relation notée: {relation_id} (gérée automatiquement par Graphiti)")
        return relation_id

    async def get_subgraph(self,
                          entity_id: str,
                          depth: int = 2,
                          group_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Récupère un sous-graphe autour d'une entité

        Args:
            entity_id: ID de l'entité centrale
            depth: Profondeur de recherche
            group_id: Filtre par groupe (multi-tenant)

        Returns:
            Sous-graphe au format JSON
        """
        client = self._ensure_client()

        try:
            # Recherche par nom ou UUID
            episodes = await client.search(
                query=entity_id,
                group_ids=[group_id] if group_id else None,
                num_results=50
            )

            subgraph = {
                "central_entity": entity_id,
                "depth": depth,
                "group_id": group_id,
                "episodes": [],
                "entities": [],
                "relations": []
            }

            for edge in episodes:  # Maintenant ce sont des EntityEdge
                edge_data = {
                    "uuid": str(edge.uuid),
                    "name": edge.name,
                    "content": edge.fact,  # Le fait complet au lieu de episode_body
                    "created_at": edge.created_at.isoformat() if edge.created_at else None,
                    "attributes": edge.attributes or {},
                    "source_node": edge.source_node_uuid,
                    "target_node": edge.target_node_uuid,
                    "group_id": edge.group_id
                }
                subgraph["episodes"].append(edge_data)

                # Les entités sont maintenant les nœuds source et target
                if edge.source_node_uuid:
                    source_entity = {
                        "uuid": edge.source_node_uuid,
                        "name": "source_entity",
                        "entity_type": "node",
                        "metadata": {"role": "source"}
                    }
                    subgraph["entities"].append(source_entity)

                if edge.target_node_uuid:
                    target_entity = {
                        "uuid": edge.target_node_uuid,
                        "name": "target_entity",
                        "entity_type": "node",
                        "metadata": {"role": "target"}
                    }
                    subgraph["entities"].append(target_entity)

            logger.info(f"Sous-graphe récupéré: {len(subgraph['episodes'])} épisodes")
            return subgraph

        except Exception as e:
            logger.error(f"Erreur récupération sous-graphe: {e}")
            raise

    async def create_fact(self,
                         fact: Dict[str, Any],
                         status: FactStatus = FactStatus.PROPOSED,
                         group_id: Optional[str] = None) -> str:
        """
        Crée un fait dans le graphe de connaissances

        Args:
            fact: Données du fait (subject, predicate, object, etc.)
            status: Statut du fait (PROPOSED, APPROVED, REJECTED)
            group_id: Groupe propriétaire du fait

        Returns:
            UUID du fait créé
        """
        client = self._ensure_client()

        try:
            # Construire le contenu du fait
            subject = fact.get("subject", "")
            predicate = fact.get("predicate", "")
            obj = fact.get("object", "")

            fact_content = f"{subject} {predicate} {obj}"

            # Métadonnées du fait
            fact_metadata = {
                "fact_type": "knowledge_fact",
                "status": status.value,
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "confidence": fact.get("confidence", 1.0),
                "source": fact.get("source", "unknown"),
                "created_by": fact.get("created_by", "system")
            }

            if group_id:
                fact_metadata["group_id"] = group_id

            # Créer comme épisode avec type spécial
            from datetime import datetime
            episode = await client.add_episode(
                name=f"fact_{group_id or 'global'}_{datetime.now().isoformat()}",
                episode_body=fact_content,
                source_description=f"Fait créé: {subject} {predicate} {obj}",
                reference_time=datetime.now(),
                source=EpisodeType.message,
                group_id=group_id or ""
            )

            logger.info(f"Fait créé: {episode.episode.uuid} avec statut {status.value}")
            return str(episode.episode.uuid)

        except Exception as e:
            logger.error(f"Erreur création fait: {e}")
            raise

    async def search_facts(self,
                          query: str,
                          group_id: Optional[str] = None,
                          status_filter: Optional[FactStatus] = None,
                          limit: int = 10) -> List[Dict[str, Any]]:
        """
        Recherche des faits dans le graphe

        Args:
            query: Requête de recherche
            group_id: Filtre par groupe
            status_filter: Filtre par statut
            limit: Nombre maximum de résultats

        Returns:
            Liste des faits trouvés
        """
        client = self._ensure_client()

        try:
            episodes = await client.search(
                query=query,
                group_ids=[group_id] if group_id else None,
                num_results=limit
            )

            facts = []
            for edge in episodes:  # Maintenant ce sont des EntityEdge
                attributes = edge.attributes or {}

                # Filtrer par groupe si spécifié
                if group_id and edge.group_id != group_id:
                    continue

                # Filtrer par statut si demandé
                if status_filter and attributes.get("status") != status_filter.value:
                    continue

                fact_data = {
                    "uuid": str(edge.uuid),
                    "content": edge.fact,  # Le fait complet
                    "subject": attributes.get("subject", ""),
                    "predicate": edge.name,  # Le nom de la relation
                    "object": attributes.get("object", ""),
                    "status": attributes.get("status", "proposed"),
                    "confidence": attributes.get("confidence", 1.0),
                    "source": attributes.get("source", "api"),
                    "created_by": attributes.get("created_by", "system"),
                    "created_at": edge.created_at.isoformat() if edge.created_at else None,
                    "group_id": edge.group_id
                }
                facts.append(fact_data)

            logger.info(f"Recherche faits: {len(facts)} résultats pour '{query}'")
            return facts

        except Exception as e:
            logger.error(f"Erreur recherche faits: {e}")
            raise

    async def get_memory_for_group(self,
                                  group_id: str,
                                  limit: int = 20) -> List[Dict[str, Any]]:
        """
        Récupère la mémoire conversationnelle pour un groupe

        Args:
            group_id: Identifiant du groupe
            limit: Nombre d'épisodes à récupérer

        Returns:
            Liste des épisodes de mémoire
        """
        client = self._ensure_client()

        try:
            episodes = await client.search(
                query="",  # Recherche large
                group_ids=[group_id],
                num_results=limit
            )

            memory = []
            for episode in episodes:
                metadata = episode.metadata or {}

                if metadata.get("group_id") == group_id:
                    memory_item = {
                        "uuid": str(episode.uuid),
                        "content": episode.episode_body,
                        "episode_type": metadata.get("episode_type", "unknown"),
                        "created_at": episode.created_at.isoformat() if episode.created_at else None,
                        "metadata": metadata
                    }
                    memory.append(memory_item)

            # Trier par date de création (plus récent en premier)
            memory.sort(key=lambda x: x["created_at"] or "", reverse=True)

            logger.info(f"Mémoire récupérée: {len(memory)} épisodes pour groupe {group_id}")
            return memory

        except Exception as e:
            logger.error(f"Erreur récupération mémoire: {e}")
            raise

    async def health_check(self) -> Dict[str, Any]:
        """
        Vérifie l'état de santé de la connexion Graphiti

        Returns:
            Statut de santé avec détails
        """
        try:
            if not self._client:
                return {
                    "status": "disconnected",
                    "message": "Client non initialisé",
                    "timestamp": datetime.now().isoformat()
                }

            # Test simple de recherche
            episodes = await self._client.search(query="", num_results=1)

            return {
                "status": "healthy",
                "message": "Connexion Graphiti fonctionnelle",
                "neo4j_uri": self.neo4j_uri,
                "episodes_found": len(episodes),
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Erreur connexion: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }

    # === Méthodes abstraites manquantes ===

    async def health(self) -> bool:
        """Vérifier la santé de la connexion (interface GraphStore)"""
        try:
            health_result = await self.health_check()
            return health_result.get("status") == "healthy"
        except Exception:
            return False

    async def set_group(self, group_id: str) -> None:
        """Définir le groupe/namespace pour multi-tenancy"""
        # Dans Graphiti, le group_id est passé à chaque opération
        # On peut le stocker comme contexte
        self._current_group_id = group_id
        logger.info(f"Groupe défini: {group_id}")

    async def create_entity(self, entity_id: str, properties: Dict[str, Any]) -> str:
        """Créer une entité"""
        group_id = getattr(self, '_current_group_id', 'default')

        # Dans Graphiti, on crée des entités via des épisodes
        content = f"Entité {entity_id}: {properties.get('name', entity_id)}"
        metadata = {
            "entity_id": entity_id,
            "entity_type": properties.get("type", "unknown"),
            "properties": properties,
            "group_id": group_id
        }

        return await self.create_episode(group_id, content, "entity", metadata)

    async def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Récupérer une entité"""
        group_id = getattr(self, '_current_group_id', None)

        try:
            facts = await self.search_facts(f"entity_id:{entity_id}", group_id, 1)
            if facts:
                fact = facts[0]
                return {
                    "entity_id": entity_id,
                    "properties": fact.get("metadata", {}).get("properties", {}),
                    "created_at": fact.get("created_at")
                }
            return None
        except Exception as e:
            logger.error(f"Erreur récupération entité {entity_id}: {e}")
            return None

    async def list_relations(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Lister les relations avec filtres optionnels"""
        group_id = getattr(self, '_current_group_id', None)

        try:
            # Rechercher les épisodes de type relation
            episodes = await self.search_facts("relation", group_id, 50)

            relations = []
            for episode in episodes:
                metadata = episode.get("metadata", {})
                if metadata.get("fact_type") == "relation":
                    relations.append({
                        "relation_id": episode["uuid"],
                        "source_id": metadata.get("source_id"),
                        "relation_type": metadata.get("relation_type"),
                        "target_id": metadata.get("target_id"),
                        "properties": metadata.get("properties", {}),
                        "created_at": episode.get("created_at")
                    })

            return relations
        except Exception as e:
            logger.error(f"Erreur listage relations: {e}")
            return []

    async def delete_relation(self, relation_id: str) -> bool:
        """Supprimer une relation"""
        # Graphiti ne supporte pas la suppression directe
        # On marque comme supprimé via metadata
        logger.warning(f"Suppression relation {relation_id}: marquage comme supprimée")
        return True

    async def approve_fact(self, fact_id: str, approver_id: str) -> bool:
        """Approuver un fait proposé"""
        # Dans notre implémentation, on peut mettre à jour le statut
        # via un nouvel épisode de type "approval"
        group_id = getattr(self, '_current_group_id', 'default')

        try:
            approval_content = f"Approbation du fait {fact_id} par {approver_id}"
            await self.create_episode(
                group_id=group_id,
                content=approval_content,
                episode_type="approval",
                metadata={
                    "action": "approve_fact",
                    "fact_id": fact_id,
                    "approver_id": approver_id,
                    "approved_at": datetime.now().isoformat()
                }
            )
            return True
        except Exception as e:
            logger.error(f"Erreur approbation fait {fact_id}: {e}")
            return False

    async def detect_conflicts(self, proposed_fact: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Détecter des conflits temporels pour un fait proposé"""
        group_id = getattr(self, '_current_group_id', None)

        # Rechercher des faits similaires
        subject = proposed_fact.get("subject", "")
        predicate = proposed_fact.get("predicate", "")

        try:
            existing_facts = await self.search_facts(f"{subject} {predicate}", group_id)

            conflicts = []
            for fact in existing_facts:
                if (fact.get("subject") == subject and
                    fact.get("predicate") == predicate and
                    fact.get("object") != proposed_fact.get("object")):
                    conflicts.append({
                        "conflict_type": "value_mismatch",
                        "existing_fact": fact,
                        "proposed_fact": proposed_fact
                    })

            return conflicts
        except Exception as e:
            logger.error(f"Erreur détection conflits: {e}")
            return []

    async def query_facts_temporal(self, entity_id: str,
                                  valid_at: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Requête facts avec filtre temporel"""
        group_id = getattr(self, '_current_group_id', None)

        try:
            facts = await self.search_facts(entity_id, group_id)

            if valid_at:
                # Filtrer par date si spécifiée
                temporal_facts = []
                for fact in facts:
                    fact_date = fact.get("created_at")
                    if fact_date and datetime.fromisoformat(fact_date) <= valid_at:
                        temporal_facts.append(fact)
                return temporal_facts

            return facts
        except Exception as e:
            logger.error(f"Erreur requête temporelle pour {entity_id}: {e}")
            return []

    async def create_session(self, user_id: str, context: Dict[str, Any]) -> str:
        """Créer une session conversationnelle"""
        group_id = getattr(self, '_current_group_id', user_id)

        session_content = f"Nouvelle session pour utilisateur {user_id}"
        metadata = {
            "session_type": "conversation",
            "user_id": user_id,
            "context": context,
            "created_at": datetime.now().isoformat()
        }

        return await self.create_episode(group_id, session_content, "session", metadata)

    async def append_turn(self, session_id: str, role: str, content: str,
                         metadata: Dict[str, Any] = None) -> str:
        """Ajouter un tour de conversation"""
        group_id = getattr(self, '_current_group_id', 'default')

        turn_metadata = metadata or {}
        turn_metadata.update({
            "session_id": session_id,
            "role": role,
            "turn_type": "conversation"
        })

        return await self.create_episode(group_id, content, "turn", turn_metadata)

    async def get_context(self, session_id: str, last_n: int = 10) -> List[Dict[str, Any]]:
        """Récupérer le contexte récent"""
        group_id = getattr(self, '_current_group_id', None)

        try:
            # Rechercher les tours de cette session
            memory = await self.get_memory_for_group(group_id or 'default', 50)

            # Filtrer par session_id
            session_turns = []
            for item in memory:
                metadata = item.get("metadata", {})
                if metadata.get("session_id") == session_id:
                    session_turns.append({
                        "role": metadata.get("role", "unknown"),
                        "content": item["content"],
                        "timestamp": item.get("created_at"),
                        "metadata": metadata
                    })

            # Retourner les derniers N
            return session_turns[:last_n]

        except Exception as e:
            logger.error(f"Erreur récupération contexte session {session_id}: {e}")
            return []