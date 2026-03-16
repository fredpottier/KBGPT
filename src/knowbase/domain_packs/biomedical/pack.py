# src/knowbase/domain_packs/biomedical/pack.py
"""
BiomedicalPack — Domain Pack pour les sciences de la vie.

NER via scispaCy (en_ner_bc5cdr_md) pour Chemical + Disease.
Configuration chargée depuis context_defaults.json co-localisé.
"""

from __future__ import annotations

from typing import List

from knowbase.domain_packs.base import DomainPack, DomainEntityExtractor


class BiomedicalPack(DomainPack):
    """Pack domaine Biomédical / Sciences de la vie.

    Acronymes, concepts clés et stoplist sont dans context_defaults.json
    (même répertoire que ce fichier), modifiable sans toucher au code.
    """

    @property
    def name(self) -> str:
        return "biomedical"

    @property
    def display_name(self) -> str:
        return "Biomedical / Sciences de la vie"

    @property
    def description(self) -> str:
        return (
            "NER spécialisé pour la littérature biomédicale et clinique. "
            "Détecte les entités chimiques (molécules, biomarqueurs) "
            "et les maladies via scispaCy (en_ner_bc5cdr_md)."
        )

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return 100

    def get_entity_extractors(self) -> List[DomainEntityExtractor]:
        from knowbase.domain_packs.biomedical.entity_extractor import (
            BiomedicalEntityExtractor,
        )
        return [BiomedicalEntityExtractor()]


__all__ = ["BiomedicalPack"]
