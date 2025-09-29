"""
Gestionnaire multi-tenant pour Graphiti
"""
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from .graphiti_store import GraphitiStore
from .config import graphiti_config
from ..interfaces.graph_store import FactStatus

logger = logging.getLogger(__name__)


class GraphitiTenantManager:
    """
    Gestionnaire multi-tenant pour isoler les données par groupe
    """

    def __init__(self, store: GraphitiStore):
        """
        Initialise le gestionnaire de tenants

        Args:
            store: Instance GraphitiStore
        """
        self.store = store
        self._tenant_cache: Dict[str, Dict[str, Any]] = {}

    async def create_tenant(self, group_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Crée un nouveau tenant (groupe)

        Args:
            group_id: Identifiant unique du groupe
            metadata: Métadonnées du groupe (nom, description, etc.)

        Returns:
            Informations du tenant créé
        """
        if group_id in self._tenant_cache:
            logger.warning(f"Tenant {group_id} existe déjà")
            return self._tenant_cache[group_id]

        tenant_info = {
            "group_id": group_id,
            "created_at": datetime.now().isoformat(),
            "metadata": metadata or {},
            "stats": {
                "episodes_count": 0,
                "facts_count": 0,
                "last_activity": None
            }
        }

        # Créer un épisode initial pour marquer le tenant
        await self.store.create_episode(
            group_id=group_id,
            content=f"Initialisation du groupe {group_id}",
            episode_type="system",
            metadata={
                "action": "tenant_creation",
                **tenant_info
            }
        )

        self._tenant_cache[group_id] = tenant_info
        logger.info(f"Tenant créé: {group_id}")

        return tenant_info

    async def get_tenant_info(self, group_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les informations d'un tenant

        Args:
            group_id: Identifiant du groupe

        Returns:
            Informations du tenant ou None si inexistant
        """
        if group_id in self._tenant_cache:
            return self._tenant_cache[group_id]

        # Rechercher dans Graphiti
        try:
            episodes = await self.store.search_facts(
                query="tenant_creation",
                group_id=group_id,
                limit=1  # Ce paramètre sera géré dans search_facts
            )

            if episodes:
                episode = episodes[0]
                metadata = episode.get("metadata", {})

                tenant_info = {
                    "group_id": group_id,
                    "created_at": episode.get("created_at"),
                    "metadata": metadata.get("metadata", {}),
                    "stats": await self._calculate_tenant_stats(group_id)
                }

                self._tenant_cache[group_id] = tenant_info
                return tenant_info

        except Exception as e:
            logger.error(f"Erreur récupération tenant {group_id}: {e}")

        return None

    async def list_tenants(self) -> List[Dict[str, Any]]:
        """
        Liste tous les tenants

        Returns:
            Liste des tenants avec leurs informations
        """
        tenants = []

        # Ajouter les tenants en cache
        for tenant_info in self._tenant_cache.values():
            # Mettre à jour les stats
            group_id = tenant_info["group_id"]
            tenant_info["stats"] = await self._calculate_tenant_stats(group_id)
            tenants.append(tenant_info)

        logger.info(f"Tenants listés: {len(tenants)}")
        return tenants

    async def delete_tenant(self, group_id: str, confirm: bool = False) -> bool:
        """
        Supprime un tenant et toutes ses données

        Args:
            group_id: Identifiant du groupe
            confirm: Confirmation de suppression (sécurité)

        Returns:
            True si supprimé avec succès
        """
        if not confirm:
            logger.warning(f"Suppression tenant {group_id} non confirmée")
            return False

        try:
            # Note: Graphiti ne supporte pas encore la suppression par groupe
            # Cette fonctionnalité nécessiterait une requête Cypher directe
            logger.warning(f"Suppression tenant {group_id}: fonctionnalité non implémentée")

            # Retirer du cache
            if group_id in self._tenant_cache:
                del self._tenant_cache[group_id]

            return True

        except Exception as e:
            logger.error(f"Erreur suppression tenant {group_id}: {e}")
            return False

    async def isolate_tenant_data(self, group_id: str, action: str, **kwargs) -> Any:
        """
        Exécute une action en isolation pour un tenant

        Args:
            group_id: Identifiant du groupe
            action: Action à exécuter
            **kwargs: Arguments de l'action

        Returns:
            Résultat de l'action
        """
        # Vérifier que le tenant existe
        tenant_info = await self.get_tenant_info(group_id)
        if not tenant_info and action != "create_tenant":
            # Créer automatiquement le tenant si nécessaire
            await self.create_tenant(group_id)

        # Dispatcher les actions
        if action == "create_episode":
            return await self.store.create_episode(group_id=group_id, **kwargs)

        elif action == "create_fact":
            return await self.store.create_fact(group_id=group_id, **kwargs)

        elif action == "search_facts":
            return await self.store.search_facts(group_id=group_id, **kwargs)

        elif action == "get_memory":
            return await self.store.get_memory_for_group(group_id=group_id, **kwargs)

        elif action == "get_subgraph":
            return await self.store.get_subgraph(group_id=group_id, **kwargs)

        else:
            raise ValueError(f"Action inconnue: {action}")

    async def _calculate_tenant_stats(self, group_id: str) -> Dict[str, Any]:
        """
        Calcule les statistiques d'un tenant

        Args:
            group_id: Identifiant du groupe

        Returns:
            Statistiques du tenant
        """
        try:
            # Récupérer la mémoire récente
            memory = await self.store.get_memory_for_group(group_id, limit=100)

            # Compter les épisodes et faits
            episodes_count = len(memory)
            facts_count = len([item for item in memory
                             if item.get("metadata", {}).get("fact_type") == "knowledge_fact"])

            # Dernière activité
            last_activity = None
            if memory:
                last_activity = memory[0].get("created_at")

            return {
                "episodes_count": episodes_count,
                "facts_count": facts_count,
                "last_activity": last_activity
            }

        except Exception as e:
            logger.error(f"Erreur calcul stats tenant {group_id}: {e}")
            return {
                "episodes_count": 0,
                "facts_count": 0,
                "last_activity": None
            }

    async def migrate_tenant_data(self, source_group_id: str, target_group_id: str) -> bool:
        """
        Migre les données d'un tenant vers un autre

        Args:
            source_group_id: Groupe source
            target_group_id: Groupe cible

        Returns:
            True si migration réussie
        """
        try:
            # Récupérer toutes les données du tenant source
            memory = await self.store.get_memory_for_group(source_group_id, limit=1000)

            migration_count = 0
            for item in memory:
                # Créer un nouvel épisode dans le tenant cible
                metadata = item.get("metadata", {})
                metadata["migrated_from"] = source_group_id
                metadata["migration_date"] = datetime.now().isoformat()

                await self.store.create_episode(
                    group_id=target_group_id,
                    content=item["content"],
                    episode_type=metadata.get("episode_type", "message"),
                    metadata=metadata
                )
                migration_count += 1

            logger.info(f"Migration terminée: {migration_count} éléments de {source_group_id} vers {target_group_id}")
            return True

        except Exception as e:
            logger.error(f"Erreur migration {source_group_id} -> {target_group_id}: {e}")
            return False


# Factory pour créer le gestionnaire de tenants
async def create_tenant_manager() -> GraphitiTenantManager:
    """
    Crée et initialise un gestionnaire de tenants

    Returns:
        Instance GraphitiTenantManager initialisée
    """
    # Valider la configuration
    graphiti_config.validate()

    # Créer et initialiser le store
    store = GraphitiStore(
        neo4j_uri=graphiti_config.neo4j_uri,
        neo4j_user=graphiti_config.neo4j_user,
        neo4j_password=graphiti_config.neo4j_password,
        anthropic_api_key=graphiti_config.anthropic_api_key
    )

    await store.initialize()

    # Créer le gestionnaire
    manager = GraphitiTenantManager(store)

    logger.info("Gestionnaire de tenants Graphiti initialisé")
    return manager