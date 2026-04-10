"""Domain Pack: Regulatory & Legal Documents."""

from __future__ import annotations

from typing import List

from knowbase.domain_packs.base import DomainPack, DomainEntityExtractor


class RegulatoryPack(DomainPack):
    @property
    def name(self) -> str:
        return "regulatory"

    @property
    def display_name(self) -> str:
        return "Regulatory & Legal"

    @property
    def description(self) -> str:
        return (
            "Domain pack for legal and regulatory documents. Covers data protection "
            "(GDPR, CCPA, PIPL), AI governance (AI Act, EO 14110, NIST RMF), digital "
            "markets (DMA, DSA), and international frameworks (OECD, UNESCO). "
            "Uses GLiNER zero-shot NER with a regulatory gazetteer of 55+ regulations."
        )

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return 100  # primary domain pack

    def get_entity_extractors(self) -> List[DomainEntityExtractor]:
        from knowbase.domain_packs.regulatory.entity_extractor import RegulatoryEntityExtractor
        return [RegulatoryEntityExtractor()]
