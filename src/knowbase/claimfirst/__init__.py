# src/knowbase/claimfirst/__init__.py
"""
OSMOSE Pipeline Claim-First (Pivot Epistémique)
===============================================

Pipeline de connaissance centré sur les Claims documentées.

Pivot validé: L'objet central devient la **Claim documentée** — une affirmation
synthétisée, précise, explicitement fondée sur un ou plusieurs passages verbatim.

Architecture (CHEMIN CANONIQUE - INV-8 CORRECTIF 6 + PATCH C):

    SubjectAnchor (Sujet Canonique avec aliases typés - INV-9)
    ├─ canonical_name: "SAP S/4HANA Cloud Private Edition"
    ├─ aliases_explicit: ["RISE S/4HANA PCE"] (FORT)
    ├─ aliases_inferred: ["S/4HANA Private"] (FAIBLE)
    └─ aliases_learned: [...] (MOYEN)

    Document
    ├─[:HAS_CONTEXT]─ DocumentContext (INV-8: scope appartient au doc)
    │                 ├─ raw_subjects, subject_ids
    │                 └─ qualifiers: {version: "2021", region: "EU"}
    │
    ├─[:ABOUT_SUBJECT]─ SubjectAnchor (via DocumentContext)
    │
    └─[:FROM]─ Passage (= DocItem avec verbatim, contient units U1, U2...)
               └─[:SUPPORTED_BY]─ Claim (CENTRAL, doc_id fixe, unit_ids = preuve)
                                  ├─[:ABOUT]─ Entity (ancre navigation, pas de role V1)
                                  ├─[:HAS_FACET]─ Facet (axe navigation THÉMATIQUE)
                                  ├─[:IN_CLUSTER]─ ClaimCluster (agrégation inter-docs)
                                  └─[:CONTRADICTS|REFINES|QUALIFIES]─ Claim

Invariants:
    - INV-1: Unit = preuve textuelle exacte, Passage = contexte
    - INV-2: Relations de l'objet détaillé vers l'objet englobant
    - INV-3: Claim = occurrence mono-document
    - INV-4: Entity sans rôle structurant (V1)
    - INV-5: EntityExtractor enrichi (pas juste NER)
    - INV-6: ClaimClusterer conservateur (2 étages)
    - INV-7: Suppression legacy = post-validation étendue
    - INV-8: Applicability over Truth (scope = DocumentContext, pas Claim)
    - INV-9: Conservative Subject Resolution (aliases typés, pas d'auto-fusion)
    - INV-10: Discriminants Découverts, pas Hardcodés (domain-agnostic)
"""

from knowbase.claimfirst.models import (
    # Claim
    Claim,
    ClaimType,
    ClaimScope,  # DEPRECATED - use DocumentContext
    # Entity
    Entity,
    EntityType,
    # Facet
    Facet,
    FacetKind,
    # Passage
    Passage,
    # Result
    ClaimCluster,
    ClaimRelation,
    RelationType,
    ClaimFirstResult,
    # INV-9: Subject Resolution
    SubjectAnchor,
    AliasSource,
    # INV-8: Document Context
    DocumentContext,
    ResolutionStatus,
)

__version__ = "1.1.0"  # Phase 1.5 complete

__all__ = [
    # Core models
    "Claim",
    "ClaimType",
    "ClaimScope",  # DEPRECATED
    "Entity",
    "EntityType",
    "Facet",
    "FacetKind",
    "Passage",
    "ClaimCluster",
    "ClaimRelation",
    "RelationType",
    "ClaimFirstResult",
    # INV-9: Subject Resolution
    "SubjectAnchor",
    "AliasSource",
    # INV-8: Document Context
    "DocumentContext",
    "ResolutionStatus",
]
