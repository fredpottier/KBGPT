"""
FacetEngine V2 — Modeles de donnees.

Les facettes sont des surfaces d'organisation, pas des verites.
Le coeur d'une facette est son prototype composite (embedding),
pas une liste de mots-cles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class FacetCandidate:
    """Facette candidate extraite par LLM (Pass F1)."""
    label: str
    description: str
    facet_family: str = "cross_cutting_concern"
    source_doc_ids: List[str] = field(default_factory=list)
    prototype_claim_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class FacetPrototype:
    """Prototype composite d'une facette (Pass F3).

    Le vecteur composite est calcule comme :
      0.25 * label_description_vector
    + 0.50 * prototype_claims_centroid
    + 0.15 * claimkey_centroid
    + 0.10 * theme_centroid
    """
    facet_id: str
    vector: List[float] = field(default_factory=list)  # 1024d composite
    label_vector: List[float] = field(default_factory=list)
    claims_centroid: List[float] = field(default_factory=list)
    prototype_claim_ids: List[str] = field(default_factory=list)
    prototype_count: int = 0


@dataclass
class FacetAssignment:
    """Resultat de l'assignment d'une claim a une facette (Pass F4)."""
    claim_id: str
    facet_id: str
    global_score: float
    score_semantic: float
    score_theme: float = 0.0
    score_claimkey: float = 0.0
    score_structural: float = 0.0
    promotion_level: str = "WEAK"  # STRONG | WEAK
    assignment_method: str = "embedding_centroid"


@dataclass
class FacetHealth:
    """Metriques de sante d'une facette (Pass F5)."""
    facet_id: str
    info_count: int = 0
    doc_count: int = 0
    weak_ratio: float = 0.0
    strong_ratio: float = 0.0
    top_doc_concentration: float = 0.0
    cross_doc_stability: float = 0.0
    merge_candidate_with: Optional[str] = None
    split_candidate: bool = False
    drift_alert: bool = False


@dataclass
class Facet:
    """Facette V2 — pole de regroupement semantique."""
    facet_id: str
    canonical_label: str
    description: str
    facet_family: str = "cross_cutting_concern"
    status: str = "candidate"  # candidate | validated | deprecated
    promotion_level: str = "WEAK"
    prototype: Optional[FacetPrototype] = None
    health: Optional[FacetHealth] = None
    source_doc_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    extraction_method: str = "hybrid_bootstrap"

    def to_neo4j_properties(self) -> Dict:
        """Convertit en properties Neo4j."""
        props = {
            "facet_id": self.facet_id,
            "canonical_label": self.canonical_label,
            "facet_name": self.canonical_label,  # compat avec V1
            "description": self.description,
            "facet_family": self.facet_family,
            "status": self.status,
            "promotion_level": self.promotion_level,
            "extraction_method": self.extraction_method,
            "source_doc_count": len(self.source_doc_ids),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        if self.health:
            props["info_count"] = self.health.info_count
            props["doc_count"] = self.health.doc_count
            props["weak_ratio"] = self.health.weak_ratio
            props["strong_ratio"] = self.health.strong_ratio
            props["cross_doc_stability"] = self.health.cross_doc_stability
        return {k: v for k, v in props.items() if v is not None}
