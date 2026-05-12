"""
Types V3.3 pour le chantier contradiction-detection.

Séparé de `types.py` qui contient les RelationType métier de Phase 2
(PART_OF, REQUIRES, etc., 18 types domaine-spécifiques).

Les LogicalRelationType V3.3 sont **orthogonaux** aux RelationType métier :
- RelationType (Phase 2) : sémantique du contenu (qui dépend de quoi, qui définit quoi)
- LogicalRelationType (V3.3) : relation logique entre 2 claims (qui contredit qui,
  qui supersede qui, qui définit qui — du point de vue raisonnement formel)

Ref : doc/ongoing/CONTRADICTION_DETECTION_ARCHITECTURE.md V3.3 §3.G
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# 12 types LogicalRelation V3.3
# ============================================================================

class LogicalRelationType(str, Enum):
    """
    Typologie fermée 12-types V3.3 (cf. CONTRADICTION_DETECTION_ARCHITECTURE.md §3.C).

    Détermine la relation logique entre 2 claims sur des scopes alignés :
    - SET-LIKE (5)    : SUBSET, SUPERSET, EQUIVALENT, OVERLAP, DISJOINT
    - LOGICAL (3)     : CONFLICT, EXCEPTION, DEFINITION_OF
    - TEMPORAL (3)    : SUPERSEDES, EVOLVES_FROM, REAFFIRMS
    - DEFAULT (1)     : UNRELATED (skip persistence)
    """

    # --- Set-like (relation entre les scopes des 2 claims) ---
    SUBSET = "SUBSET"          # A est cas particulier strict de B
    SUPERSET = "SUPERSET"      # B est cas particulier strict de A
    EQUIVALENT = "EQUIVALENT"  # A et B expriment la même règle
    OVERLAP = "OVERLAP"        # A et B partagent du scope partiellement, ni l'un ni l'autre subset
    DISJOINT = "DISJOINT"      # A et B ne s'appliquent pas aux mêmes choses

    # --- Logical (relation entre les assertions) ---
    CONFLICT = "CONFLICT"           # A et B font des assertions incompatibles sur scope identique
    EXCEPTION = "EXCEPTION"         # A déroge à B sous conditions spécifiques
    DEFINITION_OF = "DEFINITION_OF" # A définit un terme utilisé dans B (ou vice-versa)

    # --- Temporal (V3.1 — relation temporelle entre versions) ---
    SUPERSEDES = "SUPERSEDES"      # A remplace B (B est validity_end avant A.validity_start)
    EVOLVES_FROM = "EVOLVES_FROM"  # A descend de B sans nécessairement le remplacer
    REAFFIRMS = "REAFFIRMS"        # A reprend explicitement la même règle que B

    # --- Default (skip persistence) ---
    UNRELATED = "UNRELATED"  # Pas de relation logique significative


class RelationStrength(str, Enum):
    """Force d'une LogicalRelation (cf. V3.3 §3.G.1)."""

    STRONG = "STRONG"        # Logique claire, peu d'ambiguïté
    WEAK = "WEAK"            # Interprétatif, dépend du contexte
    UNCERTAIN = "UNCERTAIN"  # Borderline, abstention possible


# Confidence thresholds par type (cf. V3.3 §3.G.2)
# CONFLICT plus strict que SUBSET car faux CONFLICT = pire cas produit
CONFIDENCE_THRESHOLDS: dict[LogicalRelationType, float] = {
    LogicalRelationType.CONFLICT: 0.90,       # Le plus risqué
    LogicalRelationType.EXCEPTION: 0.80,
    LogicalRelationType.SUBSET: 0.70,
    LogicalRelationType.SUPERSET: 0.70,
    LogicalRelationType.EQUIVALENT: 0.75,
    LogicalRelationType.SUPERSEDES: 0.75,
    LogicalRelationType.EVOLVES_FROM: 0.65,
    LogicalRelationType.REAFFIRMS: 0.70,
    LogicalRelationType.OVERLAP: 0.65,
    LogicalRelationType.DISJOINT: 0.60,        # Facile : scopes orthogonaux
    LogicalRelationType.DEFINITION_OF: 0.60,   # Facile : signal lexical fort
    LogicalRelationType.UNRELATED: 0.50,       # Absorption, pas confiance
}


# ============================================================================
# Scope Relation (output Gate V3.3 — relation entre 2 ApplicabilityFrame V2)
# ============================================================================

class ScopeRelation(str, Enum):
    """Alignement de scope entre 2 claims (cf. V3.3 §4 ter)."""

    SUBSET = "SUBSET"            # scope_a ⊂ scope_b
    SUPERSET = "SUPERSET"        # scope_a ⊃ scope_b
    EQUIVALENT = "EQUIVALENT"    # scope_a == scope_b
    OVERLAPPING = "OVERLAPPING"  # scope_a ∩ scope_b ≠ ∅, ni subset ni superset
    DISJOINT = "DISJOINT"        # scope_a ∩ scope_b == ∅
    UNKNOWN = "UNKNOWN"          # Pas assez d'info dans les frames pour décider


# ============================================================================
# Temporal Relation
# ============================================================================

class TemporalRelation(str, Enum):
    """Alignement temporel entre 2 claims (V3.3 §4 bis)."""

    OVERLAP = "OVERLAP"      # validity windows se chevauchent
    DISJOINT = "DISJOINT"    # validity windows non chevauchantes (a se termine avant b)
    A_BEFORE_B = "A_BEFORE_B"  # a se termine avant que b commence (cas SUPERSEDES candidate)
    B_BEFORE_A = "B_BEFORE_A"  # b se termine avant que a commence
    UNKNOWN = "UNKNOWN"      # Pas assez d'info temporelle pour décider


# ============================================================================
# Gate Decision (output Gate V3.3 — verdict avant LLM call)
# ============================================================================

class GateDecision(str, Enum):
    """
    Verdict du Gate V3.3 (cf. plan §S2.B).

    Décide si la paire candidate doit être :
    - SKIP_DISJOINT : skip (scopes disjoints, pas de relation possible)
    - LIKELY_SUPERSEDES : highly likely SUPERSEDES (scopes alignés, temporal_disjoint)
    - LIKELY_REAFFIRMS : highly likely REAFFIRMS (scopes équivalents, temporel non-disjoint)
    - FULL_LLM_CLASSIFY : paire à passer au 12-class classifier (S3)
    """

    SKIP_DISJOINT = "SKIP_DISJOINT"
    LIKELY_SUPERSEDES = "LIKELY_SUPERSEDES"
    LIKELY_REAFFIRMS = "LIKELY_REAFFIRMS"
    FULL_LLM_CLASSIFY = "FULL_LLM_CLASSIFY"


# ============================================================================
# Multi-signal score breakdown
# ============================================================================

class MultiSignalScore(BaseModel):
    """
    Score composite multi-signal pour pair selection (V3.3 §S2.A).

    Score final = 0.3·s_cos + 0.25·s_entity + 0.15·s_facet + 0.2·s_cluster + 0.1·s_graph

    Threshold tunable, démarrage à 0.55.
    """

    s_cos: float = Field(ge=0.0, le=1.0, description="Cosine similarity (Qdrant ou C4 cached)")
    s_entity: float = Field(ge=0.0, le=1.0, description="Min(1, shared_canonical_entities / 2)")
    s_facet: float = Field(ge=0.0, le=1.0, description="1 si même facet, 0 sinon")
    s_cluster: float = Field(ge=0.0, le=1.0, description="1 si même cluster, 0 sinon")
    s_graph: float = Field(ge=0.0, le=1.0, description="Max(0, 1 - graph_distance / 4) via ABOUT/MENTIONS")

    @property
    def composite(self) -> float:
        """Score composite pondéré."""
        return (
            0.30 * self.s_cos
            + 0.25 * self.s_entity
            + 0.15 * self.s_facet
            + 0.20 * self.s_cluster
            + 0.10 * self.s_graph
        )


# ============================================================================
# Logical Relation Output (sortie 12-class classifier S3)
# ============================================================================

class LogicalRelationOutput(BaseModel):
    """
    Output du 12-class LogicalRelation classifier (V3.3 §3.C).

    Persiste sur Neo4j comme :
        (a:Claim)-[:LOGICAL_RELATION {
            type, strength, confidence, reasoning,
            scope_alignment, temporal_relation,
            is_contradiction,
            evidence_quote_a, evidence_quote_b,
            extracted_by, extracted_at, derived
        }]->(b:Claim)
    """

    relation: LogicalRelationType
    strength: RelationStrength = RelationStrength.STRONG
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Reasoning structuré du LLM")

    # Inputs context (au moment de la classification)
    scope_alignment: Optional[ScopeRelation] = None
    temporal_relation: Optional[TemporalRelation] = None

    # Décision déterministe (V3.3 §3.D)
    is_contradiction: bool = Field(default=False, description="Vraie contradiction (CONFLICT + scope_overlap + confidence ≥ 0.85)")
    contradiction_reason: Optional[str] = Field(default=None, description="Justification de la décision")

    # Multi-label si ambiguïté (V3.3 §3.G.5)
    alternatives: list[dict] = Field(
        default_factory=list,
        description="Top-2 alternatives si delta < 0.15 (audit only)"
    )

    # Evidence
    evidence_quote_a: Optional[str] = None
    evidence_quote_b: Optional[str] = None

    def passes_threshold(self) -> bool:
        """True si confidence >= threshold pour ce type."""
        threshold = CONFIDENCE_THRESHOLDS.get(self.relation, 0.65)
        return self.confidence >= threshold


__all__ = [
    "LogicalRelationType",
    "RelationStrength",
    "CONFIDENCE_THRESHOLDS",
    "ScopeRelation",
    "TemporalRelation",
    "GateDecision",
    "MultiSignalScore",
    "LogicalRelationOutput",
]
