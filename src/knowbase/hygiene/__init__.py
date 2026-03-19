"""
KG Hygiene System — Nettoyage autonome du Knowledge Graph + Rollback.

2 couches:
- Layer 1: Haute précision, domain-agnostic (auto, post-ingestion)
- Layer 2: Heuristique, LLM-driven (admin, avec PROPOSED)

Invariant: N'altère jamais les preuves documentaires primaires (Claims, textes extraits).
"""
