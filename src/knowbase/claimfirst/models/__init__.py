# src/knowbase/claimfirst/models/__init__.py
"""
Modèles Claim-First Pipeline.

Exporte tous les modèles du pipeline claim-first.

INV-8: DocumentContext porte le scope (pas Claim.scope)
INV-9: SubjectAnchor avec aliases typés pour résolution conservative
INV-12/14/25/26: Applicability Axis pour questions temporelles
"""

from knowbase.claimfirst.models.claim import (
    Claim,
    ClaimType,
    ClaimScope,  # Gardé pour compatibilité, mais DEPRECATED (INV-8)
)
from knowbase.claimfirst.models.entity import (
    Entity,
    EntityType,
    ENTITY_STOPLIST,
    is_valid_entity_name,
)
from knowbase.claimfirst.models.facet import (
    Facet,
    FacetKind,
)
from knowbase.claimfirst.models.passage import (
    Passage,
)
from knowbase.claimfirst.models.result import (
    ClaimFirstResult,
    ClaimCluster,
    ClaimRelation,
    RelationType,
)
from knowbase.claimfirst.models.subject_anchor import (
    SubjectAnchor,
    AliasSource,
    is_valid_subject_name,
)
from knowbase.claimfirst.models.document_context import (
    DocumentContext,
    ResolutionStatus,
    BOOTSTRAP_QUALIFIERS,
    extract_bootstrap_qualifiers,
)
# Applicability Axis (INV-12, INV-14, INV-25, INV-26)
from knowbase.claimfirst.models.applicability_axis import (
    ApplicabilityAxis,
    OrderType,
    OrderingConfidence,
    NEUTRAL_AXIS_KEYS,
)
from knowbase.claimfirst.models.axis_value import (
    AxisValue,
    AxisValueType,
    EvidenceSpan,
)
from knowbase.claimfirst.models.context_comparability import (
    ComparabilityResult,
    ComparabilityStatus,
    ContextOrdering,
    DocumentAuthority,
    LatestSelectionCriteria,
    LatestSelectionResult,
    TieBreakingStrategy,
)
# ComparableSubject (pivot de comparaison inter-docs)
from knowbase.claimfirst.models.comparable_subject import (
    ComparableSubject,
)
# SubjectResolver v2 output models
from knowbase.claimfirst.models.subject_resolver_output import (
    DiscriminatingRole,
    CandidateClass,
    EvidenceSource,
    EvidenceSpanOutput,
    SupportEvidence,
    ComparableSubjectOutput,
    AxisValueOutput,
    DocTypeOutput,
    ClassifiedCandidate,
    AbstainInfo,
    SubjectResolverOutput,
)

__all__ = [
    # Claim
    "Claim",
    "ClaimType",
    "ClaimScope",  # DEPRECATED - use DocumentContext
    # Entity
    "Entity",
    "EntityType",
    "ENTITY_STOPLIST",
    "is_valid_entity_name",
    # Facet
    "Facet",
    "FacetKind",
    # Passage
    "Passage",
    # Result
    "ClaimFirstResult",
    "ClaimCluster",
    "ClaimRelation",
    "RelationType",
    # INV-9: Subject Resolution
    "SubjectAnchor",
    "AliasSource",
    "is_valid_subject_name",
    # INV-8: Document Context
    "DocumentContext",
    "ResolutionStatus",
    "BOOTSTRAP_QUALIFIERS",
    "extract_bootstrap_qualifiers",
    # Applicability Axis (INV-12, INV-14, INV-25, INV-26)
    "ApplicabilityAxis",
    "OrderType",
    "OrderingConfidence",
    "NEUTRAL_AXIS_KEYS",
    "AxisValue",
    "AxisValueType",
    "EvidenceSpan",
    "ComparabilityResult",
    "ComparabilityStatus",
    "ContextOrdering",
    "DocumentAuthority",
    "LatestSelectionCriteria",
    "LatestSelectionResult",
    "TieBreakingStrategy",
    # ComparableSubject (pivot de comparaison)
    "ComparableSubject",
    # SubjectResolver v2 output
    "DiscriminatingRole",
    "CandidateClass",
    "EvidenceSource",
    "EvidenceSpanOutput",
    "SupportEvidence",
    "ComparableSubjectOutput",
    "AxisValueOutput",
    "DocTypeOutput",
    "ClassifiedCandidate",
    "AbstainInfo",
    "SubjectResolverOutput",
]
