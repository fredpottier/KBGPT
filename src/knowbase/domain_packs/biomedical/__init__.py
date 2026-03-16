# src/knowbase/domain_packs/biomedical/__init__.py
"""
Domain Pack Biomedical — Sciences de la vie.

NER spécialisé via scispaCy (en_ner_bc5cdr_md).
Détecte Chemical et Disease dans les claims isolées.
"""

from knowbase.domain_packs.biomedical.pack import BiomedicalPack

__all__ = ["BiomedicalPack"]
