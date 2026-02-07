# src/knowbase/claimfirst/models/result.py
"""
Modèles de résultats pour le pipeline Claim-First.

ClaimFirstResult: Résultat complet du pipeline
ClaimCluster: Agrégation inter-documents
ClaimRelation: Relations entre claims (CONTRADICTS, REFINES, QUALIFIES)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.entity import Entity
from knowbase.claimfirst.models.facet import Facet
from knowbase.claimfirst.models.passage import Passage
from knowbase.claimfirst.models.document_context import DocumentContext
from knowbase.claimfirst.models.subject_anchor import SubjectAnchor
from knowbase.claimfirst.models.applicability_axis import ApplicabilityAxis
from knowbase.claimfirst.models.comparable_subject import ComparableSubject



class RelationType(str, Enum):
    """Types de relations entre claims."""

    CONTRADICTS = "CONTRADICTS"
    """Les claims sont incompatibles (assertion vs négation)."""

    REFINES = "REFINES"
    """La claim A précise/détaille la claim B."""

    QUALIFIES = "QUALIFIES"
    """La claim A conditionne/nuance la claim B."""

    CHAINS_TO = "CHAINS_TO"
    """La claim A chaîne vers la claim B via un join S/P/O (object_A == subject_B)."""


class ClaimRelation(BaseModel):
    """
    Relation entre deux Claims.

    Utilisé pour exprimer des liens sémantiques entre claims:
    - CONTRADICTS: incompatibilité
    - REFINES: précision/détail
    - QUALIFIES: condition/nuance

    INV-6: Règle d'abstention stricte.
    Si pas sûr → pas de lien.
    Faux positifs en contradiction détruisent la confiance.
    """

    source_claim_id: str = Field(
        ...,
        description="ID de la claim source"
    )

    target_claim_id: str = Field(
        ...,
        description="ID de la claim cible"
    )

    relation_type: RelationType = Field(
        ...,
        description="Type de relation"
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Score de confiance [0-1]"
    )

    basis: Optional[str] = Field(
        default=None,
        description="Justification de la relation (pour CONTRADICTS)"
    )

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour la relation Neo4j."""
        return {
            "confidence": self.confidence,
            "basis": self.basis,
            "relation_type": self.relation_type.value,
        }


class ClaimCluster(BaseModel):
    """
    Cluster d'agrégation inter-documents.

    INV-3: L'agrégation inter-documents passe exclusivement par ClaimCluster.
    Le cluster exprime "ces claims de différents docs disent la même chose".

    INV-6: Clustering conservateur en 2 étages.
    - Étage 1: Candidats par embeddings (seuil 0.85)
    - Étage 2: Validation stricte avant merge

    Règle d'abstention: Si doute → PAS de cluster.
    Mieux trop de clusters que des clusters faux.
    """

    cluster_id: str = Field(
        ...,
        description="Identifiant unique du cluster"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    canonical_label: str = Field(
        ...,
        description="Label représentatif du cluster"
    )

    claim_ids: List[str] = Field(
        default_factory=list,
        description="IDs des claims membres"
    )

    doc_ids: List[str] = Field(
        default_factory=list,
        description="Documents représentés dans le cluster"
    )

    # Métriques du cluster
    claim_count: int = Field(
        default=0,
        ge=0,
        description="Nombre de claims dans le cluster"
    )

    doc_count: int = Field(
        default=0,
        ge=0,
        description="Nombre de documents représentés"
    )

    avg_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confiance moyenne des claims"
    )

    # Facettes dominantes
    dominant_facet_ids: List[str] = Field(
        default_factory=list,
        description="Facettes les plus représentées"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de création"
    )

    def model_post_init(self, __context) -> None:
        """Calcule les métriques à partir des listes si non fournies."""
        if self.claim_ids and self.claim_count == 0:
            object.__setattr__(self, "claim_count", len(self.claim_ids))
        if self.doc_ids and self.doc_count == 0:
            object.__setattr__(self, "doc_count", len(self.doc_ids))

    def add_claim(self, claim: Claim) -> None:
        """
        Ajoute une claim au cluster.

        Met à jour les statistiques du cluster.
        """
        if claim.claim_id not in self.claim_ids:
            self.claim_ids.append(claim.claim_id)
            self.claim_count = len(self.claim_ids)

            if claim.doc_id not in self.doc_ids:
                self.doc_ids.append(claim.doc_id)
                self.doc_count = len(self.doc_ids)

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        return {
            "cluster_id": self.cluster_id,
            "tenant_id": self.tenant_id,
            "canonical_label": self.canonical_label,
            "claim_ids": self.claim_ids,
            "doc_ids": self.doc_ids,
            "claim_count": self.claim_count,
            "doc_count": self.doc_count,
            "avg_confidence": self.avg_confidence,
            "dominant_facet_ids": self.dominant_facet_ids if self.dominant_facet_ids else None,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "ClaimCluster":
        """Construit un ClaimCluster depuis un record Neo4j."""
        return cls(
            cluster_id=record["cluster_id"],
            tenant_id=record["tenant_id"],
            canonical_label=record["canonical_label"],
            claim_ids=record.get("claim_ids") or [],
            doc_ids=record.get("doc_ids") or [],
            claim_count=record.get("claim_count", 0),
            doc_count=record.get("doc_count", 0),
            avg_confidence=record.get("avg_confidence", 0.0),
            dominant_facet_ids=record.get("dominant_facet_ids") or [],
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at")
            else datetime.utcnow(),
        )


class ClaimFirstResult(BaseModel):
    """
    Résultat complet du pipeline Claim-First.

    Contient tous les artefacts extraits d'un document:
    - Passages (contextes)
    - Claims (assertions documentées)
    - Entities (ancres de navigation)
    - Facets (axes de navigation)
    - Clusters (agrégation inter-docs)
    - Relations (liens entre claims)
    - Liens (passage→claim, claim→entity, claim→facet)
    """

    # Identifiants
    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    doc_id: str = Field(
        ...,
        description="Document traité"
    )

    # Contexte documentaire (INV-8: Applicability over Truth)
    doc_context: Optional[DocumentContext] = Field(
        default=None,
        description="Contexte d'applicabilité du document (sujets, qualificateurs)"
    )

    # Sujet comparable principal (INV-25: Domain-Agnostic)
    comparable_subject: Optional[ComparableSubject] = Field(
        default=None,
        description="Sujet stable comparable entre documents (pivot de comparaison)"
    )

    # Sujets résolus (INV-9: Conservative Subject Resolution) - topics secondaires
    subject_anchors: List[SubjectAnchor] = Field(
        default_factory=list,
        description="SubjectAnchors créés ou mis à jour pour ce document (topics secondaires)"
    )

    # Axes d'applicabilité détectés (INV-12, INV-14, INV-25)
    detected_axes: List[ApplicabilityAxis] = Field(
        default_factory=list,
        description="ApplicabilityAxis détectés pour ce document"
    )

    # Frame d'applicabilité evidence-locked (remplace l'ancien AxisDetector)
    applicability_frame: Optional[Any] = Field(
        default=None,
        description="ApplicabilityFrame evidence-locked (Layer A→B→C→D)"
    )

    # Artefacts extraits
    passages: List[Passage] = Field(
        default_factory=list,
        description="Passages (contextes)"
    )

    claims: List[Claim] = Field(
        default_factory=list,
        description="Claims extraites"
    )

    entities: List[Entity] = Field(
        default_factory=list,
        description="Entités extraites"
    )

    facets: List[Facet] = Field(
        default_factory=list,
        description="Facettes matchées"
    )

    clusters: List[ClaimCluster] = Field(
        default_factory=list,
        description="Clusters créés/mis à jour"
    )

    relations: List[ClaimRelation] = Field(
        default_factory=list,
        description="Relations entre claims"
    )

    # Liens (source_id, target_id)
    claim_passage_links: List[Tuple[str, str]] = Field(
        default_factory=list,
        description="Liens Claim → Passage (SUPPORTED_BY)"
    )

    claim_entity_links: List[Tuple[str, str]] = Field(
        default_factory=list,
        description="Liens Claim → Entity (ABOUT)"
    )

    claim_facet_links: List[Tuple[str, str]] = Field(
        default_factory=list,
        description="Liens Claim → Facet (HAS_FACET)"
    )

    claim_cluster_links: List[Tuple[str, str]] = Field(
        default_factory=list,
        description="Liens Claim → Cluster (IN_CLUSTER)"
    )

    # Statistiques
    processing_time_ms: int = Field(
        default=0,
        ge=0,
        description="Temps de traitement en ms"
    )

    llm_calls: int = Field(
        default=0,
        ge=0,
        description="Nombre d'appels LLM"
    )

    llm_tokens_used: int = Field(
        default=0,
        ge=0,
        description="Tokens LLM consommés"
    )

    qdrant_points_upserted: int = Field(
        default=0,
        ge=0,
        description="Nombre de points persistés dans Qdrant Layer R"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de traitement"
    )

    # Indexation
    _passage_index: Dict[str, Passage] = {}
    _claim_index: Dict[str, Claim] = {}
    _entity_index: Dict[str, Entity] = {}

    def model_post_init(self, __context) -> None:
        """Construit les index après initialisation."""
        self._passage_index = {p.passage_id: p for p in self.passages}
        self._claim_index = {c.claim_id: c for c in self.claims}
        self._entity_index = {e.entity_id: e for e in self.entities}

    @property
    def passage_count(self) -> int:
        """Nombre de passages."""
        return len(self.passages)

    @property
    def claim_count(self) -> int:
        """Nombre de claims."""
        return len(self.claims)

    @property
    def entity_count(self) -> int:
        """Nombre d'entités."""
        return len(self.entities)

    @property
    def facet_count(self) -> int:
        """Nombre de facettes."""
        return len(self.facets)

    @property
    def cluster_count(self) -> int:
        """Nombre de clusters."""
        return len(self.clusters)

    @property
    def relation_count(self) -> int:
        """Nombre de relations."""
        return len(self.relations)

    @property
    def subject_anchor_count(self) -> int:
        """Nombre de sujets résolus."""
        return len(self.subject_anchors)

    @property
    def detected_axes_count(self) -> int:
        """Nombre d'axes d'applicabilité détectés."""
        return len(self.detected_axes)

    def get_passage(self, passage_id: str) -> Optional[Passage]:
        """Récupère un passage par son ID."""
        return self._passage_index.get(passage_id)

    def get_claim(self, claim_id: str) -> Optional[Claim]:
        """Récupère une claim par son ID."""
        return self._claim_index.get(claim_id)

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Récupère une entité par son ID."""
        return self._entity_index.get(entity_id)

    def get_claims_for_passage(self, passage_id: str) -> List[Claim]:
        """Récupère les claims liées à un passage."""
        claim_ids = [cid for cid, pid in self.claim_passage_links if pid == passage_id]
        return [c for c in self.claims if c.claim_id in claim_ids]

    def get_entities_for_claim(self, claim_id: str) -> List[Entity]:
        """Récupère les entités liées à une claim."""
        entity_ids = [eid for cid, eid in self.claim_entity_links if cid == claim_id]
        return [e for e in self.entities if e.entity_id in entity_ids]

    def get_facets_for_claim(self, claim_id: str) -> List[Facet]:
        """Récupère les facettes liées à une claim."""
        facet_ids = [fid for cid, fid in self.claim_facet_links if cid == claim_id]
        return [f for f in self.facets if f.facet_id in facet_ids]

    def to_summary(self) -> dict:
        """Génère un résumé du résultat."""
        summary = {
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "counts": {
                "passages": self.passage_count,
                "claims": self.claim_count,
                "entities": self.entity_count,
                "facets": self.facet_count,
                "clusters": self.cluster_count,
                "relations": self.relation_count,
                "subject_anchors": self.subject_anchor_count,
                "detected_axes": self.detected_axes_count,
            },
            "links": {
                "claim_passage": len(self.claim_passage_links),
                "claim_entity": len(self.claim_entity_links),
                "claim_facet": len(self.claim_facet_links),
                "claim_cluster": len(self.claim_cluster_links),
            },
            "processing": {
                "time_ms": self.processing_time_ms,
                "llm_calls": self.llm_calls,
                "llm_tokens": self.llm_tokens_used,
            },
            "created_at": self.created_at.isoformat(),
        }

        # Ajouter le sujet comparable (INV-25)
        if self.comparable_subject:
            summary["comparable_subject"] = {
                "subject_id": self.comparable_subject.subject_id,
                "canonical_name": self.comparable_subject.canonical_name,
                "aliases": self.comparable_subject.aliases,
                "confidence": self.comparable_subject.confidence,
            }

        # Ajouter le contexte documentaire (INV-8)
        if self.doc_context:
            summary["doc_context"] = {
                "raw_subjects": self.doc_context.raw_subjects,
                "resolved_subjects": self.doc_context.subject_ids,
                "qualifiers": self.doc_context.qualifiers,
                "document_type": self.doc_context.document_type,
                "temporal_scope": self.doc_context.temporal_scope,
                "resolution_status": self.doc_context.resolution_status.value,
                "resolution_confidence": self.doc_context.resolution_confidence,
                # Applicability Axis (INV-25, INV-26)
                "applicable_axes": self.doc_context.applicable_axes,
            }

        # Ajouter les axes détectés (INV-12, INV-14, INV-25)
        if self.detected_axes:
            summary["detected_axes"] = [
                {
                    "axis_key": axis.axis_key,
                    "axis_display_name": axis.axis_display_name,
                    "is_orderable": axis.is_orderable,
                    "ordering_confidence": axis.ordering_confidence.value,
                    "known_values": axis.known_values,
                    "is_validated_claimkey": axis.is_validated_claimkey(),
                }
                for axis in self.detected_axes
            ]

        # Ajouter le frame d'applicabilité (evidence-locked)
        if self.applicability_frame and hasattr(self.applicability_frame, 'to_json_dict'):
            summary["applicability_frame"] = self.applicability_frame.to_json_dict()

        return summary


__all__ = [
    "ClaimFirstResult",
    "ClaimCluster",
    "ClaimRelation",
    "RelationType",
]
