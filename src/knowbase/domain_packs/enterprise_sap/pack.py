# src/knowbase/domain_packs/enterprise_sap/pack.py
"""
EnterpriseSapPack — Domain Pack pour l'ecosysteme SAP.

NER zero-shot via GLiNER + gazetteer produits SAP.
Configuration chargee depuis context_defaults.json co-localise.
"""

from __future__ import annotations

from typing import List

from knowbase.domain_packs.base import DomainPack, DomainEntityExtractor


class EnterpriseSapPack(DomainPack):
    """Pack domaine SAP Enterprise.

    Acronymes, concepts cles, stoplist et gazetteer produits sont dans
    context_defaults.json (meme repertoire que ce fichier).
    """

    @property
    def name(self) -> str:
        return "enterprise_sap"

    @property
    def display_name(self) -> str:
        return "SAP Enterprise"

    @property
    def description(self) -> str:
        return (
            "NER zero-shot pour la documentation SAP Enterprise. "
            "Detecte les produits, modules, services et plateformes SAP "
            "via GLiNER (gliner_medium-v2.1) + gazetteer 530+ produits / 210+ acronymes."
        )

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return 100

    def get_entity_extractors(self) -> List[DomainEntityExtractor]:
        from knowbase.domain_packs.enterprise_sap.entity_extractor import (
            SapEntityExtractor,
        )
        return [SapEntityExtractor()]


__all__ = ["EnterpriseSapPack"]
