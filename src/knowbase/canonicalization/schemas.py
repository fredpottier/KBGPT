"""
Schémas Pydantic pour la canonicalisation d'entités
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class EntityCandidateStatus(str, Enum):
    """Statuts des entités candidates"""
    CANDIDATE = "candidate"     # Entité extraite automatiquement, en attente
    SEED = "seed"              # Entité promue automatiquement (bootstrap)
    CANONICAL = "canonical"    # Entité canonique validée manuellement
    REJECTED = "rejected"      # Entité rejetée


class EntityCandidate(BaseModel):
    """Entité candidate extraite automatiquement"""
    name: str = Field(..., description="Nom de l'entité candidate")
    entity_type: str = Field(..., description="Type d'entité")
    description: Optional[str] = Field(None, description="Description extraite")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confiance extraction")
    occurrences: int = Field(default=1, ge=1, description="Nombre d'occurrences détectées")
    status: EntityCandidateStatus = Field(default=EntityCandidateStatus.CANDIDATE)
    group_id: str = Field(..., description="Groupe multi-tenant")
    source_chunks: List[str] = Field(default_factory=list, description="IDs chunks sources")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Attributs additionnels")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BootstrapConfig(BaseModel):
    """Configuration pour le bootstrap automatique"""
    min_occurrences: int = Field(default=10, ge=1, description="Minimum d'occurrences requises")
    min_confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence minimale")
    group_id: Optional[str] = Field(None, description="Groupe à bootstrap (None = tous)")
    entity_types: Optional[List[str]] = Field(None, description="Types d'entités à inclure")
    dry_run: bool = Field(default=False, description="Mode simulation (pas de modification)")


class BootstrapResult(BaseModel):
    """Résultat d'un bootstrap"""
    total_candidates: int = Field(..., description="Nombre total de candidates analysées")
    promoted_seeds: int = Field(..., description="Nombre d'entités promues en seeds")
    seed_ids: List[str] = Field(..., description="IDs des seeds créées")
    duration_seconds: float = Field(..., description="Durée d'exécution")
    dry_run: bool = Field(..., description="Mode simulation activé")
    by_entity_type: Dict[str, int] = Field(default_factory=dict, description="Répartition par type")


class BootstrapProgress(BaseModel):
    """Progression d'un bootstrap en cours"""
    status: str = Field(..., description="État actuel (running/completed/failed)")
    processed: int = Field(..., description="Candidates traitées")
    total: int = Field(..., description="Total de candidates")
    promoted: int = Field(..., description="Seeds promues")
    current_entity: Optional[str] = Field(None, description="Entité en cours")
    started_at: datetime = Field(..., description="Début d'exécution")
    estimated_completion: Optional[datetime] = Field(None, description="Fin estimée")


class MergeEntitiesRequest(BaseModel):
    """Requête merge candidates vers entité canonique"""
    canonical_entity_id: str = Field(..., description="UUID entité canonique cible")
    candidate_ids: List[str] = Field(..., min_length=1, description="Liste UUIDs candidates à merger")
    user_id: Optional[str] = Field(None, description="Utilisateur effectuant merge")


class MergeEntitiesResponse(BaseModel):
    """Réponse merge entities"""
    canonical_entity_id: str = Field(..., description="UUID entité canonique")
    merged_candidates: List[str] = Field(..., description="Candidates mergées")
    merge_count: int = Field(..., description="Nombre candidates mergées")
    operation: str = Field(..., description="Type opération (merge)")
    idempotency_key: str = Field(..., description="Clé idempotence")
    user_id: Optional[str] = Field(None, description="Utilisateur")
    version_metadata: Dict[str, Any] = Field(..., description="Metadata versioning")
    executed_at: str = Field(..., description="Timestamp exécution")
    status: str = Field(..., description="Statut (completed, failed)")
    result_hash: str = Field(..., description="Hash déterministe résultat")


class CreateNewCanonicalRequest(BaseModel):
    """Requête création nouvelle entité canonique"""
    candidate_ids: List[str] = Field(..., min_length=1, description="Liste UUIDs candidates sources")
    canonical_name: str = Field(..., min_length=1, description="Nom entité canonique à créer")
    entity_type: str = Field(..., description="Type entité (solution, product, concept, etc.)")
    description: Optional[str] = Field(None, description="Description optionnelle")
    user_id: Optional[str] = Field(None, description="Utilisateur effectuant création")


class CreateNewCanonicalResponse(BaseModel):
    """Réponse création nouvelle entité canonique"""
    canonical_entity_id: str = Field(..., description="UUID entité canonique créée")
    canonical_name: str = Field(..., description="Nom entité")
    entity_type: str = Field(..., description="Type entité")
    description: Optional[str] = Field(None, description="Description")
    source_candidates: List[str] = Field(..., description="Candidates sources")
    candidate_count: int = Field(..., description="Nombre candidates")
    operation: str = Field(..., description="Type opération (create_new)")
    idempotency_key: Optional[str] = Field(None, description="Clé idempotence")
    user_id: Optional[str] = Field(None, description="Utilisateur")
    version_metadata: Dict[str, Any] = Field(..., description="Metadata versioning")
    executed_at: str = Field(..., description="Timestamp exécution")
    status: str = Field(..., description="Statut (created, failed)")
    result_hash: str = Field(..., description="Hash déterministe résultat")
