"""Domain Pack: Aerospace Certification & Dual-Use Export Control."""

from __future__ import annotations

from typing import List

from knowbase.domain_packs.base import DomainPack, DomainEntityExtractor


class AerospaceCompliancePack(DomainPack):
    @property
    def name(self) -> str:
        return "aerospace_compliance"

    @property
    def display_name(self) -> str:
        return "Aerospace Certification & Dual-Use Export Control"

    @property
    def description(self) -> str:
        return (
            "Domain pack for aerospace certification (EASA CS-25, FAR Part 25) and "
            "dual-use export control (Regulation 2021/821, predecessor 428/2009, "
            "Annex I delegated regulations). Detects certification standards, "
            "amendments, regulatory bodies (EASA, FAA, ICAO), dual-use items, "
            "international export control regimes (Wassenaar, MTCR, NSG, Australia "
            "Group), and jurisdictions. Uses GLiNER zero-shot NER with an aerospace "
            "+ export-control gazetteer."
        )

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return 100  # primary domain pack

    def get_entity_extractors(self) -> List[DomainEntityExtractor]:
        from knowbase.domain_packs.aerospace_compliance.entity_extractor import (
            AerospaceComplianceEntityExtractor,
        )
        return [AerospaceComplianceEntityExtractor()]
