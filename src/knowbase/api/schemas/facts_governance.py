"""
Schémas Pydantic pour Facts Gouvernées - Phase 3
Gestion du cycle de vie des faits avec validation humaine et détection de conflits
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class FactStatus(str, Enum):
    """Statuts du cycle de vie d'un fait"""
    PROPOSED = "proposed"      # Créé automatiquement, en attente validation
    APPROVED = "approved"      # Validé par un expert
    REJECTED = "rejected"      # Rejeté par un expert
    CONFLICTED = "conflicted"  # En conflit avec un fait existant


class ConflictType(str, Enum):
    """Types de conflits détectés"""
    VALUE_MISMATCH = "value_mismatch"        # Valeur différente pour même sujet/prédicat
    TEMPORAL_OVERLAP = "temporal_overlap"    # Périodes de validité qui se chevauchent
    CONTRADICTION = "contradiction"          # Contradiction logique
    DUPLICATE = "duplicate"                  # Fait identique existant


class FactBase(BaseModel):
    """Schéma de base pour un fait"""
    subject: str = Field(..., description="Sujet du fait (entité source)")
    predicate: str = Field(..., description="Prédicat/relation du fait")
    object: str = Field(..., description="Objet du fait (entité cible ou valeur)")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Niveau de confiance")
    source: Optional[str] = Field(None, description="Source du fait (document, URL, etc.)")
    tags: List[str] = Field(default_factory=list, description="Tags pour catégorisation")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées enrichies")


class FactCreate(FactBase):
    """Schéma pour création d'un fait"""
    valid_from: Optional[datetime] = Field(None, description="Début période de validité")
    valid_until: Optional[datetime] = Field(None, description="Fin période de validité")
    created_by: Optional[str] = Field(None, description="Utilisateur créateur")


class FactUpdate(BaseModel):
    """Schéma pour mise à jour d'un fait"""
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    source: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class FactResponse(FactBase):
    """Schéma de réponse pour un fait"""
    uuid: str = Field(..., description="Identifiant unique du fait")
    status: FactStatus = Field(..., description="Statut du fait")
    created_at: datetime = Field(..., description="Date de création")
    created_by: Optional[str] = Field(None, description="Utilisateur créateur")
    approved_by: Optional[str] = Field(None, description="Utilisateur validateur")
    approved_at: Optional[datetime] = Field(None, description="Date d'approbation")
    rejected_by: Optional[str] = Field(None, description="Utilisateur rejet")
    rejected_at: Optional[datetime] = Field(None, description="Date de rejet")
    rejection_reason: Optional[str] = Field(None, description="Motif du rejet")
    valid_from: Optional[datetime] = Field(None, description="Début validité")
    valid_until: Optional[datetime] = Field(None, description="Fin validité")
    version: int = Field(default=1, description="Numéro de version")
    group_id: str = Field(..., description="Groupe multi-tenant")

    class Config:
        json_schema_extra = {
            "example": {
                "uuid": "fact_123",
                "subject": "SAP S/4HANA",
                "predicate": "supports",
                "object": "Real-time Analytics",
                "confidence": 0.95,
                "status": "approved",
                "created_at": "2025-09-29T10:00:00Z",
                "created_by": "user_expert_1",
                "approved_by": "user_admin_1",
                "approved_at": "2025-09-29T10:15:00Z",
                "group_id": "corporate"
            }
        }


class ConflictDetail(BaseModel):
    """Détails d'un conflit détecté"""
    conflict_type: ConflictType = Field(..., description="Type de conflit")
    existing_fact: FactResponse = Field(..., description="Fait existant en conflit")
    proposed_fact: FactCreate = Field(..., description="Fait proposé")
    description: str = Field(..., description="Description du conflit")
    severity: str = Field(..., description="Sévérité (low/medium/high)")
    resolution_suggestions: List[str] = Field(default_factory=list, description="Suggestions résolution")


class FactApprovalRequest(BaseModel):
    """Requête d'approbation d'un fait"""
    approver_id: str = Field(..., description="Identifiant du validateur")
    comment: Optional[str] = Field(None, description="Commentaire d'approbation")


class FactRejectionRequest(BaseModel):
    """Requête de rejet d'un fait"""
    rejector_id: str = Field(..., description="Identifiant du rejeteur")
    reason: str = Field(..., description="Motif du rejet")
    comment: Optional[str] = Field(None, description="Commentaire additionnel")


class FactFilters(BaseModel):
    """Filtres pour recherche de faits"""
    status: Optional[FactStatus] = None
    created_by: Optional[str] = None
    subject: Optional[str] = None
    predicate: Optional[str] = None
    tags: Optional[List[str]] = None
    valid_at: Optional[datetime] = None  # Filtrer les faits valides à une date donnée
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class FactTimelineEntry(BaseModel):
    """Entrée dans la timeline temporelle d'un fait"""
    fact: FactResponse = Field(..., description="Fait à cette version")
    action: str = Field(..., description="Action effectuée (created/approved/rejected/updated)")
    performed_by: str = Field(..., description="Utilisateur ayant effectué l'action")
    performed_at: datetime = Field(..., description="Date de l'action")
    comment: Optional[str] = Field(None, description="Commentaire associé")


class FactTimelineResponse(BaseModel):
    """Réponse avec historique temporel complet d'une entité"""
    entity_id: str = Field(..., description="Identifiant de l'entité")
    timeline: List[FactTimelineEntry] = Field(..., description="Historique chronologique")
    total_versions: int = Field(..., description="Nombre total de versions")
    current_version: Optional[FactResponse] = Field(None, description="Version actuelle")


class FactsListResponse(BaseModel):
    """Réponse listage de faits"""
    facts: List[FactResponse] = Field(..., description="Liste des faits")
    total: int = Field(..., description="Nombre total de faits")
    limit: int = Field(..., description="Limite appliquée")
    offset: int = Field(..., description="Offset appliqué")
    has_more: bool = Field(..., description="Indique s'il y a plus de résultats")


class ConflictsListResponse(BaseModel):
    """Réponse listage de conflits"""
    conflicts: List[ConflictDetail] = Field(..., description="Liste des conflits")
    total: int = Field(..., description="Nombre total de conflits")
    unresolved_count: int = Field(..., description="Nombre de conflits non résolus")


class FactStats(BaseModel):
    """Statistiques sur les faits"""
    total_facts: int = Field(..., description="Nombre total de faits")
    by_status: Dict[str, int] = Field(..., description="Répartition par statut")
    pending_approval: int = Field(..., description="Faits en attente de validation")
    conflicts_count: int = Field(..., description="Nombre de conflits actifs")
    avg_approval_time_hours: Optional[float] = Field(None, description="Temps moyen d'approbation")
    top_contributors: List[Dict[str, Any]] = Field(default_factory=list, description="Contributeurs principaux")
    group_id: str = Field(..., description="Groupe multi-tenant")