"""
Client Graphiti - Interface avec service Graphiti Knowledge Graph

Phase: Phase 1 Critère 1.3
Référence: https://github.com/getzep/graphiti

Architecture:
- Graphiti service (zepai/graphiti:latest) expose API REST
- Episodes = unité d'ingestion groupant entities/relations d'un document
- Nodes = entities extraites (CONCEPT, PRODUCT, TECHNOLOGY, etc.)
- Edges = relations entre entities (USES, PROVIDES, INTEGRATES_WITH, etc.)
"""

import logging
import httpx
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class GraphitiClient:
    """
    Client HTTP pour service Graphiti

    Endpoints principaux:
    - POST /messages - Ajouter messages/épisodes avec entities/relations
    - POST /search - Recherche sémantique dans le KG
    - GET /episodes/{group_id} - Récupérer épisodes d'un groupe
    - GET /episode/{uuid} - Récupérer épisode par UUID
    - GET /healthcheck - Vérifier santé du service
    """

    def __init__(self, base_url: str = "http://graphiti:8000"):
        """
        Initialiser client Graphiti

        Args:
            base_url: URL de base du service Graphiti
                     Docker: http://graphiti:8000
                     Local: http://localhost:8300
        """
        self.base_url = base_url.rstrip('/')
        self.client = httpx.Client(timeout=120.0)  # 2 min timeout pour ingestion

        logger.info(f"[GraphitiClient] Initialisé avec base_url: {self.base_url}")

    def healthcheck(self) -> bool:
        """
        Vérifier disponibilité du service Graphiti

        Returns:
            True si service disponible, False sinon
        """
        try:
            response = self.client.get(f"{self.base_url}/healthcheck")
            response.raise_for_status()
            data = response.json()
            is_healthy = data.get("status") == "healthy"

            if is_healthy:
                logger.debug("[GraphitiClient] ✅ Service healthy")
            else:
                logger.warning(f"[GraphitiClient] ⚠️ Service unhealthy: {data}")

            return is_healthy

        except Exception as e:
            logger.error(f"[GraphitiClient] ❌ Healthcheck failed: {e}")
            return False

    def add_episode(
        self,
        group_id: str,
        messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Ajouter un épisode avec entities/relations

        Un épisode = ingestion d'un document complet avec toutes ses entities/relations

        Args:
            group_id: ID du groupe/tenant (ex: "client_acme")
            messages: Liste de messages avec entities/relations extraites
                Format Graphiti:
                {
                    "content": "Text content of the slide/chunk",
                    "role_type": "user",  # Requis: "user", "assistant" ou "system"
                    "entities": [
                        {
                            "name": "SAP S/4HANA",
                            "entity_type": "PRODUCT",
                            "summary": "Enterprise ERP solution"
                        }
                    ],
                    "relations": [
                        {
                            "source": "SAP S/4HANA",
                            "target": "Cloud Computing",
                            "relation_type": "USES"
                        }
                    ]
                }

        Returns:
            {
                "episode_id": "uuid",
                "entities_created": int,
                "relations_created": int,
                "processing_time_ms": float
            }

        Raises:
            httpx.HTTPError: Si requête échoue
        """
        payload = {
            "group_id": group_id,
            "messages": messages
        }

        logger.info(
            f"[GraphitiClient] 📤 Ajout épisode: group_id={group_id}, "
            f"{len(messages)} messages"
        )

        try:
            response = self.client.post(
                f"{self.base_url}/messages",
                json=payload
            )
            response.raise_for_status()
            result = response.json()

            logger.info(
                f"[GraphitiClient] ✅ Épisode créé: "
                f"episode_id={result.get('episode_id', 'N/A')}"
            )

            return result

        except httpx.HTTPError as e:
            logger.error(f"[GraphitiClient] ❌ Échec ajout épisode: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response body: {e.response.text}")
            raise

    def search(
        self,
        query: str,
        group_id: str,
        limit: int = 10,
        center_node_uuid: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Recherche sémantique dans le Knowledge Graph

        Args:
            query: Requête en langage naturel
            group_id: ID du groupe/tenant
            limit: Nombre max de résultats
            center_node_uuid: UUID d'un noeud central pour recherche contextuelle

        Returns:
            {
                "nodes": [...],  # Entities trouvées
                "edges": [...],  # Relations trouvées
                "facts": [...]   # Facts extraits
            }
        """
        payload = {
            "query": query,
            "group_id": group_id,
            "limit": limit
        }

        if center_node_uuid:
            payload["center_node_uuid"] = center_node_uuid

        logger.debug(f"[GraphitiClient] 🔍 Search: query='{query[:50]}...', group_id={group_id}")

        try:
            response = self.client.post(f"{self.base_url}/search", json=payload)
            response.raise_for_status()
            result = response.json()

            logger.debug(
                f"[GraphitiClient] ✅ Search results: "
                f"{len(result.get('nodes', []))} nodes, "
                f"{len(result.get('edges', []))} edges"
            )

            return result

        except httpx.HTTPError as e:
            logger.error(f"[GraphitiClient] ❌ Search failed: {e}")
            raise

    def get_episodes(self, group_id: str, last_n: int = 100) -> List[Dict[str, Any]]:
        """
        Récupérer les N derniers épisodes d'un groupe

        Args:
            group_id: ID du groupe/tenant
            last_n: Nombre d'épisodes à récupérer (défaut: 100)

        Returns:
            Liste d'épisodes avec métadonnées
        """
        try:
            response = self.client.get(
                f"{self.base_url}/episodes/{group_id}",
                params={"last_n": last_n}
            )
            response.raise_for_status()
            episodes = response.json()

            logger.debug(f"[GraphitiClient] ✅ {len(episodes)} épisodes pour group_id={group_id}")
            return episodes

        except httpx.HTTPError as e:
            logger.error(f"[GraphitiClient] ❌ Get episodes failed: {e}")
            raise

    def get_episode(self, episode_uuid: str, group_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupérer un épisode par UUID

        Note: L'API Graphiti ne fournit pas d'endpoint GET /episode/{uuid}.
        On récupère tous les episodes du groupe et on filtre par name.

        Args:
            episode_uuid: UUID de l'épisode (utilisé comme name dans Graphiti)
            group_id: ID du groupe/tenant

        Returns:
            Métadonnées de l'épisode ou None si non trouvé
        """
        try:
            # Récupérer tous les episodes du groupe
            all_episodes = self.get_episodes(group_id=group_id)

            # Filtrer par name (qui correspond à notre episode_uuid)
            for episode in all_episodes:
                if episode.get('name') == episode_uuid:
                    logger.debug(f"[GraphitiClient] ✅ Episode trouvé: {episode_uuid}")
                    return episode

            logger.warning(f"[GraphitiClient] ⚠️ Episode non trouvé: {episode_uuid}")
            return None

        except httpx.HTTPError as e:
            logger.error(f"[GraphitiClient] ❌ Get episode failed: {e}")
            raise

    def delete_episode(self, episode_uuid: str) -> bool:
        """
        Supprimer un épisode

        Args:
            episode_uuid: UUID de l'épisode

        Returns:
            True si succès
        """
        try:
            response = self.client.delete(f"{self.base_url}/episode/{episode_uuid}")
            response.raise_for_status()

            logger.info(f"[GraphitiClient] ✅ Episode supprimé: {episode_uuid}")
            return True

        except httpx.HTTPError as e:
            logger.error(f"[GraphitiClient] ❌ Delete episode failed: {e}")
            raise

    def clear_group(self, group_id: str) -> bool:
        """
        Supprimer toutes les données d'un groupe

        ATTENTION: Opération destructive !

        Args:
            group_id: ID du groupe/tenant

        Returns:
            True si succès
        """
        try:
            response = self.client.delete(f"{self.base_url}/group/{group_id}")
            response.raise_for_status()

            logger.warning(f"[GraphitiClient] ⚠️ Groupe supprimé: {group_id}")
            return True

        except httpx.HTTPError as e:
            logger.error(f"[GraphitiClient] ❌ Clear group failed: {e}")
            raise

    def close(self):
        """Fermer connexion HTTP"""
        self.client.close()
        logger.debug("[GraphitiClient] Connexion fermée")


# Instance globale (singleton)
_graphiti_client: Optional[GraphitiClient] = None


def get_graphiti_client(base_url: str = "http://graphiti:8000") -> GraphitiClient:
    """
    Récupérer instance singleton du client Graphiti

    Args:
        base_url: URL de base (défaut: http://graphiti:8000 pour Docker)

    Returns:
        Instance globale de GraphitiClient

    Usage:
        >>> from knowbase.graphiti.graphiti_client import get_graphiti_client
        >>> client = get_graphiti_client()
        >>> if client.healthcheck():
        >>>     result = client.add_episode(group_id="acme", messages=[...])
    """
    global _graphiti_client

    if _graphiti_client is None:
        _graphiti_client = GraphitiClient(base_url=base_url)

        # Vérifier disponibilité au premier appel
        if not _graphiti_client.healthcheck():
            logger.warning(
                "[GraphitiClient] ⚠️ Service Graphiti non disponible au démarrage. "
                "Mode fallback activé."
            )

    return _graphiti_client
