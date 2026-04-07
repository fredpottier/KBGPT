# src/knowbase/perspectives/models.py
"""
Modeles pour la couche Perspective (theme-scoped V2).

Une Perspective est un cluster thematique transversal du corpus :
elle regroupe des claims qui partagent le meme axe semantique,
INDEPENDAMMENT de leur sujet (ComparableSubject) parent.

Les sujets touches sont une METADONNEE calculee (linked_subject_ids),
pas un facteur de regroupement. C'est la difference fondamentale avec
la V1 subject-scoped.

Construction : UMAP + HDBSCAN sur tous les claims du tenant, sans
hardcoding de mots-cles ou de domaines.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


@dataclass
class PerspectiveConfig:
    """Configuration du builder de Perspectives theme-scoped (V2)."""

    # Parametres clustering
    umap_n_components: int = 15
    """Nombre de dimensions cibles pour la reduction UMAP."""

    umap_n_neighbors: int = 30
    """Nombre de voisins UMAP."""

    umap_min_dist: float = 0.0
    """Distance minimale UMAP."""

    hdbscan_min_cluster_size: int = 30
    """Taille minimale d'un cluster HDBSCAN pour former une Perspective."""

    hdbscan_min_samples: int = 5
    """Min samples HDBSCAN (densite locale requise)."""

    # Parametres labellisation et persistence
    max_clusters_to_label: int = 60
    """Nombre maximum de clusters a labelliser via LLM (limite cout)."""

    max_claims_per_perspective: int = 50
    """Nombre maximum de claims stockes par Perspective."""

    n_representative_claims: int = 8
    """Nombre de claims representatifs gardes pour le prompt."""

    # Parametres qualite
    min_doc_count: int = 2
    """Nombre minimum de documents distincts pour qu'un cluster soit retenu."""

    drop_clusters_with_single_doc: bool = True
    """Si True, drop les clusters dont tous les claims viennent d'un seul doc."""


class Perspective(BaseModel):
    """
    Perspective theme-scoped V2.

    Cluster thematique transversal qui regroupe des claims partageant
    un axe semantique, decouvert par clustering global du corpus.
    Les sujets touches sont une metadonnee, pas un critere de regroupement.
    """

    # Identifiants
    perspective_id: str = Field(
        ..., description="Identifiant unique de la Perspective"
    )
    tenant_id: str = Field(
        ..., description="Identifiant du tenant"
    )

    # Label thematique (decouvert par LLM, domain-agnostic)
    label: str = Field(
        ..., description="Label thematique court (ex: 'Authorization Objects and Access Control')"
    )
    description: str = Field(
        default="", description="Description 1-2 phrases"
    )
    keywords: List[str] = Field(
        default_factory=list, description="5-8 mots-cles pour matching et hints"
    )

    # Sujets touches (metadonnee calculee, pas critere de regroupement)
    linked_subject_ids: List[str] = Field(
        default_factory=list,
        description="ComparableSubjects ou SubjectAnchors touches par cette Perspective"
    )
    linked_subject_names: List[str] = Field(
        default_factory=list,
        description="Noms canoniques des sujets touches (denormalise pour affichage)"
    )

    # Metriques
    claim_count: int = Field(default=0, ge=0, description="Nombre total de claims dans cette Perspective")
    doc_count: int = Field(default=0, ge=0, description="Documents sources distincts")
    tension_count: int = Field(default=0, ge=0, description="Tensions internes (CONTRADICTS/REFINES)")
    importance_score: float = Field(default=0.0, ge=0.0, description="Score d'importance composite")

    # Facets dominantes (info derivee, pas critere de regroupement)
    dominant_facet_names: List[str] = Field(
        default_factory=list, description="Top facets associees aux claims (info dérivée)"
    )

    # Claims representatifs (pour scoring rapide + injection prompt)
    representative_claim_ids: List[str] = Field(
        default_factory=list, description="Top N claims les plus importants"
    )
    representative_texts: List[str] = Field(
        default_factory=list, description="Textes des claims representatifs"
    )

    # Embedding (pour scoring semantique vs question)
    embedding: Optional[List[float]] = Field(
        default=None, description="Embedding composite (label + claims centroid)"
    )

    # Evolution cross-version (Phase 1B — declares mais vides en V2 initiale)
    evolution_summary: str = Field(default="", description="Resume de l'evolution vs version precedente")
    added_claim_count: int = Field(default=0, ge=0)
    removed_claim_count: int = Field(default=0, ge=0)
    changed_claim_count: int = Field(default=0, ge=0)

    # Tracabilite du build
    cluster_method: str = Field(
        default="umap_hdbscan",
        description="Methode de clustering utilisee"
    )
    cluster_id_in_run: int = Field(
        default=-1,
        description="ID du cluster dans le run HDBSCAN qui l'a produit (debug/repro)"
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en proprietes pour Neo4j."""
        props = {
            "perspective_id": self.perspective_id,
            "tenant_id": self.tenant_id,
            "label": self.label,
            "description": self.description,
            "keywords": self.keywords if self.keywords else None,
            "linked_subject_ids": self.linked_subject_ids if self.linked_subject_ids else None,
            "linked_subject_names": self.linked_subject_names if self.linked_subject_names else None,
            "claim_count": self.claim_count,
            "doc_count": self.doc_count,
            "tension_count": self.tension_count,
            "importance_score": self.importance_score,
            "dominant_facet_names": self.dominant_facet_names if self.dominant_facet_names else None,
            "representative_claim_ids": self.representative_claim_ids if self.representative_claim_ids else None,
            "representative_texts": self.representative_texts if self.representative_texts else None,
            "evolution_summary": self.evolution_summary or None,
            "added_claim_count": self.added_claim_count,
            "removed_claim_count": self.removed_claim_count,
            "changed_claim_count": self.changed_claim_count,
            "cluster_method": self.cluster_method,
            "cluster_id_in_run": self.cluster_id_in_run,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        # Neo4j ne supporte pas les listes de floats nativement — stocker comme JSON string
        if self.embedding:
            props["embedding_json"] = json.dumps(self.embedding)
        return {k: v for k, v in props.items() if v is not None}

    @classmethod
    def from_neo4j_record(cls, record: Dict[str, Any]) -> Perspective:
        """Construit une Perspective depuis un record Neo4j."""
        embedding = None
        if record.get("embedding_json"):
            embedding = json.loads(record["embedding_json"])

        return cls(
            perspective_id=record["perspective_id"],
            tenant_id=record["tenant_id"],
            label=record["label"],
            description=record.get("description", ""),
            keywords=record.get("keywords") or [],
            linked_subject_ids=record.get("linked_subject_ids") or [],
            linked_subject_names=record.get("linked_subject_names") or [],
            claim_count=record.get("claim_count", 0),
            doc_count=record.get("doc_count", 0),
            tension_count=record.get("tension_count", 0),
            importance_score=record.get("importance_score", 0.0),
            dominant_facet_names=record.get("dominant_facet_names") or [],
            representative_claim_ids=record.get("representative_claim_ids") or [],
            representative_texts=record.get("representative_texts") or [],
            embedding=embedding,
            evolution_summary=record.get("evolution_summary", ""),
            added_claim_count=record.get("added_claim_count", 0),
            removed_claim_count=record.get("removed_claim_count", 0),
            changed_claim_count=record.get("changed_claim_count", 0),
            cluster_method=record.get("cluster_method", "umap_hdbscan"),
            cluster_id_in_run=record.get("cluster_id_in_run", -1),
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"])
            if record.get("updated_at") else datetime.utcnow(),
        )

    @classmethod
    def create_new(
        cls,
        tenant_id: str,
        label: str,
        cluster_id_in_run: int,
        description: str = "",
        keywords: Optional[List[str]] = None,
    ) -> Perspective:
        """Factory pour creer une nouvelle Perspective theme-scoped."""
        name_hash = hashlib.md5(
            f"{tenant_id}:{label.lower()}:{cluster_id_in_run}".encode()
        ).hexdigest()[:12]
        perspective_id = f"persp_{name_hash}"

        return cls(
            perspective_id=perspective_id,
            tenant_id=tenant_id,
            label=label,
            description=description,
            keywords=keywords or [],
            cluster_id_in_run=cluster_id_in_run,
        )


@dataclass
class ScoredPerspective:
    """Perspective avec son score de pertinence pour une question donnee."""

    perspective: Perspective
    relevance_score: float = 0.0
    semantic_score: float = 0.0
    subject_overlap_bonus: float = 0.0
    """Bonus si la Perspective touche un sujet identifie dans la question."""

    # Claims re-rankes par similarite a la question (Phase B6)
    # Si renseigne, le prompt_builder utilise ces claims plutot que les
    # representative_texts figes au build time. Permet d'injecter les
    # claims VRAIMENT pertinents pour la question, pas seulement les plus
    # importants en general.
    reranked_claims: Optional[List[Dict[str, Any]]] = None
    """Claims re-rankes au runtime: [{claim_id, text, doc_id, similarity}, ...]"""


__all__ = ["Perspective", "PerspectiveConfig", "ScoredPerspective"]
