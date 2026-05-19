"""V6 — Extracteurs structurés additifs au pipeline ClaimFirst.

Ces extracteurs ne remplacent pas les Claims existants : ils ajoutent
des archétypes complémentaires (Procedure, Reference, ConceptCard)
pour enrichir le KG.

Jalons V6 :
- J1 ✅ : Procedure multi-step
- J2 ✅ : Reference typée
- J3 : ConceptCard auto-générée (à venir)
- J0 : Purge + réingestion complète unifiée (final)
"""
from knowbase.claimfirst.v6.procedure_extractor import (
    ProcedureExtractor,
    extract_procedures_for_doc,
)
from knowbase.claimfirst.v6.procedure_persister import ProcedurePersister
from knowbase.claimfirst.v6.reference_extractor import (
    ReferenceExtractor,
    extract_references_for_doc,
)
from knowbase.claimfirst.v6.reference_persister import ReferencePersister
from knowbase.claimfirst.v6.schema import V6Schema, ensure_v6_schema

__all__ = [
    # V6-J1
    "ProcedureExtractor",
    "extract_procedures_for_doc",
    "ProcedurePersister",
    # V6-J2
    "ReferenceExtractor",
    "extract_references_for_doc",
    "ReferencePersister",
    # Schema
    "V6Schema",
    "ensure_v6_schema",
]
