"""
FacetEngine V2 — Adressabilite Semantique Emergente.

Les facettes sont des poles de regroupement semantique servant a la navigation,
l'adressabilite et la lecture du corpus. Elles ne sont PAS des verites.

Pipeline :
  F1. Bootstrap (LLM) → FacetCandidate[]
  F2. Normalization → deduplicate/merge facettes proches
  F3. Prototype Build → embeddings composites par facette
  F4. Assignment → scoring multi-signal, STRONG/WEAK
  F5. Governance → metriques de sante, merge/split candidates

ADR: doc/ongoing/ADR_FACET_ENGINE_V2.md
"""
