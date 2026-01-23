"""
OSMOSE Pipeline V2 - Lecture Stratifiée
========================================

Pipeline de traitement documentaire basé sur le modèle de lecture stratifiée.
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Passes:
- Pass 0: Extraction + Structural Graph (Document, Section, DocItem)
- Pass 1: Lecture Stratifiée (Subject, Theme, Concept, Information)
- Pass 2: Enrichissement (Relations inter-concepts)
- Pass 3: Consolidation Corpus (Entity Resolution cross-doc)
"""

__version__ = "2.0.0"
