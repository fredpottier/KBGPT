# src/knowbase/perspectives/models.py
"""
Modeles pour la couche Perspective.

Une Perspective regroupe les claims d'un sujet autour d'un axe thematique
coherent. C'est une structure de regroupement persistee, non canonique,
revisable, subordonnee aux claims.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


@dataclass
class PerspectiveConfig:
    """Configuration du builder de Perspectives."""

    facet_weight: float = 0.5
    """Poids de la membership facet dans le clustering (0.0 = embedding-first)."""

    embedding_weight: float = 0.5
    """Poids de l'embedding semantique dans le clustering."""

    min_cluster_size: int = 3
    """Taille minimale d'un cluster pour former une Perspective."""

    target_clusters_min: int = 3
    """Nombre minimum de Perspectives cible par sujet."""

    target_clusters_max: int = 8
    """Nombre maximum de Perspectives cible par sujet."""

    max_claims_per_perspective: int = 50
    """Nombre maximum de claims stockes par Perspective (le prompt n'en injecte que 5-8)."""

    min_subject_claims: int = 10
    """Seuil minimum de claims pour qu'un sujet soit eligible."""

    cosine_merge_threshold: float = 0.4
    """Seuil cosine distance en-dessous duquel deux clusters sont fusionnes."""


class Perspective(BaseModel):
    """
    Perspective — regroupement thematique de claims pour un sujet.

    C'est une brique d'assemblage, pas une section finale de reponse.
    Le LLM de synthese est libre de recomposer les Perspectives selon la question.
    """

    perspective_id: str = Field(
        ..., description="Identifiant unique de la Perspective"
    )
    tenant_id: str = Field(
        ..., description="Identifiant du tenant"
    )
    subject_id: str = Field(
        ..., description="ID du SubjectAnchor ou ComparableSubject parent"
    )
    subject_name: str = Field(
        default="", description="Nom canonique du sujet parent (denormalise pour affichage)"
    )

    # Label et description (decouverts par LLM, domain-agnostic)
    label: str = Field(
        ..., description="Label thematique (ex: 'Security & Authentication')"
    )
    description: str = Field(
        default="", description="Description 1-2 phrases"
    )
    negative_boundary: str = Field(
        default="", description="Ce que cette Perspective n'est PAS"
    )
    keywords: List[str] = Field(
        default_factory=list, description="5-8 mots-cles pour matching"
    )

    # Metriques
    claim_count: int = Field(default=0, ge=0, description="Nombre de claims dans cette Perspective")
    doc_count: int = Field(default=0, ge=0, description="Documents sources distincts")
    tension_count: int = Field(default=0, ge=0, description="Tensions internes (CONTRADICTS/REFINES)")
    coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="% des claims du sujet couverts")
    importance_score: float = Field(default=0.0, ge=0.0, description="Score d'importance composite")

    # Facets sources
    source_facet_ids: List[str] = Field(
        default_factory=list, description="Facets regroupees dans cette Perspective"
    )

    # Claims representatifs (pour scoring rapide + prompt)
    representative_claim_ids: List[str] = Field(
        default_factory=list, description="Top 5-8 claims les plus importants"
    )
    representative_texts: List[str] = Field(
        default_factory=list, description="Textes des claims representatifs"
    )

    # Embedding (pour scoring vs question)
    embedding: Optional[List[float]] = Field(
        default=None, description="Embedding composite (25% label + 75% claims centroid)"
    )

    # Evolution cross-version (Phase 1B — declares mais vides pour l'instant)
    evolution_summary: str = Field(default="", description="Resume de l'evolution vs version precedente")
    added_claim_count: int = Field(default=0, ge=0)
    removed_claim_count: int = Field(default=0, ge=0)
    changed_claim_count: int = Field(default=0, ge=0)

    # Metadata
    build_method: str = Field(default="facet_clustering", description="Methode de construction")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en proprietes pour Neo4j."""
        props = {
            "perspective_id": self.perspective_id,
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "label": self.label,
            "description": self.description,
            "negative_boundary": self.negative_boundary,
            "keywords": self.keywords if self.keywords else None,
            "claim_count": self.claim_count,
            "doc_count": self.doc_count,
            "tension_count": self.tension_count,
            "coverage_ratio": self.coverage_ratio,
            "importance_score": self.importance_score,
            "source_facet_ids": self.source_facet_ids if self.source_facet_ids else None,
            "representative_claim_ids": self.representative_claim_ids if self.representative_claim_ids else None,
            "representative_texts": self.representative_texts if self.representative_texts else None,
            "build_method": self.build_method,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        # Neo4j ne supporte pas les listes de floats nativement — stocker comme string JSON
        if self.embedding:
            import json
            props["embedding_json"] = json.dumps(self.embedding)
        return {k: v for k, v in props.items() if v is not None}

    @classmethod
    def from_neo4j_record(cls, record: Dict[str, Any]) -> Perspective:
        """Construit une Perspective depuis un record Neo4j."""
        embedding = None
        if record.get("embedding_json"):
            import json
            embedding = json.loads(record["embedding_json"])

        return cls(
            perspective_id=record["perspective_id"],
            tenant_id=record["tenant_id"],
            subject_id=record["subject_id"],
            subject_name=record.get("subject_name", ""),
            label=record["label"],
            description=record.get("description", ""),
            negative_boundary=record.get("negative_boundary", ""),
            keywords=record.get("keywords") or [],
            claim_count=record.get("claim_count", 0),
            doc_count=record.get("doc_count", 0),
            tension_count=record.get("tension_count", 0),
            coverage_ratio=record.get("coverage_ratio", 0.0),
            importance_score=record.get("importance_score", 0.0),
            source_facet_ids=record.get("source_facet_ids") or [],
            representative_claim_ids=record.get("representative_claim_ids") or [],
            representative_texts=record.get("representative_texts") or [],
            embedding=embedding,
            evolution_summary=record.get("evolution_summary", ""),
            added_claim_count=record.get("added_claim_count", 0),
            removed_claim_count=record.get("removed_claim_count", 0),
            changed_claim_count=record.get("changed_claim_count", 0),
            build_method=record.get("build_method", "facet_clustering"),
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"])
            if record.get("updated_at") else datetime.utcnow(),
        )

    @classmethod
    def create_new(
        cls,
        tenant_id: str,
        subject_id: str,
        subject_name: str,
        label: str,
        description: str = "",
        negative_boundary: str = "",
        keywords: Optional[List[str]] = None,
    ) -> Perspective:
        """Factory pour creer une nouvelle Perspective."""
        name_hash = hashlib.md5(
            f"{tenant_id}:{subject_id}:{label.lower()}".encode()
        ).hexdigest()[:12]
        perspective_id = f"persp_{name_hash}"

        return cls(
            perspective_id=perspective_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            subject_name=subject_name,
            label=label,
            description=description,
            negative_boundary=negative_boundary,
            keywords=keywords or [],
        )


@dataclass
class ScoredPerspective:
    """Perspective avec son score de pertinence pour une question donnee."""

    perspective: Perspective
    relevance_score: float = 0.0
    semantic_score: float = 0.0


__all__ = ["Perspective", "PerspectiveConfig", "ScoredPerspective"]
