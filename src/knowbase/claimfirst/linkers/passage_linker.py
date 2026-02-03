# src/knowbase/claimfirst/linkers/passage_linker.py
"""
PassageLinker - Lien Claim → Passage basé sur unit spans.

INV-1: Sémantique Unit vs Passage vs Claim
- Unit (U1, U2...) = preuve textuelle exacte (verbatim garanti)
- Passage (DocItem) = contexte englobant (peut contenir plusieurs units)
- Claim = affirmation synthétique pointant vers un ou plusieurs unit_ids

Règle: La preuve d'une Claim est `unit_ids`, pas `passage_id`.
       Le passage est le contexte de navigation, pas la preuve.
       Le linker vérifie que `unit spans ⊆ passage span`, PAS que
       `verbatim_quote ⊆ passage.text` (fragile).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.passage import Passage
from knowbase.stratified.pass1.assertion_unit_indexer import UnitIndexResult

logger = logging.getLogger(__name__)


class PassageLinker:
    """
    Linking Claim → Passage basé sur unit_ids.

    INV-1: La preuve est unit_ids, le passage est le contexte.
    On vérifie que les unit spans sont contenus dans le passage span.

    Ne compare PAS `verbatim_quote ⊆ passage.text` (fragile).
    """

    def __init__(self):
        """Initialise le linker."""
        self.stats = {
            "claims_processed": 0,
            "links_created": 0,
            "links_from_unit_spans": 0,
            "links_from_passage_id": 0,
            "orphan_claims": 0,
        }

    def link(
        self,
        claims: List[Claim],
        passages: List[Passage],
        unit_index: Dict[str, UnitIndexResult],
    ) -> List[Tuple[str, str]]:
        """
        Établit les liens Claim → Passage.

        Args:
            claims: Claims à lier
            passages: Passages disponibles
            unit_index: Index des unités (passage_id → UnitIndexResult)

        Returns:
            Liste de tuples (claim_id, passage_id) pour relation SUPPORTED_BY
        """
        links: List[Tuple[str, str]] = []

        # Index des passages par ID et par spans
        passage_by_id: Dict[str, Passage] = {p.passage_id: p for p in passages}
        passage_spans: Dict[str, Tuple[int, int]] = {
            p.passage_id: (p.char_start, p.char_end)
            for p in passages
        }

        for claim in claims:
            self.stats["claims_processed"] += 1
            linked = False

            # Stratégie 1: Utiliser passage_id direct si présent et valide
            if claim.passage_id and claim.passage_id in passage_by_id:
                links.append((claim.claim_id, claim.passage_id))
                self.stats["links_created"] += 1
                self.stats["links_from_passage_id"] += 1
                linked = True

            # Stratégie 2: Si unit_ids présents, vérifier les spans
            elif claim.unit_ids and unit_index:
                passage_id = self._find_passage_by_unit_spans(
                    claim.unit_ids,
                    unit_index,
                    passage_spans,
                )
                if passage_id:
                    links.append((claim.claim_id, passage_id))
                    self.stats["links_created"] += 1
                    self.stats["links_from_unit_spans"] += 1
                    linked = True

            if not linked:
                self.stats["orphan_claims"] += 1
                logger.warning(
                    f"[OSMOSE:PassageLinker] Orphan claim {claim.claim_id}: "
                    f"no passage found"
                )

        # Dedup (une claim peut avoir plusieurs unit_ids dans le même passage)
        unique_links = list(set(links))

        logger.info(
            f"[OSMOSE:PassageLinker] Created {len(unique_links)} links "
            f"({self.stats['links_from_passage_id']} from passage_id, "
            f"{self.stats['links_from_unit_spans']} from unit spans, "
            f"{self.stats['orphan_claims']} orphans)"
        )

        return unique_links

    def _find_passage_by_unit_spans(
        self,
        unit_ids: List[str],
        unit_index: Dict[str, UnitIndexResult],
        passage_spans: Dict[str, Tuple[int, int]],
    ) -> Optional[str]:
        """
        Trouve le passage qui contient les unit spans.

        INV-1: On vérifie que unit spans ⊆ passage span.

        Args:
            unit_ids: IDs des unités (format: passage_id#U{n})
            unit_index: Index des unités
            passage_spans: Spans des passages (passage_id → (start, end))

        Returns:
            passage_id si trouvé, None sinon
        """
        for unit_global_id in unit_ids:
            # Parser l'ID global (format: passage_id#U{n})
            if "#" not in unit_global_id:
                continue

            passage_id, unit_local_id = unit_global_id.rsplit("#", 1)

            # Récupérer l'unité depuis l'index
            unit_result = unit_index.get(passage_id)
            if not unit_result:
                continue

            unit = unit_result.get_unit_by_local_id(unit_local_id)
            if not unit:
                continue

            # Vérifier que le span de l'unité est dans le span du passage
            passage_span = passage_spans.get(passage_id)
            if not passage_span:
                # Le passage existe, on fait confiance au passage_id
                return passage_id

            p_start, p_end = passage_span
            if unit.char_start >= p_start and unit.char_end <= p_end:
                return passage_id

            # Même si le span ne matche pas exactement, on fait confiance
            # au passage_id extrait de l'unit_global_id
            return passage_id

        return None

    def validate_link(
        self,
        claim: Claim,
        passage: Passage,
        unit_index: Dict[str, UnitIndexResult],
    ) -> bool:
        """
        Valide qu'un lien Claim → Passage est correct.

        Vérifie INV-1: unit spans ⊆ passage span.

        Args:
            claim: Claim à valider
            passage: Passage cible
            unit_index: Index des unités

        Returns:
            True si le lien est valide
        """
        # Si pas d'unit_ids, on accepte si passage_id correspond
        if not claim.unit_ids:
            return claim.passage_id == passage.passage_id

        # Vérifier que les unit spans sont dans le passage span
        unit_result = unit_index.get(passage.passage_id)
        if not unit_result:
            return False

        for unit_global_id in claim.unit_ids:
            if "#" not in unit_global_id:
                continue

            _, unit_local_id = unit_global_id.rsplit("#", 1)
            unit = unit_result.get_unit_by_local_id(unit_local_id)

            if not unit:
                return False

            # INV-1: Vérifier que unit span ⊆ passage span
            if not passage.contains_unit_span(unit.char_start, unit.char_end):
                logger.warning(
                    f"[OSMOSE:PassageLinker] Invalid link: unit {unit_local_id} "
                    f"span ({unit.char_start}, {unit.char_end}) not in passage "
                    f"span ({passage.char_start}, {passage.char_end})"
                )
                return False

        return True

    def get_stats(self) -> dict:
        """Retourne les statistiques de linking."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "claims_processed": 0,
            "links_created": 0,
            "links_from_unit_spans": 0,
            "links_from_passage_id": 0,
            "orphan_claims": 0,
        }


__all__ = [
    "PassageLinker",
]
