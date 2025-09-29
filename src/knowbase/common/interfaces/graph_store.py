"""
Interface GraphStore - Abstraction pour Knowledge Graph operations
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum


class FactStatus(Enum):
    """Statuts pour les facts"""
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class GraphStore(ABC):
    """Interface abstraite pour les opérations Knowledge Graph"""

    @abstractmethod
    async def health(self) -> bool:
        """Vérifier la santé de la connexion"""
        pass

    @abstractmethod
    async def set_group(self, group_id: str) -> None:
        """Définir le groupe/namespace pour multi-tenancy"""
        pass

    # === CRUD Entités ===

    @abstractmethod
    async def create_entity(self, entity_id: str, properties: Dict[str, Any]) -> str:
        """Créer une entité"""
        pass

    @abstractmethod
    async def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Récupérer une entité"""
        pass

    # === CRUD Relations ===

    @abstractmethod
    async def create_relation(self, source_id: str, relation_type: str,
                             target_id: str, properties: Dict[str, Any] = None) -> str:
        """Créer une relation entre deux entités"""
        pass

    @abstractmethod
    async def list_relations(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Lister les relations avec filtres optionnels"""
        pass

    @abstractmethod
    async def delete_relation(self, relation_id: str) -> bool:
        """Supprimer une relation"""
        pass

    # === Sous-graphes ===

    @abstractmethod
    async def get_subgraph(self, entity_id: str, depth: int = 2) -> Dict[str, Any]:
        """Récupérer un sous-graphe autour d'une entité"""
        pass

    # === Facts avec gouvernance ===

    @abstractmethod
    async def create_fact(self, fact: Dict[str, Any],
                         status: FactStatus = FactStatus.PROPOSED) -> str:
        """Créer un fait avec statut initial"""
        pass

    @abstractmethod
    async def approve_fact(self, fact_id: str, approver_id: str) -> bool:
        """Approuver un fait proposé"""
        pass

    @abstractmethod
    async def detect_conflicts(self, proposed_fact: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Détecter des conflits temporels pour un fait proposé"""
        pass

    @abstractmethod
    async def query_facts_temporal(self, entity_id: str,
                                  valid_at: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Requête facts avec filtre temporel"""
        pass

    # === Mémoire conversationnelle ===

    @abstractmethod
    async def create_session(self, user_id: str, context: Dict[str, Any]) -> str:
        """Créer une session conversationnelle"""
        pass

    @abstractmethod
    async def append_turn(self, session_id: str, role: str, content: str,
                         metadata: Dict[str, Any] = None) -> str:
        """Ajouter un tour de conversation"""
        pass

    @abstractmethod
    async def get_context(self, session_id: str, last_n: int = 10) -> List[Dict[str, Any]]:
        """Récupérer le contexte récent"""
        pass