"""
OSMOSE Pipeline V2.2 - Modèles de données
==========================================
Dataclasses pour le pipeline Extract-then-Structure.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import numpy as np


@dataclass
class ZonedAssertion:
    """
    Assertion brute avec zone_id (sortie de Pass 1.A).

    Enrichie d'un embedding_index pour le clustering sans duplication mémoire.
    """

    assertion_id: str
    text: str
    type: str  # AssertionType value
    chunk_id: str
    zone_id: str  # Zone d'origine
    section_id: Optional[str] = None
    page_no: Optional[int] = None
    confidence: float = 0.8
    embedding_index: int = -1  # Index dans le tableau numpy d'embeddings


@dataclass
class AssertionCluster:
    """
    Cluster d'assertions (sortie de Pass 1.B).

    Représente un groupe d'assertions sémantiquement proches dans une ou
    plusieurs zones. Le nommage est effectué a posteriori en Pass 1.C.
    """

    cluster_id: str
    zone_ids: List[str] = field(default_factory=list)  # 1 si intra-zone, 2+ si fusionné
    assertion_indices: List[int] = field(default_factory=list)  # Indices dans la liste d'assertions
    support_count: int = 0  # = len(assertion_indices)
    centroid: Optional[np.ndarray] = None  # Centroïde pour fusion inter-zones
    intra_similarity: float = 0.0  # Cohésion interne (mean cosine assertion↔centroid)

    # Remplis en Pass 1.C
    concept_name: Optional[str] = None
    definition: Optional[str] = None
    theme_id: Optional[str] = None
    role: str = "STANDARD"
    keywords: List[str] = field(default_factory=list)  # Mots-clés extraits des assertions
    variants: List[str] = field(default_factory=list)  # Alias/variantes du concept


class ConceptStatus(str, Enum):
    """Statut d'un concept dans le KG."""

    ACTIVE = "ACTIVE"      # Dans le KG (support >= 3, purity ok, dans budget)
    DRAFT = "DRAFT"        # Valide mais hors budget
    UNLINKED = "UNLINKED"  # Assertion sans cluster suffisant
