"""
Service Knowledge Graph Utilisateur - Phase 2
Étend KnowledgeGraphService pour support multi-tenant utilisateur
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import Request

from knowbase.api.services.knowledge_graph import KnowledgeGraphService
from knowbase.api.services.user import UserService
from knowbase.api.middleware.user_context import get_user_context
from knowbase.api.schemas.knowledge_graph import (
    EntityCreate, EntityResponse, RelationCreate, RelationResponse,
    SubgraphRequest, SubgraphResponse, KnowledgeGraphStats
)

logger = logging.getLogger(__name__)


class UserKnowledgeGraphService(KnowledgeGraphService):
    """
    Service Knowledge Graph utilisateur avec support multi-tenant

    Fonctionnalités:
    - Auto-provisioning groupes utilisateur
    - Isolation par group_id utilisateur
    - Héritage complet de KnowledgeGraphService
    - Gestion contexte utilisateur
    """

    def __init__(self):
        """Initialise le service avec support utilisateur"""
        super().__init__()
        self.user_service = UserService()
        self._user_groups_initialized: Dict[str, bool] = {}

    async def _ensure_user_group_initialized(self, user_id: str, group_id: str):
        """
        Garantit que le groupe utilisateur existe et est initialisé

        Args:
            user_id: Identifiant utilisateur
            group_id: Identifiant groupe (user_{user_id})
        """
        if group_id in self._user_groups_initialized:
            return

        try:
            # Initialiser le store Graphiti si nécessaire
            if not self._initialized:
                await self._initialize_corporate_group()

            # Configurer le store pour le groupe utilisateur
            await self.store.set_group(group_id)

            # Vérifier la santé du système pour ce groupe
            health = await self.store.health()
            if not health:
                logger.warning(f"Store Graphiti pas complètement opérationnel pour {group_id}")

            # Créer le schéma de base utilisateur
            await self._create_user_base_schema(user_id, group_id)

            # Marquer comme initialisé
            self._user_groups_initialized[group_id] = True

            # Mettre à jour les métadonnées utilisateur
            await self._update_user_kg_metadata(user_id, group_id)

            logger.info(f"Groupe utilisateur '{group_id}' initialisé pour user {user_id}")

        except Exception as e:
            logger.error(f"Erreur initialisation groupe utilisateur {group_id}: {e}")
            raise

    async def _create_user_base_schema(self, user_id: str, group_id: str):
        """
        Crée le schéma de base pour un nouveau Knowledge Graph utilisateur

        Args:
            user_id: Identifiant utilisateur
            group_id: Identifiant groupe
        """
        try:
            # Créer une entité "Profile" utilisateur
            profile_entity = EntityCreate(
                name=f"Profile utilisateur {user_id}",
                entity_type="concept",
                description=f"Profil personnel de l'utilisateur {user_id}",
                attributes={
                    "user_id": user_id,
                    "kg_type": "personal",
                    "created_at": datetime.utcnow().isoformat(),
                    "schema_version": "1.0"
                }
            )

            # Utiliser la méthode parent avec le bon contexte
            original_group = getattr(self, '_current_group_id', None)
            self._current_group_id = group_id

            profile = await super().create_entity(profile_entity)

            logger.info(f"Profil utilisateur créé: {profile.uuid} pour {user_id}")

            # Restaurer le groupe original
            if original_group:
                self._current_group_id = original_group

        except Exception as e:
            logger.error(f"Erreur création schéma utilisateur {user_id}: {e}")
            # Non-bloquant pour l'initialisation

    async def _update_user_kg_metadata(self, user_id: str, group_id: str):
        """
        Met à jour les métadonnées Knowledge Graph de l'utilisateur

        Args:
            user_id: Identifiant utilisateur
            group_id: Identifiant groupe
        """
        try:
            # Récupérer l'utilisateur
            user = await self.user_service.get_user(user_id)
            if not user:
                logger.warning(f"Utilisateur {user_id} non trouvé pour mise à jour métadonnées")
                return

            # Mettre à jour avec les métadonnées KG
            update_data = {
                "graphiti_group_id": group_id,
                "kg_initialized": True,
                "kg_created_at": datetime.utcnow().isoformat(),
                "kg_preferences": {
                    "auto_expansion": True,
                    "default_depth": 2,
                    "favorite_entities": []
                }
            }

            # Utiliser le service utilisateur pour la mise à jour (non-async)
            self.user_service.update_user(user_id, update_data)

            logger.info(f"Métadonnées KG mises à jour pour utilisateur {user_id}")

        except Exception as e:
            logger.error(f"Erreur mise à jour métadonnées utilisateur {user_id}: {e}")
            # Non-bloquant

    async def _initialize_corporate_group(self):
        """Initialise le groupe corporate (ancien enterprise)"""
        try:
            # Initialiser le store Graphiti
            await self.store.initialize()

            # Configurer le store pour le groupe corporate
            await self.store.set_group("corporate")

            # Vérifier la santé du système
            health = await self.store.health()
            if not health:
                logger.warning("Store Graphiti n'est pas complètement opérationnel")

            logger.info("Groupe corporate initialisé")
            self._initialized = True

        except Exception as e:
            logger.error(f"Erreur initialisation groupe corporate: {e}")
            raise

    async def create_entity_for_user(self, request: Request, entity: EntityCreate) -> EntityResponse:
        """
        Crée une entité dans le Knowledge Graph de l'utilisateur

        Args:
            request: Requête FastAPI avec contexte utilisateur
            entity: Données de l'entité à créer

        Returns:
            Entité créée avec métadonnées utilisateur
        """
        context = get_user_context(request)

        if context["is_personal_kg"]:
            # Mode personnel - utiliser le groupe utilisateur
            user_id = context["user_id"]
            group_id = context["group_id"]

            await self._ensure_user_group_initialized(user_id, group_id)

            # Ajout métadonnées utilisateur
            entity.attributes = entity.attributes or {}
            entity.attributes.update({
                "created_by": user_id,
                "kg_type": "personal"
            })

            logger.info(f"Création entité utilisateur {user_id}: {entity.name}")

        else:
            # Mode corporate - utiliser le groupe corporate
            group_id = "corporate"
            logger.info(f"Création entité corporate: {entity.name}")

        # Configurer le groupe et utiliser la méthode parent
        original_group = getattr(self, '_current_group_id', None)
        self._current_group_id = group_id

        try:
            result = await super().create_entity(entity)
            return result

        finally:
            # Restaurer le groupe original
            if original_group:
                self._current_group_id = original_group

    async def get_user_stats(self, request: Request) -> KnowledgeGraphStats:
        """
        Récupère les statistiques du Knowledge Graph utilisateur

        Args:
            request: Requête avec contexte utilisateur

        Returns:
            Statistiques du KG utilisateur ou corporate
        """
        context = get_user_context(request)

        if context["is_personal_kg"]:
            user_id = context["user_id"]
            group_id = context["group_id"]

            await self._ensure_user_group_initialized(user_id, group_id)

            # Configurer pour le groupe utilisateur
            original_group = getattr(self, '_current_group_id', None)
            self._current_group_id = group_id

            try:
                stats = await super().get_stats()
                # Ajouter métadonnées utilisateur
                stats.group_id = user_id  # Afficher user_id plutôt que group_id interne
                return stats

            finally:
                if original_group:
                    self._current_group_id = original_group
        else:
            # Mode corporate
            return await super().get_stats()

    async def get_entity_for_user(self, request: Request, entity_id: str) -> Optional[EntityResponse]:
        """
        Récupère une entité dans le contexte utilisateur approprié
        """
        context = get_user_context(request)
        group_id = context["group_id"]

        if context["is_personal_kg"]:
            await self._ensure_user_group_initialized(context["user_id"], group_id)

        original_group = getattr(self, '_current_group_id', None)
        self._current_group_id = group_id

        try:
            return await super().get_entity(entity_id)
        finally:
            if original_group:
                self._current_group_id = original_group

    async def create_relation_for_user(self, request: Request, relation: RelationCreate) -> RelationResponse:
        """
        Crée une relation dans le contexte utilisateur approprié
        """
        context = get_user_context(request)
        group_id = context["group_id"]

        if context["is_personal_kg"]:
            user_id = context["user_id"]
            await self._ensure_user_group_initialized(user_id, group_id)

            # Ajout métadonnées utilisateur
            relation.attributes = relation.attributes or {}
            relation.attributes.update({
                "created_by": user_id,
                "kg_type": "personal"
            })

        original_group = getattr(self, '_current_group_id', None)
        self._current_group_id = group_id

        try:
            return await super().create_relation(relation)
        finally:
            if original_group:
                self._current_group_id = original_group

    async def list_relations_for_user(
        self,
        request: Request,
        entity_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        limit: int = 100
    ) -> List[RelationResponse]:
        """
        Liste les relations dans le contexte utilisateur approprié
        """
        context = get_user_context(request)
        group_id = context["group_id"]

        if context["is_personal_kg"]:
            await self._ensure_user_group_initialized(context["user_id"], group_id)

        original_group = getattr(self, '_current_group_id', None)
        self._current_group_id = group_id

        try:
            return await super().list_relations(entity_id, relation_type, limit)
        finally:
            if original_group:
                self._current_group_id = original_group

    async def delete_relation_for_user(self, request: Request, relation_id: str) -> bool:
        """
        Supprime une relation dans le contexte utilisateur approprié
        """
        context = get_user_context(request)
        group_id = context["group_id"]

        if context["is_personal_kg"]:
            await self._ensure_user_group_initialized(context["user_id"], group_id)

        original_group = getattr(self, '_current_group_id', None)
        self._current_group_id = group_id

        try:
            return await super().delete_relation(relation_id)
        finally:
            if original_group:
                self._current_group_id = original_group

    async def get_subgraph_for_user(self, request: Request, subgraph_request: SubgraphRequest) -> SubgraphResponse:
        """
        Récupère un sous-graphe dans le contexte utilisateur approprié
        """
        context = get_user_context(request)
        group_id = context["group_id"]

        if context["is_personal_kg"]:
            await self._ensure_user_group_initialized(context["user_id"], group_id)

        original_group = getattr(self, '_current_group_id', None)
        self._current_group_id = group_id

        try:
            return await super().get_subgraph(subgraph_request)
        finally:
            if original_group:
                self._current_group_id = original_group