"""OSMOSIS V6 — Pipeline d'extraction structurée universelle.

Refonte ingestion-centric : extraction lourde à l'ingestion (5 archétypes
universels + concept cards) pour permettre retrieval léger au runtime.

Charte domain-agnostic stricte : tous les schémas et prompts du core sont
universels (testés sur SAP, légal, médical, aerospace). La spécialisation
par domaine passe par Domain Pack tenant-scoped (sub-classing).

Voir doc/ongoing/V6_REFONTE_INGESTION_PROPOSITION.md pour le rationale complet.
"""
