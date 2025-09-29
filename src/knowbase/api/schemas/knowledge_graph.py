"""
Schémas Pydantic pour Knowledge Graph Enterprise
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Types d'entités dans le knowledge graph enterprise"""
    DOCUMENT = "document"
    CONCEPT = "concept"
    SOLUTION = "solution"
    FEATURE = "feature"
    PROCESS = "process"
    PERSON = "person"
    ORGANIZATION = "organization"
    PRODUCT = "product"


class RelationType(str, Enum):
    """Types de relations dans le knowledge graph enterprise"""
    CONTAINS = "contains"
    RELATES_TO = "relates_to"
    DEPENDS_ON = "depends_on"
    IMPLEMENTS = "implements"
    SUPPORTS = "supports"
    CREATED_BY = "created_by"
    PART_OF = "part_of"
    SIMILAR_TO = "similar_to"
    REFERENCES = "references"


class EntityBase(BaseModel):
    """Entité de base du knowledge graph"""
    name: str = Field(..., description="Nom de l'entité")
    entity_type: EntityType = Field(..., description="Type de l'entité")
    description: Optional[str] = Field(None, description="Description de l'entité")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Attributs additionnels")


class EntityCreate(EntityBase):
    """Schéma pour création d'entité"""
    pass


class EntityResponse(EntityBase):
    """Réponse entité avec métadonnées"""
    uuid: str = Field(..., description="Identifiant unique de l'entité")
    created_at: datetime = Field(..., description="Date de création")
    group_id: str = Field(..., description="Groupe propriétaire")


class RelationBase(BaseModel):
    """Relation de base du knowledge graph"""
    source_entity_id: str = Field(..., description="ID de l'entité source")
    target_entity_id: str = Field(..., description="ID de l'entité cible")
    relation_type: RelationType = Field(..., description="Type de relation")
    description: Optional[str] = Field(None, description="Description de la relation")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confiance dans la relation")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Attributs additionnels")


class RelationCreate(RelationBase):
    """Schéma pour création de relation"""
    pass


class RelationResponse(RelationBase):
    """Réponse relation avec métadonnées"""
    uuid: str = Field(..., description="Identifiant unique de la relation")
    created_at: datetime = Field(..., description="Date de création")
    group_id: str = Field(..., description="Groupe propriétaire")


class SubgraphRequest(BaseModel):
    """Requête pour récupérer un sous-graphe"""
    entity_id: str = Field(..., description="ID de l'entité centrale")
    depth: int = Field(default=2, ge=1, le=5, description="Profondeur d'exploration")
    entity_types: Optional[List[EntityType]] = Field(None, description="Types d'entités à inclure")
    relation_types: Optional[List[RelationType]] = Field(None, description="Types de relations à inclure")


class GraphNode(BaseModel):
    """Noeud dans un graphe"""
    uuid: str = Field(..., description="Identifiant unique")
    name: str = Field(..., description="Nom du noeud")
    entity_type: EntityType = Field(..., description="Type d'entité")
    description: Optional[str] = Field(None, description="Description")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Attributs")


class GraphEdge(BaseModel):
    """Arête dans un graphe"""
    uuid: str = Field(..., description="Identifiant unique")
    source_id: str = Field(..., description="ID du noeud source")
    target_id: str = Field(..., description="ID du noeud cible")
    relation_type: RelationType = Field(..., description="Type de relation")
    description: Optional[str] = Field(None, description="Description")
    confidence: float = Field(..., description="Confiance")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Attributs")


class SubgraphResponse(BaseModel):
    """Réponse sous-graphe structuré"""
    central_entity: GraphNode = Field(..., description="Entité centrale")
    nodes: List[GraphNode] = Field(..., description="Noeuds du sous-graphe")
    edges: List[GraphEdge] = Field(..., description="Arêtes du sous-graphe")
    depth_reached: int = Field(..., description="Profondeur atteinte")
    total_nodes: int = Field(..., description="Nombre total de noeuds")
    total_edges: int = Field(..., description="Nombre total d'arêtes")


class KnowledgeGraphStats(BaseModel):
    """Statistiques du knowledge graph"""
    total_entities: int = Field(..., description="Nombre total d'entités")
    total_relations: int = Field(..., description="Nombre total de relations")
    entity_types_count: Dict[str, int] = Field(..., description="Répartition par type d'entité")
    relation_types_count: Dict[str, int] = Field(..., description="Répartition par type de relation")
    group_id: str = Field(..., description="Groupe concerné")